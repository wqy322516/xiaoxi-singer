"""Lyrics: read/write LRC, and transcribe a vocal into timed lines.

The transcription path is optional (``pip install 'xiaoxi-singer[song]'`` gives you
``faster-whisper``). It exists so the video renderer has something to show when the
caller did not supply an LRC file.
"""

from __future__ import annotations

import re
from pathlib import Path


def read_lrc(path: str | Path) -> list[tuple[float, str]]:
    """Parse ``[mm:ss.xx] text`` lines into ``[(seconds, text), ...]``."""
    out: list[tuple[float, str]] = []
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\[(\d+):(\d+(?:[.:]\d+)?)\]\s*(.*)", raw.strip())
        if not m:
            continue
        mm, ss = int(m.group(1)), m.group(2).replace(":", ".")
        text = m.group(3).strip()
        if text:
            out.append((mm * 60 + float(ss), text))
    out.sort(key=lambda x: x[0])
    return out


def write_lrc(lines: list[tuple[float, str]], path: str | Path) -> Path:
    body = []
    for t, text in lines:
        mm, ss = divmod(max(0.0, t), 60)
        body.append(f"[{int(mm):02d}:{ss:05.2f}]{text}")
    p = Path(path)
    p.write_text("\n".join(body) + "\n", encoding="utf-8")
    return p


def transcribe(audio: str | Path, *, model_size: str = "medium", language: str = "zh",
               device: str = "cpu", compute_type: str = "int8") -> list[tuple[float, str]]:
    """Timed lyric lines from the *converted* vocal (what the listener actually hears)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "自动生成歌词需要 faster-whisper：pip install 'xiaoxi-singer[song]'"
        ) from exc

    m = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = m.transcribe(
        str(audio),
        language=language,
        vad_filter=True,
        beam_size=5,
        condition_on_previous_text=False,
        repetition_penalty=1.35,
    )
    lines = []
    prev = ""
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        # whisper 对唱腔容易复读，去掉和上一句一模一样的结果
        if text == prev:
            continue
        prev = text
        lines.append((float(seg.start), text))
    return lines


def from_netease(query: str, *, limit: int = 5) -> list[tuple[float, str]]:
    """Timestamped lyrics from NetEase Cloud Music (much better than ASR on singing)."""
    import json
    import urllib.parse
    import urllib.request

    def get(url: str) -> dict:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://music.163.com/",
        })
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    try:
        found = get("https://music.163.com/api/search/get/web?s="
                    + urllib.parse.quote(query) + f"&type=1&limit={limit}")
        songs = ((found.get("result") or {}).get("songs")) or []
        if not songs:
            return []
        best = max(songs, key=lambda x: (x.get("popularity") or 0, x.get("score") or 0))
        lrc = get(f"https://music.163.com/api/song/lyric?id={best['id']}&lv=-1&tv=-1")
        text = (lrc.get("lrc") or {}).get("lyric") or ""
    except Exception:
        return []

    out: list[tuple[float, str]] = []
    for raw in text.splitlines():
        m = re.match(r"\[(\d+):(\d+(?:[.:]\d+)?)\]\s*(.*)", raw.strip())
        if not m:
            continue
        mm, ss = int(m.group(1)), m.group(2).replace(":", ".")
        body = m.group(3).strip()
        if body:
            out.append((mm * 60 + float(ss), body))
    out.sort(key=lambda x: x[0])
    return out

