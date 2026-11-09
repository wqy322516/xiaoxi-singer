"""A self-contained agent: an LLM that plans, calls the voice tools, and checks its work.

This is what turns the repository from "a library" into "an agent". Without a brain
the tools just sit there; with the loop in this file you can say

    xiaoxi-singer agent "把 /data/verse.wav 唱成女声，和 /data/inst.wav 混成 /data/out.mp3"

and it will inspect the audio, decide on a transposition, convert, mix, and report.

The loop is deliberately small and auditable:

    plan -> call tool -> read result -> plan again -> ... -> answer to the user

Any OpenAI-compatible endpoint works (DeepSeek, OpenAI, a local vLLM). Configure with
``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL``.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import settings
from .mix import mix_cover
from .pipeline import render_cover, render_vocal
from .song import CoverError, cover_song as _whole_song, pick as _pick, search as _bili_search

SYSTEM_PROMPT = """你是「小汐」，一个会唱歌的 AI，手上有几件真实可用的音频工具。

原则：
- 先看事实再动手：拿到人声先 probe_audio（时长、基频中位数、有声比例），再决定要不要变调。
- 男声（基频中位 < 265Hz）用 up_key=+7 升成女声；女声不要乱升。
- 音频必须是「干声」；如果用户给的是带伴奏的成品，提醒他先分离人声，不要硬转。
- 出成品前确认伴奏和干声时长接近。
- 用户只说歌名（例如「唱一下晴天」）时，用 cover_song 一步做完：搜歌 → 下载 → 分离 → 换音色 → 混音。
- cover_song 的结果里带 qa：verdict 不是 pass 时，把 qa.issues 里的话原样告诉用户，别自己编。
- 用户要视频时给 cover_song 传 video=true（或对已有 mp3 用 make_video）。
- 用户要「原创/写一首/按这张图做歌」时用 compose_song；没配多模态模型（VISION_*）时，先请用户用文字描述图片内容。
- 做完用一句话汇报：文件在哪、做了什么处理、有什么听感风险（例如升调后高音可能更紧）。
- 不要编造文件的时长、参数或结果；只报工具返回的数字。
"""


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# --------------------------------------------------------------------- tools
def _probe(path: str) -> dict[str, Any]:
    """Facts an agent needs before choosing conversion settings."""
    import librosa
    import numpy as np
    import soundfile as sf

    w, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = w.mean(axis=1)
    dur = len(mono) / sr
    y16 = librosa.resample(mono, orig_sr=sr, target_sr=16000)
    f0, voiced, _ = librosa.pyin(y16, fmin=70, fmax=1100, sr=16000, frame_length=2048)
    v = f0[voiced & (f0 > 0)]
    median_f0 = float(np.median(v)) if len(v) else 0.0
    rms = float(np.sqrt((mono.astype(np.float64) ** 2).mean()))
    return {
        "path": path,
        "duration_s": round(dur, 2),
        "sample_rate": int(sr),
        "channels": int(w.shape[1]),
        "rms": round(rms, 4),
        "median_f0_hz": round(median_f0, 1),
        "voiced_ratio": round(float(np.mean(voiced)), 3),
        "suggested_up_key": 7 if 0 < median_f0 < 265 else 0,
        "suggested_protect": 0.9 if (median_f0 and median_f0 < 265) else 0.5,
    }


def _convert(vocal: str, out: str, up_key: int = 0, protect: float = -1.0) -> dict[str, Any]:
    prot = None if protect < 0 else protect
    path = render_vocal(vocal, out, up_key=up_key, protect=prot)
    return {"ok": True, "audio": str(path)}


def _cover(vocal: str, instrumental: str, out: str, up_key: int = 0, protect: float = -1.0,
           target_rms: float = 0.0) -> dict[str, Any]:
    prot = None if protect < 0 else protect
    path = render_cover(vocal, instrumental, out, up_key=up_key, protect=prot, target_rms=target_rms)
    return {"ok": True, "audio": str(path)}


def _mix(vocal: str, instrumental: str, out: str, target_rms: float = 0.0) -> dict[str, Any]:
    path = mix_cover(vocal, instrumental, out, target_rms=target_rms, ffmpeg=settings.ffmpeg)
    return {"ok": True, "audio": str(path)}



def _find_song(query: str, limit: int = 6) -> dict:
    try:
        cands = _bili_search(query, limit=limit)
    except CoverError as exc:
        return {"ok": False, "error": str(exc)}
    if not cands:
        return {"ok": False, "error": f"没搜到「{query}」"}
    best = _pick(cands, query)
    return {
        "ok": True,
        "best": {k: best[k] for k in ("bv", "title", "author", "secs") if k in best},
        "candidates": [{k: c[k] for k in ("bv", "title", "author", "secs") if k in c} for c in cands[:5]],
    }


def _cover_song(query: str, out: str, bv: str = "", audio: str = "", up_key: int | None = None,
                video: bool = False, lyrics: str = "") -> dict:
    try:
        return _whole_song(
            query or audio or bv,
            out,
            bv=bv or None,
            audio=audio or None,
            up_key=up_key,
            video=bool(video),
            lyrics=lyrics or None,
        )
    except CoverError as exc:
        return {"ok": False, "error": str(exc)}


def _make_video(audio: str, out: str, cover: str = "", lrc: str = "", title: str = "") -> dict:
    from .video import make_video

    try:
        return {"ok": True, **make_video(audio, out, cover=cover or None, lrc=lrc or None, title=title)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}



def _compose_song(brief: str, lyrics: str = "", image: str = "", duration: float = 90.0,
                  seed: int | None = None, out_dir: str = "") -> dict[str, Any]:
    """原创歌曲：ACE-Step 生成 -> 分离 -> 换成小汐音色 -> 混音。"""
    from .original import ComposeError, compose

    try:
        r = compose(
            brief,
            lyrics=lyrics or "",
            image=image or None,
            duration=float(duration or 90.0),
            seed=seed,
            out_dir=out_dir or None,
        )
    except ComposeError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "final": str(r.final),
        "song": str(r.song),
        "seconds": round(r.seconds, 1),
        "prompt": r.prompt,
        "image_brief": r.image_brief,
    }


TOOLS: list[Tool] = [
    Tool(
        "probe_audio",
        "分析一段音频：时长、采样率、RMS、基频中位数、有声比例，并给出建议的 up_key / protect。",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "音频文件路径"}},
            "required": ["path"],
        },
        _probe,
    ),
    Tool(
        "convert_vocal",
        "把一段干声换成小汐的音色（不含伴奏、不做混音）。",
        {
            "type": "object",
            "properties": {
                "vocal": {"type": "string"},
                "out": {"type": "string"},
                "up_key": {"type": "integer", "description": "半音数，男声转女声用 7"},
                "protect": {"type": "number", "description": "0-1，-1 表示用默认 0.5"},
            },
            "required": ["vocal", "out"],
        },
        _convert,
    ),
    Tool(
        "render_cover",
        "一步到位：干声换音色 + 与伴奏混音，输出 mp3 成品。",
        {
            "type": "object",
            "properties": {
                "vocal": {"type": "string"},
                "instrumental": {"type": "string"},
                "out": {"type": "string"},
                "up_key": {"type": "integer"},
                "protect": {"type": "number"},
                "target_rms": {"type": "number", "description": "成品目标响度，0 表示不强制"},
            },
            "required": ["vocal", "instrumental", "out"],
        },
        _cover,
    ),
    Tool(
        "mix_only",
        "只做混音：已转换好的人声 + 伴奏 → mp3。",
        {
            "type": "object",
            "properties": {
                "vocal": {"type": "string"},
                "instrumental": {"type": "string"},
                "out": {"type": "string"},
                "target_rms": {"type": "number"},
            },
            "required": ["vocal", "instrumental", "out"],
        },
        _mix,
    ),
    Tool(
        "find_song",
        "在 B站搜一首歌，返回最像官方整首的那条（BV 号、标题、时长、候选列表）。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "歌名，可带歌手，例如「林俊杰 美人鱼」"},
                "limit": {"type": "integer", "description": "返回几条候选，默认 6"},
            },
            "required": ["query"],
        },
        _find_song,
    ),
    Tool(
        "cover_song",
        "整首翻唱一步到位：搜歌 → 下载 → MDX 分离人声/伴奏 → 换成小汐音色 → 后期 → 混音，输出 mp3。"
        "也可以传 audio（本地带伴奏的成品）跳过搜索下载。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "歌名；给了 audio 时可留空"},
                "out": {"type": "string", "description": "输出 mp3 路径"},
                "bv": {"type": "string", "description": "已知 BV 号时直接指定"},
                "audio": {"type": "string", "description": "本地音频（带伴奏的成品），跳过搜索下载"},
                "up_key": {"type": "integer", "description": "半音数；男声歌留空会自动判 +7"},
                "video": {"type": "boolean", "description": "顺便渲染带歌词的 mp4（会自动转写歌词）"},
                "lyrics": {"type": "string", "description": "已有 .lrc 时传路径，省掉转写"},
            },
            "required": ["out"],
        },
        _cover_song,
    ),
    Tool(
        "make_video",
        "把已经做好的 mp3 渲染成带歌词的 mp4；不给 lrc 就自动转写。",
        {
            "type": "object",
            "properties": {
                "audio": {"type": "string"},
                "out": {"type": "string"},
                "cover": {"type": "string", "description": "封面图，可留空"},
                "lrc": {"type": "string", "description": "现成的 .lrc，可留空"},
                "title": {"type": "string", "description": "画面左上角的标题"},
            },
            "required": ["audio", "out"],
        },
        _make_video,
    ),
    Tool(
        "compose_song",
        "做一首原创歌曲：给文字需求（可选图片路径），ACE-Step 生成整首 -> 分离人声 -> 换成小汐音色 -> 混音成 mp3。",
        {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "description": "想要什么样的歌：主题、风格、情绪、参考曲风"},
                "lyrics": {"type": "string", "description": "歌词（可选，不给就由模型自己唱）"},
                "image": {"type": "string", "description": "图片路径（可选，需要多模态模型才能读）"},
                "duration": {"type": "number", "description": "时长秒数，默认 90，最长约 240"},
                "seed": {"type": "integer", "description": "随机种子，想复现同一首歌时给固定值"},
            },
            "required": ["brief"],
        },
        _compose_song,
    ),
]

TOOL_MAP = {t.name: t for t in TOOLS}


# ----------------------------------------------------------------------- LLM
@dataclass
class AgentConfig:
    base_url: str = field(default_factory=lambda: os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", "deepseek-chat"))
    max_steps: int = field(default_factory=lambda: int(os.environ.get("LLM_MAX_STEPS", "12")))
    temperature: float = 0.2


def _chat(cfg: AgentConfig, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    if not cfg.api_key:
        raise RuntimeError("set LLM_API_KEY (any OpenAI-compatible endpoint works)")
    body = json.dumps(
        {
            "model": cfg.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": cfg.temperature,
        }
    ).encode()
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"},
    )
    # Honour HTTPS_PROXY / ALL_PROXY explicitly: urlopen would otherwise ignore the
    # system proxy on Windows, which is exactly where an agent usually runs.
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("ALL_PROXY")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy else urllib.request.build_opener()
    for attempt in range(3):
        try:
            with opener.open(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:  # surface the server's message
            detail = exc.read().decode(errors="replace")[:400]
            if attempt == 2:
                raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("unreachable")


def run_agent(
    task: str,
    cfg: AgentConfig | None = None,
    *,
    trace: bool = True,
    on_step: "Callable[[dict[str, Any]], None] | None" = None,
) -> dict[str, Any]:
    """Run one task to completion. Returns the transcript plus the final answer."""
    cfg = cfg or AgentConfig()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    schemas = [t.schema() for t in TOOLS]
    steps: list[dict[str, Any]] = []

    for _ in range(cfg.max_steps):
        resp = _chat(cfg, messages, schemas)
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return {"ok": True, "answer": msg.get("content", ""), "steps": steps}

        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool = TOOL_MAP.get(name)
            started = time.time()
            if tool is None:
                result: Any = {"ok": False, "error": f"unknown tool {name}"}
            else:
                try:
                    result = tool.fn(**args)
                except Exception as exc:  # noqa: BLE001 - the model should see failures
                    result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            elapsed = round(time.time() - started, 2)
            steps.append({"tool": name, "args": args, "result": result, "seconds": elapsed})
            if on_step is not None:
                try:
                    on_step(steps[-1])
                except Exception:  # a broken listener must never kill the run
                    pass
            if trace:
                brief = json.dumps(result, ensure_ascii=False)
                print(f"  → {name}({json.dumps(args, ensure_ascii=False)})  [{elapsed}s]  {brief[:160]}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {"ok": False, "answer": "超过最大步数仍未完成", "steps": steps}


def _print_plan(task: str) -> None:
    print(f'任务：{task}')


def cli_main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser("xiaoxi-singer agent", description="LLM-driven singing-voice agent")
    p.add_argument("task", help="用自然语言描述要做什么")
    p.add_argument("--model", default=None)
    p.add_argument("--base-url", default=None, dest="base_url")
    p.add_argument("--max-steps", type=int, default=None, dest="max_steps")
    a = p.parse_args(argv)

    cfg = AgentConfig()
    if a.model:
        cfg.model = a.model
    if a.base_url:
        cfg.base_url = a.base_url
    if a.max_steps:
        cfg.max_steps = a.max_steps

    _print_plan(a.task)
    out = run_agent(a.task, cfg)
    print("\n" + out["answer"])
    return 0 if out["ok"] else 1
