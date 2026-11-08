"""RVC voice conversion, chunked so it survives small GPUs.

The upstream RVC demo converts a whole song in one pass, which OOMs on 8 GB cards
and drifts when you simply trim the output. This module instead:

* slices the source into fixed canvas slots (``chunk_s`` + ``overlap_s`` tail),
* converts each slice independently,
* writes every converted slice back onto a single time-indexed canvas with
  triangular cross-fades, so the total length is exactly the source length,
* applies a *source-referenced* silence gate (RVC hallucinates a 780 Hz tone when
  fed near-silence),
* detects spoken (non-melodic) passages and raises ``protect`` for them, because
  the model tends to "sing-ify" speech and turn it metallic.

Optional sweet-zone clamping (``RVC_SWEET``) is implemented inside the RVC fork;
see ``patches/rvc_sweet.patch``.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import soundfile as sf

from .config import Settings, settings as default_settings

ProgressFn = Callable[[int, int, str], None]


class RvcEngine:
    """One process-wide RVC session (the model stays loaded between calls)."""

    _lock = threading.Lock()

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or default_settings
        self._vc = None
        self._loaded_model: Optional[str] = None

    # ------------------------------------------------------------------ setup
    def _boot(self) -> None:
        root = str(self.s.rvc_root)
        if not Path(root).is_dir():
            raise RuntimeError(
                f"RVC_ROOT does not exist: {root}\n"
                "Run `bash scripts/install_rvc.sh` first (it clones the fork and applies patches/)."
            )
        if root not in sys.path:
            sys.path.insert(0, root)
        os.environ.setdefault("weight_root", os.path.join(root, "assets", "weights"))
        os.environ.setdefault("RVC_CUDA_GRAPH", "0")  # chunked calls + cudagraph do not mix

        from infer.cli import create_config  # type: ignore
        from infer.vc.modules import VC  # type: ignore

        cfg = create_config()
        self._vc = VC(cfg)

    def load(self, model_path: str | Path | None = None) -> None:
        # the RVC import chdir()s into its checkout; callers expect their cwd back
        cwd = os.getcwd()
        try:
            self._load_locked(model_path)
        finally:
            os.chdir(cwd)

    def _load_locked(self, model_path: str | Path | None = None) -> None:
        model = str(model_path or self.s.model_path)
        if not Path(model).is_file():
            raise FileNotFoundError(f"voice model not found: {model}")
        with self._lock:
            if self._vc is None:
                self._boot()
            if self._loaded_model != model:
                self._vc.get_vc(Path(model).name)  # type: ignore[union-attr]
                self._loaded_model = model

    # ------------------------------------------------------------------ pitch
    def _maybe_sweet(self, src_wav: str) -> None:
        """Clamp the top of the register only when the source really goes there.

        Clamping a source that never leaves 250-500 Hz only costs pitch accuracy,
        so the threshold is measured instead of assumed.
        """
        if os.environ.get("RVC_SWEET") or os.environ.get("RVC_SWEET_AUTO", "1") != "1":
            return
        try:
            import librosa

            y, _ = librosa.load(src_wav, sr=16000, mono=True, duration=120)
            f0, voiced, _ = librosa.pyin(y, fmin=80, fmax=1100, sr=16000, frame_length=2048)
            v = f0[voiced & (f0 > 0)]
            if len(v) > 20 and float(np.percentile(v, 95)) > 500:
                os.environ["RVC_SWEET"] = "250,500"
        except Exception:  # analysis is best-effort, never fatal
            pass

    # --------------------------------------------------------------- spoken
    def _spoken_mask(self, w: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        import librosa

        f0, voiced, _ = librosa.pyin(w, fmin=70, fmax=900, sr=sr, frame_length=2048, hop_length=512)
        times = librosa.frames_to_time(np.arange(len(f0)), sr=sr, hop_length=512)
        return times, f0, voiced.astype(float)

    # ------------------------------------------------------------------ gate
    @staticmethod
    def _gate_by_source(src: np.ndarray, mix: np.ndarray, sr: int, thr_db: float) -> np.ndarray:
        n = min(len(src), len(mix))
        win = max(1, int(0.02 * sr))
        p2 = src[:n].astype(np.float64) ** 2
        cs = np.concatenate([[0.0], np.cumsum(p2)])
        idx = np.arange(n)
        lo = np.maximum(0, idx - win // 2)
        hi = np.minimum(n, idx + win // 2 + 1)
        env = np.sqrt((cs[hi] - cs[lo]) / np.maximum(hi - lo, 1))
        mask = (env > 10 ** (thr_db / 20)).astype(np.float32)
        ks = max(1, int(0.01 * sr))
        cs2 = np.concatenate([[0.0], np.cumsum(mask.astype(np.float64))])
        lo2 = np.maximum(0, idx - ks // 2)
        hi2 = np.minimum(n, idx + ks // 2 + 1)
        smooth = ((cs2[hi2] - cs2[lo2]) / np.maximum(hi2 - lo2, 1)).astype(np.float32)
        out = mix[:n] * smooth
        if n < len(mix):
            out = np.concatenate([out, np.zeros(len(mix) - n, dtype=mix.dtype)])
        return out

    # ---------------------------------------------------------------- public
    def convert(
        self,
        src_wav: str | Path,
        out_wav: str | Path,
        *,
        up_key: int | None = None,
        protect: float | None = None,
        rms_mix: float | None = None,
        f0_method: str | None = None,
        chunk_s: float | None = None,
        overlap_s: float | None = None,
        progress: ProgressFn | None = None,
    ) -> Path:
        """Convert ``src_wav`` (a dry vocal stem) into the target voice."""
        s = self.s
        up_key = s.up_key if up_key is None else up_key
        protect = s.protect if protect is None else protect
        rms_mix = s.rms_mix if rms_mix is None else rms_mix
        f0_method = f0_method or s.f0_method
        chunk = chunk_s or s.chunk_s
        overlap = s.overlap_s if overlap_s is None else overlap_s

        self.load()
        self._maybe_sweet(str(src_wav))

        w, sr = sf.read(str(src_wav), dtype="float32", always_2d=False)
        if w.ndim > 1:
            w = w.mean(axis=1)
        dur = len(w) / sr

        starts = []
        t = 0.0
        while t < dur - 0.05:
            starts.append(t)
            t += chunk
        n = len(starts)

        sp_times = sp_f0 = sp_v = None
        if s.auto_spoken:
            sp_times, sp_f0, sp_v = self._spoken_mask(w, sr)

        canvas: dict[int, np.ndarray] = {}
        out_sr = None
        for idx, st in enumerate(starts):
            seg = w[int(st * sr) : int(min(dur, st + chunk + overlap) * sr)]
            tmp = Path(out_wav).with_suffix(f".part{idx:03d}.wav")
            sf.write(str(tmp), seg, sr)
            prot = protect
            if s.auto_spoken and sp_times is not None:
                m = (sp_times >= st) & (sp_times < st + chunk)
                if m.any():
                    voicing = float(np.mean(sp_v[m]))
                    fv = sp_f0[m][~np.isnan(sp_f0[m])]
                    fmed = float(np.median(fv)) if len(fv) else 0.0
                    if 0.02 <= voicing <= 0.50 and fmed < 270:
                        prot = s.spoken_protect
            status, res = self._vc.vc_single(0, str(tmp), up_key, f0_method, "", 0, 0, rms_mix, prot)  # type: ignore[union-attr]
            tmp.unlink(missing_ok=True)
            if not res or res[1] is None:
                raise RuntimeError(f"conversion failed on chunk {idx}: {status}")
            osr, audio = res
            out_sr = out_sr or osr
            audio = np.asarray(audio, dtype=np.float32)
            if np.abs(audio).max() > 1.5:  # RVC returns int16-scaled floats
                audio /= 32768.0
            canvas[idx] = audio
            if progress:
                progress(idx + 1, n, "converting")

        assert out_sr is not None
        total = int(round(dur * out_sr)) + out_sr * 2
        mix = np.zeros(total, dtype=np.float64)
        wsum = np.zeros(total, dtype=np.float64)
        ov = int(overlap * out_sr)
        for idx, st in enumerate(starts):
            audio = canvas[idx]
            pos = int(round(st * out_sr))
            seg = audio[: max(0, total - pos)]
            L = len(seg)
            ramp = np.ones(L, dtype=np.float64)
            if idx > 0:
                f = min(ov, L)
                ramp[:f] = np.linspace(0, 1, f, endpoint=False)
            if idx < n - 1:
                f = min(ov, L)
                ramp[L - f :] = np.minimum(ramp[L - f :], np.linspace(1, 0, f, endpoint=False))
            mix[pos : pos + L] += seg * ramp
            wsum[pos : pos + L] += ramp
        wsum[wsum < 1e-8] = 1.0
        mix = (mix / wsum)[: int(round(dur * out_sr))].astype(np.float32)

        if s.gate_ref:
            import librosa

            src, _ = librosa.load(str(src_wav), sr=out_sr, mono=True)
            mix = self._gate_by_source(src, mix, out_sr, s.gate_db)

        fade = max(1, int(0.005 * out_sr))
        mix[:fade] *= np.linspace(0, 1, fade, dtype=np.float32)
        mix[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)

        sf.write(str(out_wav), mix, out_sr, subtype="FLOAT")
        if progress:
            progress(n, n, "converted")
        return Path(out_wav)
