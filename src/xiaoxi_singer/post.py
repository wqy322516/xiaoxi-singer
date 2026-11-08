"""Post-processing chain for converted vocals.

The chain is deliberately conservative: RVC output is already a plausible voice,
and stacking exciters / shelves / tanh stages on top of it is what turns a good
conversion into something metallic. Every stage can be switched off.

Order matters and mirrors what was tuned by ear on real renders:

1. 55 Hz high-pass (rumble)
2. harmonic exciter (1-5 kHz driven, band-limited to 3.5-9.5 kHz)  -- ``--hf``
3. high shelf above 4 kHz                                          -- ``--shelf``
4. de-harshing between 2.5 and 5 kHz (transient-aware)
5. optional high-frequency borrow from the source vocal            -- ``--src-hf``
6. small synthetic reverb                                          -- ``--reverb``
7. noise gate (clean tails)                                        -- ``--gate``
8. soft limiter and peak normalisation
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

SR = 24000


def bandpass(x: np.ndarray, lo: float, hi: float, order: int = 4, sr: int = SR) -> np.ndarray:
    sos = signal.butter(order, [lo, hi], btype="bandpass", fs=sr, output="sos")
    return signal.sosfilt(sos, x).astype(np.float32)


def noise_gate(x: np.ndarray, thr_db: float = -44.0, ratio: float = 3.0, attack_ms: float = 4.0,
               release_ms: float = 140.0, sr: int = SR) -> np.ndarray:
    """Downward expander on a 20 ms RMS envelope (fast close, slow open)."""
    win = max(1, int(0.020 * sr))
    pad = np.pad(np.abs(x), (win // 2, win // 2), mode="edge")
    env = np.sqrt(signal.convolve(pad ** 2, np.ones(win) / win, mode="valid"))[: len(x)]
    thr = 10 ** (thr_db / 20)
    gain = np.ones_like(env)
    below = env < thr
    gain[below] = np.clip((env[below] / thr) ** (ratio - 1), 0.05, 1.0)
    a_att = np.exp(-1.0 / (attack_ms * sr / 1000))
    a_rel = np.exp(-1.0 / (release_ms * sr / 1000))
    out = np.empty_like(gain)
    g = 1.0
    for i, target in enumerate(gain):
        a = a_att if target < g else a_rel
        g = a * g + (1 - a) * target
        out[i] = g
    return (x * out).astype(np.float32)


def post_process(
    in_wav: str | Path,
    out_wav: str | Path,
    *,
    hf: float = 0.18,
    shelf: float = 3.0,
    reverb: float = 0.08,
    gate: float = -40.0,
    gate_ratio: float = 3.0,
    src_wav: str | Path | None = None,
    src_hf: float = 0.0,
) -> Path:
    w, sr = sf.read(str(in_wav), dtype="float32", always_2d=True)
    w = w.mean(axis=1)
    if sr != SR:
        w = signal.resample_poly(w, SR, sr).astype(np.float32)
        sr = SR
    w = w / (np.abs(w).max() + 1e-9)

    # 1) rumble
    w = signal.sosfilt(signal.butter(4, 55, btype="highpass", fs=sr, output="sos"), w).astype(np.float32)

    # 2) exciter: generate harmonics for the top octave the model tends to lose
    if hf > 0:
        drive = bandpass(w, 1000, 5000, sr=sr)
        driven = np.tanh(drive * 2.5)
        exc = bandpass(driven, 3500, 9500, sr=sr)
        exc = exc / (np.abs(exc).max() + 1e-9)
        env = np.abs(w)
        env = signal.convolve(env, np.ones(480) / 480, mode="same")
        env = env / (env.max() + 1e-9)
        w = w + exc * env * hf

    # 3) shelf above 4 kHz (SHELF_DB = 0 keeps it off; this stage is the main source of buzz)
    if shelf:
        hi = signal.sosfilt(signal.butter(2, 4000, btype="highpass", fs=sr, output="sos"), w)
        w = (w - hi) + hi * (10 ** (shelf / 20))

    # 4) de-harsh 2.5-5 kHz: only tame the loudest 5 % of bins
    n_fft, hop = 1024, 256
    f, _, Z = signal.stft(w, fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    mag = np.abs(Z)
    band = (f >= 2500) & (f <= 5000)
    thr = np.percentile(mag[band], 95)
    gain = np.ones_like(mag)
    hot = mag > thr
    gain[hot] = np.clip(thr / (mag[hot] + 1e-9), 0.7, 1.0)
    _, w = signal.istft(mag * gain * np.exp(1j * np.angle(Z)), fs=sr, nperseg=n_fft, noverlap=n_fft - hop)
    w = w.astype(np.float32)

    # 5) borrow air from the original vocal (keeps consonants readable)
    if src_wav and src_hf > 0:
        s, ssr = sf.read(str(src_wav), dtype="float32", always_2d=True)
        s = s.mean(axis=1)
        if ssr != sr:
            s = signal.resample_poly(s, sr, ssr).astype(np.float32)
        n = min(len(s), len(w))
        sh = bandpass(s[:n], 4500, 11000, order=2, sr=sr)
        sh = sh / (np.abs(sh).max() + 1e-9)
        w[:n] = w[:n] + sh * src_hf

    # 6) reverb
    if reverb > 0:
        rng = np.random.default_rng(0)
        ir_len = int(0.35 * sr)
        ir = rng.standard_normal(ir_len) * np.exp(-np.arange(ir_len) / (0.10 * sr))
        ir[0] += 1.0
        ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
        wet = signal.fftconvolve(w, ir)[: len(w)].astype(np.float32)
        w = (1 - reverb) * w + reverb * wet

    # 7) gate after reverb, so the tail does not re-open the noise floor
    if gate < 0:
        w = noise_gate(w, thr_db=gate, ratio=gate_ratio, sr=sr)

    # 8) soft limit
    w = np.tanh(w * 1.05)
    w = (w / (np.abs(w).max() + 1e-9) * 0.92).astype(np.float32)
    sf.write(str(out_wav), w, sr, subtype="FLOAT")
    return Path(out_wav)
