"""Original songs: a written brief (optionally an image) becomes a sung track.

Pipeline:  brief/image -> ACE-Step (text2music) -> MDX vocal split ->
           RVC (xiaoxi timbre) -> post -> mix -> mp3

The ACE-Step code and its diffusers/transformers pins are heavy and conflict with
the RVC environment, so they are *not* imported at module load.  Point
``XIAOXI_ACESTEP_LIBS`` at a directory that holds the ``acestep`` package plus a
compatible ``diffusers``/``transformers`` and they will be prepended to
``sys.path`` only when a song is actually generated.

Weights live in ``XIAOXI_ACESTEP_MODEL`` (default ``<repo>/models/ace-step``) and
must contain ``ace_step_transformer/``, ``music_dcae_f8c8/``, ``music_vocoder/``
and ``umt5-base/``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from . import mix as mixmod
from .engine import RvcEngine
from .song import separate

ProgressFn = Callable[[str, float], None]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = Path(os.environ.get("XIAOXI_ACESTEP_MODEL", REPO_ROOT / "models" / "ace-step"))
DEFAULT_LIBS = Path(os.environ.get("XIAOXI_ACESTEP_LIBS", REPO_ROOT / "orig" / "pylibs"))

# 中文歌词的分段标记（ACE-Step 用 [verse]/[chorus] 之类的结构标签）
DEFAULT_TAGS = ["[verse]", "[chorus]", "[bridge]", "[outro]"]


class ComposeError(RuntimeError):
    """Raised when a stage of original-song generation fails."""


@dataclass
class ComposeResult:
    song: Path              # ACE-Step 原始输出（人声+伴奏混在一起）
    vocal: Optional[Path] = None
    inst: Optional[Path] = None
    sung: Optional[Path] = None   # 换成小汐音色的人声
    final: Optional[Path] = None  # 混音成品 mp3
    prompt: str = ""
    lyrics: str = ""
    image_brief: dict = field(default_factory=dict)
    seconds: float = 0.0


# --------------------------------------------------------------------- engine
_pipe = None


def _prepend_libs(libs: Path) -> None:
    p = str(libs)
    if not Path(p).is_dir():
        raise ComposeError(
            f"ACE-Step 依赖目录不存在：{p}\n"
            "设置 XIAOXI_ACESTEP_LIBS 指向含 acestep/diffusers/transformers 的目录。"
        )
    if p not in sys.path:
        sys.path.insert(0, p)


def load_pipeline(model_dir: Path | str | None = None, *, device_id: int = 0,
                  dtype: str = "bfloat16", cpu_offload: bool = False, libs: Path | str | None = None):
    """Load (once) and return the ACE-Step pipeline."""
    global _pipe
    if _pipe is not None:
        return _pipe
    model_dir = Path(model_dir or DEFAULT_MODEL_DIR)
    for need in ("ace_step_transformer", "music_dcae_f8c8", "music_vocoder", "umt5-base"):
        if not (model_dir / need).is_dir():
            raise ComposeError(f"缺少权重目录：{model_dir / need}")
    _prepend_libs(Path(libs or DEFAULT_LIBS))
    try:
        from acestep.pipeline_ace_step import ACEStepPipeline  # type: ignore
    except Exception as exc:  # pragma: no cover - 环境问题
        raise ComposeError(f"导入 ACE-Step 失败：{exc}") from exc
    _pipe = ACEStepPipeline(
        checkpoint_dir=str(model_dir),
        device_id=device_id,
        dtype=dtype,
        cpu_offload=cpu_offload,
    )
    return _pipe


def _tag_lyrics(lyrics: str) -> str:
    """把纯文本歌词按空行分段，插入 [verse]/[chorus] 标签（已带标签则原样返回）。"""
    if "[" in lyrics:
        return lyrics
    blocks = [b.strip() for b in lyrics.split("\n\n") if b.strip()]
    if not blocks:
        return lyrics
    out = []
    for i, b in enumerate(blocks):
        if i == 0:
            tag = "[verse]"
        elif i == len(blocks) - 1:
            tag = "[outro]"
        else:
            tag = "[chorus]" if i % 2 else "[verse]"
        out.append(f"{tag}\n{b}")
    return "\n\n".join(out)


# ------------------------------------------------------------------ generation
def generate(
    prompt: str,
    lyrics: str = "",
    *,
    duration: float = 120.0,
    out_path: Path | str | None = None,
    seed: int | None = None,
    steps: int = 60,
    guidance: float = 15.0,
    model_dir: Path | str | None = None,
    progress: ProgressFn | None = None,
) -> Path:
    """Text prompt (+ lyrics) -> one audio file with vocals and backing."""
    pipe = load_pipeline(model_dir)
    out_path = Path(out_path or (REPO_ROOT / "runtime" / f"compose_{int(time.time())}.flac"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("生成中（ACE-Step）", 0.15)
    t0 = time.time()
    pipe(
        prompt=prompt,
        lyrics=_tag_lyrics(lyrics) if lyrics else "",
        audio_duration=float(duration),
        infer_step=int(steps),
        guidance_scale=float(guidance),
        manual_seeds=[int(seed)] if seed is not None else None,
        save_path=str(out_path),
        format=out_path.suffix.lstrip(".") or "flac",
        batch_size=1,
    )
    if not out_path.exists():
        # 有些版本会自己改扩展名
        cand = sorted(out_path.parent.glob(out_path.stem + ".*"), key=lambda p: p.stat().st_mtime)
        if not cand:
            raise ComposeError("ACE-Step 跑完但没找到输出文件")
        out_path = cand[-1]
    if progress:
        progress(f"生成完成（{time.time() - t0:.0f}s）", 0.45)
    return out_path


# --------------------------------------------------------------------- vision
def describe_image(image_path: Path | str, *, question: str | None = None,
                   base_url: str | None = None, api_key: str | None = None,
                   model: str | None = None, timeout: float = 60.0) -> dict:
    """Ask a vision model what the picture wants to become (JSON dict).

    需要一个 OpenAI 兼容的多模态端点：``VISION_BASE_URL`` / ``VISION_API_KEY`` /
    ``VISION_MODEL``（或显式传入）。没有配置时抛 ComposeError，让调用方退化成
    「让用户用文字描述」。
    """
    import base64
    import urllib.request

    base_url = base_url or os.environ.get("VISION_BASE_URL") or os.environ.get("LLM_BASE_URL")
    api_key = api_key or os.environ.get("VISION_API_KEY") or os.environ.get("LLM_API_KEY")
    model = model or os.environ.get("VISION_MODEL")
    if not (base_url and api_key and model):
        raise ComposeError(
            "没有配置多模态模型：设置 VISION_BASE_URL / VISION_API_KEY / VISION_MODEL，"
            "或直接用文字把图片内容描述给它。"
        )
    raw = Path(image_path).read_bytes()
    b64 = base64.b64encode(raw).decode()
    mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    q = question or (
        "看这张图，推测用户想要的原创歌曲。只输出 JSON："
        '{"theme": "...", "mood": "...", "genre": "...", "instrumentation": "...", '
        '"tempo": "...", "lyrics_outline": "..."}，用中文填写，不要解释。'
    )
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": q},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode())
    text = data["choices"][0]["message"]["content"]
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return {"raw": text}


# ------------------------------------------------------------------- pipeline
def compose(
    brief: str,
    *,
    lyrics: str = "",
    image: Path | str | None = None,
    duration: float = 120.0,
    prompt_hint: str = "",
    seed: int | None = None,
    steps: int = 60,
    out_dir: Path | str | None = None,
    model_dir: Path | str | None = None,
    engine: RvcEngine | None = None,
    up_key: int = 0,
    progress: ProgressFn | None = None,
) -> ComposeResult:
    """Brief (+ optional image) -> a finished song sung in the xiaoxi voice."""
    t0 = time.time()
    out_dir = Path(out_dir or (REPO_ROOT / "runtime" / f"orig_{int(time.time())}"))
    out_dir.mkdir(parents=True, exist_ok=True)

    image_brief: dict = {}
    if image:
        try:
            image_brief = describe_image(image)
        except ComposeError:
            image_brief = {}

    prompt = " ".join(x for x in (brief, prompt_hint, str(image_brief.get("genre", "")),
                                  str(image_brief.get("mood", ""))) if x).strip()
    if not prompt:
        raise ComposeError("没有可用的文字描述")

    raw = generate(prompt, lyrics, duration=duration, out_path=out_dir / "song.flac",
                   seed=seed, steps=steps, model_dir=model_dir, progress=progress)

    if progress:
        progress("分离人声", 0.5)
    vocal, inst = separate(raw, out_dir / "stems")

    if progress:
        progress("换成小汐音色", 0.6)
    eng = engine or RvcEngine()
    sung = eng.convert(vocal, out_dir / "sung.wav")

    if progress:
        progress("混音", 0.92)
    final = mixmod.mix_cover(sung, inst, out_dir / "final.mp3")
    if progress:
        progress("完成", 1.0)

    return ComposeResult(
        song=raw, vocal=vocal, inst=inst, sung=sung, final=final,
        prompt=prompt, lyrics=lyrics, image_brief=image_brief,
        seconds=time.time() - t0,
    )
