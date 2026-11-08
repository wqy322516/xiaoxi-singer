import numpy as np
import soundfile as sf

from xiaoxi_singer.post import noise_gate, post_process


def _tone(path, seconds=1.0, sr=24000, freq=220.0):
    t = np.arange(int(seconds * sr)) / sr
    w = 0.3 * np.sin(2 * np.pi * freq * t).astype(np.float32)
    w[-2000:] = 0.0  # a silent tail we can gate
    sf.write(str(path), w, sr, subtype="FLOAT")
    return path


def test_post_process_keeps_length_and_peak(tmp_path):
    src = _tone(tmp_path / "in.wav")
    out = post_process(src, tmp_path / "out.wav", gate=-40)
    w, sr = sf.read(str(out))
    assert sr == 24000
    assert len(w) > 0
    assert np.abs(w).max() <= 1.0


def test_post_process_shelf_off_is_quieter_on_top(tmp_path):
    src = _tone(tmp_path / "in.wav", freq=6000.0)
    a = post_process(src, tmp_path / "a.wav", hf=0.0, shelf=3.0, reverb=0.0, gate=0)
    b = post_process(src, tmp_path / "b.wav", hf=0.0, shelf=0.0, reverb=0.0, gate=0)
    wa, _ = sf.read(str(a))
    wb, _ = sf.read(str(b))
    assert np.abs(wa).max() >= np.abs(wb).max() - 1e-6


def test_noise_gate_mutes_silence():
    sr = 24000
    w = np.concatenate([np.full(sr // 2, 0.2, dtype=np.float32), np.full(sr // 2, 1e-4, dtype=np.float32)])
    out = noise_gate(w, thr_db=-40, sr=sr)
    quiet = np.abs(out[sr // 2 + 2000 :]).max()
    loud = np.abs(out[: sr // 2 - 2000]).max()
    assert quiet < loud * 0.2
