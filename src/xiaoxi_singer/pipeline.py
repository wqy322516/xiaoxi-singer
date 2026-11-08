"""The whole cover pipeline: convert -> post-process -> mix."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from .config import Settings, settings as default_settings
from .engine import RvcEngine
from .mix import mix_cover
from .post import post_process

Progress = Callable[[str, float], None]


def _noop(stage: str, pct: float) -> None:  # pragma: no cover - default hook
    return None


def render_vocal(
    vocal_wav: str | Path,
    out_wav: str | Path,
    *,
    settings: Settings | None = None,
    engine: RvcEngine | None = None,
    up_key: int | None = None,
    protect: float | None = None,
    progress: Progress = _noop,
) -> Path:
    """Convert a dry vocal stem and run the post chain. Returns a 24 kHz wav."""
    s = settings or default_settings
    engine = engine or RvcEngine(s)
    out_wav = Path(out_wav)

    progress("converting", 0.05)
    raw = out_wav.with_name(out_wav.stem + "_raw.wav")
    engine.convert(
        vocal_wav,
        raw,
        up_key=up_key,
        protect=protect,
        progress=lambda i, n, _stage: progress("converting", 0.05 + 0.75 * i / max(1, n)),
    )

    progress("post", 0.85)
    post_process(
        raw,
        out_wav,
        hf=s.post_hf,
        shelf=s.post_shelf,
        reverb=s.post_reverb,
        gate=s.post_gate,
        src_wav=vocal_wav,
    )
    progress("vocal done", 1.0)
    return out_wav


def render_cover(
    vocal_wav: str | Path,
    instrumental_wav: str | Path,
    out_mp3: str | Path,
    *,
    settings: Settings | None = None,
    engine: RvcEngine | None = None,
    up_key: int | None = None,
    protect: float | None = None,
    target_rms: float = 0.0,
    progress: Progress = _noop,
) -> Path:
    """Full cover: target-voice vocal + the original instrumental."""
    s = settings or default_settings
    s.ensure_dirs()
    out_mp3 = Path(out_mp3)
    vocal_out = out_mp3.with_name(out_mp3.stem + "_vocal.wav")

    render_vocal(
        vocal_wav,
        vocal_out,
        settings=s,
        engine=engine,
        up_key=up_key,
        protect=protect,
        progress=lambda stage, pct: progress(stage, 0.9 * pct),
    )

    progress("mixing", 0.95)
    mix_cover(
        vocal_out,
        instrumental_wav,
        out_mp3,
        target_rms=target_rms,
        ffmpeg=s.ffmpeg,
    )
    progress("done", 1.0)
    return out_mp3
