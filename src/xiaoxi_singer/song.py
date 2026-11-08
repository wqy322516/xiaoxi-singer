"""Whole-song covers without a human in the loop.

``cover_song("周杰伦 晴天")`` does what the QQ bot does by hand:

    search Bilibili -> pick the official upload -> download the best audio
    -> MDX separate vocals/instrumental -> convert vocals to the target voice
    -> post-process -> mix -> 256k mp3

Every step is best-effort and reports progress through ``progress(stage, pct)``,
so the agent (and the desktop client) can show what is happening.

Only the *vocal stem* is model-generated: the instrumental always comes from the
original recording, never from the model.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path

from .config import Settings

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Bilibili WBI signing table (fixed by the API)
MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

BAD_WORDS = (
    "翻唱", "cover", "伴奏", "纯音乐", "教学", "合集", "串烧", "reaction", "听",
    "剪辑", "片段", "DJ", "remix", "钢琴", "吉他", "混音", "解说", "盘点",
    "vlog", "体验", "一天", "挑战", "探店", "日常", "直播回放", "访谈", "综艺",
    "短剧", "整活", "搞笑", "街访", "开箱", "测评",
)
GOOD_WORDS = ("官方", "mv", "原曲", "hi-res", "hires", "无损", "4k")
LABELS = ("索尼音乐", "华纳", "环球", "太合", "摩登", "音悦台", "滚石", "相信音乐")


class CoverError(RuntimeError):
    """A step of the whole-song pipeline failed, with a human-readable reason."""


# ---------------------------------------------------------------- bilibili I/O
def _requests():
    try:
        import requests  # noqa: F401
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise CoverError(
            "整首翻唱需要 requests / audio-separator，装一下：pip install 'xiaoxi-singer[full]'"
        ) from exc
    import requests

    return requests


def _session(proxy: str | None = None):
    requests = _requests()
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    # 风控看 buvid：旧 cookie 被标记后搜索只回 v_voucher，所以每次发新的
    s.cookies.set("buvid3", str(uuid.uuid4()).upper() + "infoc", domain=".bilibili.com")
    s.cookies.set("b_nut", str(int(time.time())), domain=".bilibili.com")
    if proxy:
        s.proxies.update({"http": proxy, "https": proxy})
    return s


def _wbi(sess) -> str:
    nav = sess.get("https://api.bilibili.com/x/web-interface/nav", timeout=20).json()
    img = nav["data"]["wbi_img"]["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub = nav["data"]["wbi_img"]["sub_url"].rsplit("/", 1)[1].split(".")[0]
    orig = img + sub
    return "".join(orig[i] for i in MIXIN_TAB)[:32]


def search(query: str, limit: int = 8, proxy: str | None = None) -> list[dict]:
    """Search Bilibili; retries with a fresh buvid, plain endpoint, then a proxy."""
    attempts = [(proxy, True), (proxy, False), (None, True), (None, False)]
    raw: list[dict] = []
    for px, wbi in attempts:
        try:
            sess = _session(px)
            params = {"search_type": "video", "keyword": query, "page": 1}
            if wbi:
                params["wts"] = str(int(time.time()))
                params = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in params.items()}
                qs = urllib.parse.urlencode(sorted(params.items()))
                try:
                    params["w_rid"] = hashlib.md5((qs + _wbi(sess)).encode()).hexdigest()
                except Exception:
                    pass
                url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
            else:
                url = "https://api.bilibili.com/x/web-interface/search/type"
            raw = ((sess.get(url, params=params, timeout=20).json().get("data") or {}).get("result")) or []
        except Exception:
            raw = []
        if raw:
            break
        time.sleep(1.5)

    out = []
    for it in raw:
        bv = it.get("bvid")
        if not bv:
            continue
        title = re.sub(r"<[^>]+>", "", it.get("title") or "").strip()
        title = title.replace("&quot;", '"').replace("&amp;", "&")
        secs = 0
        try:
            parts = [int(x) for x in (it.get("duration") or "0:00").split(":")]
            secs = parts[0] * 60 + parts[1] if len(parts) == 2 else parts[0] * 3600 + parts[1] * 60 + parts[2]
        except Exception:
            pass
        out.append({"bv": bv, "title": title, "author": it.get("author") or "",
                    "secs": secs, "play": it.get("play") or 0})
    out.sort(key=lambda x: -x["play"])
    return out[:limit]


def pick(cands: list[dict], query: str = "") -> dict | None:
    """Prefer a full official upload: drop covers/karaoke/vlogs, boost label accounts."""
    scored = []
    for c in cands:
        if not (90 <= c.get("secs", 0) <= 480):
            continue
        t = (c.get("title") or "").lower()
        if any(w.lower() in t for w in BAD_WORDS):
            continue
        score = float(c.get("play") or 0) or 1.0
        for tok in [w for w in re.split(r"[\s,，、]+", query or "") if len(w) >= 2]:
            if tok.lower() in t:
                score *= 2.0
        if any(w in t for w in GOOD_WORDS):
            score *= 3.0
        if any(w in (c.get("author") or "") for w in LABELS):
            score *= 5.0
        scored.append((score, c))
    if scored:
        scored.sort(key=lambda x: -x[0])
        return scored[0][1]
    good = [c for c in cands if 90 <= c.get("secs", 0) <= 480]
    return good[0] if good else (cands[0] if cands else None)


def download(bv: str, out_wav: Path, *, ffmpeg: str = "ffmpeg", proxy: str | None = None) -> Path:
    """Fetch the highest-bitrate dash audio track and decode it to mono wav."""
    sess = _session(proxy)
    view = sess.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bv}, timeout=20).json()
    if view.get("code") != 0:
        raise CoverError(f"B站 拿不到视频信息：{view.get('message')}")
    cid = view["data"]["cid"]
    play = sess.get(
        "https://api.bilibili.com/x/player/playurl",
        params={"bvid": bv, "cid": cid, "fnval": 4048, "fourk": 1},
        timeout=20,
    ).json()
    if play.get("code") != 0:
        raise CoverError(f"B站 拿不到音频地址：{play.get('message')}")
    audios = (play["data"].get("dash") or {}).get("audio") or []
    if not audios:
        raise CoverError("这条视频没有 dash 音轨")
    audios.sort(key=lambda a: a.get("bandwidth", 0), reverse=True)
    url = audios[0].get("baseUrl") or audios[0].get("base_url")

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_wav.with_suffix(".m4a")
    have = tmp.stat().st_size if tmp.exists() else 0
    for attempt in range(1, 6):
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with sess.get(url, stream=True, timeout=120, headers=headers) as r:
                if r.status_code not in (200, 206):
                    r.raise_for_status()
                mode = "wb" if (not have or r.status_code == 200) else "ab"
                with open(tmp, mode) as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            break
        except Exception:
            have = tmp.stat().st_size if tmp.exists() else 0
            if attempt == 5:
                raise CoverError("下载音频失败（B站 CDN 反复中断）")
            time.sleep(2)

    exe = shutil.which(ffmpeg) or ffmpeg
    try:  # artwork for the video renderer; failure is not fatal
        pic = (view.get("data") or {}).get("pic")
        if pic:
            art = out_wav.with_suffix(".jpg")
            with sess.get(pic, stream=True, timeout=60) as r:
                with open(art, "wb") as f:
                    for chunk in r.iter_content(1 << 18):
                        f.write(chunk)
    except Exception:
        pass

    if subprocess.run([exe, "-v", "error", "-i", str(tmp), "-f", "null", "-"], capture_output=True).returncode != 0:
        tmp.unlink(missing_ok=True)
        raise CoverError("下载的音频不完整，已删除")
    subprocess.run([exe, "-y", "-loglevel", "error", "-i", str(tmp), "-ac", "1", "-ar", "48000", str(out_wav)],
                   check=True)
    tmp.unlink(missing_ok=True)
    return out_wav


# ------------------------------------------------------------------ separation
def separator_exe() -> str:
    exe = os.environ.get("SEPARATOR_EXE") or shutil.which("audio-separator")
    if not exe or not Path(exe).exists():
        raise CoverError(
            "没找到 audio-separator。装法：pip install 'audio-separator[cpu]'，"
            "或用 SEPARATOR_EXE 环境变量指向它的可执行文件。"
        )
    return exe


def _child_env(ffmpeg: str = "ffmpeg") -> dict:
    """audio-separator shells out to ffmpeg, so its folder has to be on PATH."""
    env = dict(os.environ)
    exe = shutil.which(ffmpeg) or ffmpeg
    parent = str(Path(exe).parent)
    if parent and parent not in env.get("PATH", ""):
        env["PATH"] = parent + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def separate(wav: Path, out_dir: Path, *, model: str | None = None, ffmpeg: str = "ffmpeg") -> tuple[Path, Path]:
    """MDX-Net Kim_Vocal_2: split ``wav`` into (vocals, instrumental)."""
    exe = separator_exe()
    model = model or os.environ.get("SEPARATOR_MODEL", "Kim_Vocal_2.onnx")
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out_dir.glob("*.wav")}
    r = subprocess.run([exe, str(wav), "-m", model, "--output_dir", str(out_dir),
                        "--output_format", "WAV"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=_child_env(ffmpeg))
    if r.returncode != 0:
        raise CoverError(f"分离失败：{(r.stderr or r.stdout or '').strip()[-300:]}")
    new = [p for p in out_dir.glob("*.wav") if p.name not in before]
    voc = next((p for p in new if "Vocals" in p.name), None)
    inst = next((p for p in new if "Instrumental" in p.name), None)
    if voc is None or inst is None:
        raise CoverError("分离跑完了但没找到输出的两条轨")
    return voc, inst

def _reuse_or_separate(raw: Path, work: Path, *, ffmpeg: str = "ffmpeg") -> tuple[Path, Path]:
    """Separating a 5-minute song costs minutes; reuse the stems of a previous run."""
    vocs = sorted(work.glob("*_(Vocals)_*.wav"))
    insts = sorted(work.glob("*_(Instrumental)_*.wav"))
    if vocs and insts:
        return vocs[-1], insts[-1]
    return separate(raw, work, ffmpeg=ffmpeg)

def _median_f0(wav: Path, dur: float = 60.0) -> float:
    try:
        import librosa
        import soundfile as sf
    except ImportError:
        return 0.0
    y, sr = sf.read(str(wav), dtype="float32", always_2d=False)
    if getattr(y, "ndim", 1) > 1:
        y = y.mean(axis=1)
    y = y[: int(sr * dur)]
    if sr != 16000:
        y = librosa.resample(y, orig_sr=sr, target_sr=16000)
        sr = 16000
    f0, voiced, _ = librosa.pyin(y, fmin=60, fmax=1100, sr=sr)
    import numpy as np

    v = f0[voiced & (f0 > 0)]
    return float(np.median(v)) if v.size else 0.0


def cover_song(
    query: str,
    out_mp3: str | Path,
    settings: Settings | None = None,
    *,
    bv: str | None = None,
    audio: str | Path | None = None,
    up_key: int | None = None,
    progress=None,
    proxy: str | None = None,
    video: bool = False,
    lyrics: str | Path | None = None,
) -> dict:
    """Search (or take a local mix), separate, convert, post-process, mix.

    Returns a dict with the paths and the decisions taken, so the agent can explain
    them instead of guessing.
    """
    from . import engine as engine_mod
    from . import mix as mix_mod
    from . import post as post_mod

    s = settings or Settings()
    s.ensure_dirs()
    out_mp3 = Path(out_mp3).resolve()
    work = (Path(s.work_dir) / "song").resolve()
    work.mkdir(parents=True, exist_ok=True)

    def step(stage: str, pct: int) -> None:
        if progress:
            progress(stage, pct)

    raw: Path
    title = query
    chosen_bv = bv
    if audio:
        raw = Path(audio)
        title = raw.stem
        step("读取本地音频", 20)
    else:
        step("搜索", 5)
        if not chosen_bv:
            cands = search(query, proxy=proxy)
            if not cands:
                raise CoverError(f"没搜到「{query}」")
            best = pick(cands, query)
            chosen_bv, title = best["bv"], best["title"]
        raw = work / f"{re.sub(r'[^0-9A-Za-z]+', '_', title)[:40] or chosen_bv}.wav"
        if not raw.exists():
            step("下载音轨", 12)
            download(chosen_bv, raw, ffmpeg=s.ffmpeg, proxy=proxy)
        step("下载完成", 25)

    tag = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", title).strip("_")[:40] or "song"
    step("分离人声", 30)
    voc, inst = _reuse_or_separate(raw, work, ffmpeg=s.ffmpeg)

    up = s.up_key if up_key is None else up_key
    if up_key is None:
        med = _median_f0(voc)
        if 0 < med < 265:
            up = 7  # male original -> female voice, a seventh up (matches the QQ pipeline)
    step("转换人声", 45)
    eng = engine_mod.RvcEngine(s)
    conv = eng.convert(
        voc, work / f"{tag}_conv.wav", up_key=up,
        progress=lambda *a: step(
            "转换人声", 45 + int(max(0.0, min(1.0, (a[0] / a[1]) if len(a) > 1 else 0.0)) * 35)
        ),
    )

    step("后期", 82)
    wet = post_mod.post_process(
        conv, work / f"{tag}_post.wav",
        hf=s.post_hf, shelf=s.post_shelf, reverb=s.post_reverb,
        gate=s.post_gate, src_wav=voc,
    )

    step("混音", 92)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    mix_mod.mix_cover(wet, inst, out_mp3, target_rms=0.20, ffmpeg=s.ffmpeg)

    step("自检", 96)
    from .qa import check_cover

    qa = check_cover(voc, conv, out_mp3)

    result = {
        "ok": True,
        "title": title,
        "bv": chosen_bv,
        "up_key": up,
        "raw": str(raw),
        "vocals": str(voc),
        "instrumental": str(inst),
        "converted": str(conv),
        "mp3": str(out_mp3),
        "qa": qa,
    }

    if video:
        step("渲染歌词视频", 98)
        from .video import make_video

        art = raw.with_suffix(".jpg")
        result["video"] = make_video(
            out_mp3,
            Path(str(out_mp3).rsplit(".", 1)[0] + ".mp4"),
            cover=art if art.exists() else None,
            lrc=lyrics,
            title=f"{title} · 小汐翻唱",
            query=title,
            ffmpeg=s.ffmpeg,
            work_dir=work / "_video",
        )

    step("完成", 100)
    return result

