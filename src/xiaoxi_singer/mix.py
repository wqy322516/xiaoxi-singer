"""Loudness-aligned mixing of a converted vocal with an instrumental."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000


def _load(p: str | Path, sr: int = SR) -> np.ndarray:
    w, s = sf.read(str(p), dtype="float32", always_2d=True)
    w = w.mean(axis=1)
    if s != sr:
        import librosa

        w = librosa.resample(w, orig_sr=s, target_sr=sr).astype(np.float32)
    return w


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt((x.astype(np.float64) ** 2).mean()))


def limiter(x: np.ndarray, ceiling: float = 0.93, lookahead_ms: float = 4.0, release_ms: float = 80.0,
            sr: int = SR) -> np.ndarray:
    from numpy.lib.stride_tricks import sliding_window_view

    win = int(lookahead_ms * sr / 1000) | 1
    peak = np.abs(x)
    pad = np.pad(peak, (win // 2, win // 2), mode="edge")
    env = sliding_window_view(pad, win).max(axis=1)
    target = np.minimum(1.0, ceiling / np.maximum(env, 1e-9))
    a = np.exp(-1.0 / (release_ms * sr / 1000))
    sm = np.empty_like(target)
    g = 1.0
    for i, t in enumerate(target):
        g = min(t, a * g + (1 - a) * t)
        sm[i] = g
    return (x * sm).astype(np.float32)


def mix_cover(
    vocal_wav: str | Path,
    instrumental_wav: str | Path,
    out_mp3: str | Path,
    *,
    vocal_db: float = 0.0,
    inst_gain: float = 1.0,
    target_rms: float = 0.0,
    ffmpeg: str = "ffmpeg",
) -> Path:
    """Sum vocal and instrumental, limiter first, then land on ``target_rms``."""
    v, i = _load(vocal_wav), _load(instrumental_wav)
    n = min(len(v), len(i))
    v, i = v[:n], i[:n]

    v = v * (10 ** (vocal_db / 20))
    mix = v + i * inst_gain

    f = int(0.3 * SR)
    mix[:f] *= np.linspace(0, 1, f) ** 2
    mix[-f:] *= np.linspace(1, 0, f) ** 2
    mix = limiter(mix)

    if target_rms > 0:
        for _ in range(3):
            cur = _rms(mix)
            if cur <= 0:
                break
            mix = limiter(mix * (target_rms / cur), ceiling=0.97)

    mix = mix / (np.abs(mix).max() + 1e-9) * 0.95
    wav_path = Path(str(out_mp3).rsplit(".", 1)[0] + ".wav")
    sf.write(str(wav_path), mix.astype(np.float32), SR, subtype="PCM_16")

    exe = shutil.which(ffmpeg) or ffmpeg
    subprocess.run(
        [exe, "-y", "-loglevel", "error", "-i", str(wav_path), "-b:a", "256k", str(out_mp3)],
        check=True,
    )
    return Path(out_mp3)
