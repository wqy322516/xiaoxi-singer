"""Runtime configuration, all overridable through environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    """Everything the agent needs to find its pieces.

    ``rvc_root`` points at a checkout of Retrieval-based-Voice-Conversion-WebUI
    (the fork with the sweet-zone patch, see ``patches/``). It is imported lazily so
    that post-processing and mixing work without torch installed.
    """

    rvc_root: Path = field(default_factory=lambda: Path(_env("RVC_ROOT", "vendor/Retrieval-based-Voice-Conversion-WebUI")))
    model_path: Path = field(default_factory=lambda: Path(_env("XIAOXI_MODEL", "models/xiaoxi_ft_e45_s74565.pth")))
    work_dir: Path = field(default_factory=lambda: Path(_env("XIAOXI_WORK_DIR", "runtime")))
    ffmpeg: str = field(default_factory=lambda: _env("FFMPEG", "ffmpeg"))

    # conversion defaults (tuned on a 6.6h mixed-language singing corpus)
    f0_method: str = field(default_factory=lambda: _env("RVC_F0_METHOD", "rmvpe"))
    chunk_s: float = field(default_factory=lambda: float(_env("RVC_CHUNK", "30")))
    overlap_s: float = field(default_factory=lambda: float(_env("RVC_OVERLAP", "1.0")))
    protect: float = field(default_factory=lambda: float(_env("RVC_PROTECT", "0.5")))
    spoken_protect: float = field(default_factory=lambda: float(_env("RVC_SPOKEN_PROTECT", "0.9")))
    rms_mix: float = field(default_factory=lambda: float(_env("RVC_RMS_MIX", "0.5")))
    up_key: int = field(default_factory=lambda: int(_env("RVC_UP_KEY", "0")))
    auto_spoken: bool = field(default_factory=lambda: _env("RVC_AUTO_SPOKEN", "1") == "1")
    gate_ref: bool = field(default_factory=lambda: _env("RVC_GATE_REF", "1") == "1")
    gate_db: float = field(default_factory=lambda: float(_env("RVC_GATE_DB", "-50")))

    # post-processing defaults
    post_hf: float = field(default_factory=lambda: float(_env("POST_HF", "0.18")))
    post_shelf: float = field(default_factory=lambda: float(_env("POST_SHELF", "3.0")))
    post_reverb: float = field(default_factory=lambda: float(_env("POST_REVERB", "0.08")))
    post_gate: float = field(default_factory=lambda: float(_env("POST_GATE", "-40")))

    sample_rate: int = 24000

    def ensure_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
