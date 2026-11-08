"""Self-check for a rendered cover.

The agent should not hand back an mp3 and hope: this compares the *converted* vocal
against the source vocal and reports things a listener would notice — dropped phrases,
noise where the singer is silent, pitch drift, brittle top end, clipping.

Everything here is numpy/soundfile only, so it runs on the same machine without a
second model. It is a smoke detector, not a golden ear: a ``warn`` means "listen to
this part", not "the render is broken".
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

SR = 24000


def _load(path: str | Path, sr: int = SR) -> np.ndarray:
    y, got = sf.read(str(path), dtype="float32", always_2d=False)
    if getattr(y, "ndim", 1) > 1:
        y = y.mean(axis=1)
    if got != sr:
        import librosa

        y = librosa.resample(y, orig_sr=got, target_sr=sr)
    return y


def _envelope(y: np.ndarray, win: float = 0.25) -> np.ndarray:
    hop = int(SR * win)
    n = len(y) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    return np.sqrt((y[: n * hop].reshape(n, hop) ** 2).mean(axis=1)).astype(np.float32)


def _db(x: np.ndarray) -> np.ndarray:
    return 20.0 * np.log10(np.maximum(x, 1e-8))


def _f0(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import librosa

    y16 = librosa.resample(y, orig_sr=SR, target_sr=16000) if SR != 16000 else y
    f0, voiced, _ = librosa.pyin(y16, fmin=60, fmax=1100, sr=16000, frame_length=2048)
    return f0, voiced


def _flatness(y: np.ndarray) -> float:
    """Spectral flatness on voiced frames only (noise/buzz shows up here)."""
    import librosa

    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    flat = librosa.feature.spectral_flatness(S=S)[0]
    rms = librosa.feature.rms(S=S)[0]
    keep = rms > max(1e-4, np.percentile(rms, 40))
    return float(np.median(flat[keep])) if keep.any() else float(np.median(flat))


def _hnr(y: np.ndarray) -> tuple[float, float]:
    """Harmonic-to-noise ratio per 40 ms frame, from the autocorrelation peak."""
    win, hop = 960, 480
    vals = []
    for start in range(0, max(1, len(y) - win), hop):
        f = y[start : start + win]
        if np.sqrt((f**2).mean()) < 1e-4:
            continue
        f = f - f.mean()
        ac = np.correlate(f, f, mode="full")[win - 1 :]
        ac /= ac[0] + 1e-9
        lo, hi = int(16000 / 700), int(16000 / 60)
        seg = ac[lo : min(hi, len(ac))]
        vals.append(float(seg.max()) if len(seg) else 0.0)
    if not vals:
        return 0.0, 0.0
    arr = np.array(vals)
    return float(np.median(arr)), float(np.percentile(arr, 10))


def check_cover(
    source_vocal: str | Path,
    converted_vocal: str | Path,
    mix: str | Path | None = None,
    *,
    drop_db: float = -35.0,
) -> dict:
    """Compare a converted vocal with the source it came from."""
    src, conv = _load(source_vocal), _load(converted_vocal)
    n = min(len(src), len(conv))
    src, conv = src[:n], conv[:n]

    se, ce = _envelope(src), _envelope(conv)
    se_db, ce_db = _db(se), _db(ce)
    loud = float(np.percentile(se_db, 75))
    silent_ref = loud - 45.0

    src_on = se_db > silent_ref
    conv_on = ce_db > silent_ref

    dropped = src_on & (ce_db < se_db + drop_db)
    added = (~src_on) & (ce_db > silent_ref)
    # merge neighbouring windows into readable ranges
    def spans(mask: np.ndarray) -> list[list[float]]:
        out, start = [], None
        for i, v in enumerate(mask):
            if v and start is None:
                start = i
            elif not v and start is not None:
                out.append([round(start * 0.25, 2), round(i * 0.25, 2)])
                start = None
        if start is not None:
            out.append([round(start * 0.25, 2), round(len(mask) * 0.25, 2)])
        return [s for s in out if s[1] - s[0] >= 0.5]

    dropped_spans = spans(dropped)
    added_spans = spans(added)

    # pitch: same melody, so semitone distance should stay near zero
    f_src, v_src = _f0(src)
    f_conv, v_conv = _f0(conv)
    m = min(len(f_src), len(f_conv))
    f_src, v_src, f_conv, v_conv = f_src[:m], v_src[:m], f_conv[:m], v_conv[:m]
    both = v_src & v_conv & (f_src > 0) & (f_conv > 0)
    if both.any():
        semi = 12 * np.log2(f_conv[both] / f_src[both])
        pitch_mae = float(np.mean(np.abs(semi)))
        pitch_bias = float(np.median(semi))
    else:
        pitch_mae = pitch_bias = 0.0

    flat_src, flat_conv = _flatness(src), _flatness(conv)
    hnr_src, hnr_src_p10 = _hnr(src)
    hnr_conv, hnr_conv_p10 = _hnr(conv)
    clips = int(np.sum(np.abs(conv) > 0.999))

    issues: list[str] = []
    if dropped_spans:
        issues.append(f"有 {len(dropped_spans)} 段比源人声轻了 35dB 以上：{dropped_spans[:4]}")
    if added_spans:
        issues.append(f"有 {len(added_spans)} 段源人声是静音、输出却有声：{added_spans[:4]}")
    if pitch_mae > 0.6:
        issues.append(f"音高跟随偏差偏大：平均 {pitch_mae:.2f} 半音（>0.6 该看）")
    if flat_conv > flat_src * 1.6:
        issues.append(f"频谱比源更平（噪/气声变多）：{flat_conv:.5f} vs {flat_src:.5f}")
    if hnr_conv_p10 < 0.15:
        issues.append(f"低音帧周期性差（容易破音）：HNR p10 {hnr_conv_p10:.2f}")
    if clips:
        issues.append(f"削波 {clips} 个采样点")

    if mix:
        m_audio = _load(mix)
        sr_rms = float(np.sqrt((m_audio**2).mean()))
    else:
        sr_rms = 0.0

    verdict = "pass" if not issues else ("warn" if len(issues) <= 2 else "fail")
    return {
        "verdict": verdict,
        "duration_s": round(n / SR, 2),
        "pitch_mae_semitones": round(pitch_mae, 3),
        "pitch_bias_semitones": round(pitch_bias, 3),
        "dropped_spans": dropped_spans[:6],
        "noise_spans": added_spans[:6],
        "flatness": {"source": round(flat_src, 5), "converted": round(flat_conv, 5)},
        "hnr": {
            "source_median": round(hnr_src, 2),
            "converted_median": round(hnr_conv, 2),
            "converted_p10": round(hnr_conv_p10, 2),
        },
        "clipping_samples": clips,
        "mix_rms": round(sr_rms, 4),
        "issues": issues,
    }
