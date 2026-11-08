"""MCP server, so an LLM agent can *call* the voice.

Register it with any MCP client, e.g. Claude Desktop / DSH:

    {
      "mcpServers": {
        "xiaoxi-singer": {
          "command": "xiaoxi-singer",
          "args": ["mcp"],
          "env": {
            "RVC_ROOT": "/path/to/Retrieval-based-Voice-Conversion-WebUI",
            "XIAOXI_MODEL": "/path/to/models/xiaoxi_ft_e45_s74565.pth"
          }
        }
      }
    }

Tools are split into non-blocking (`start_*` -> job id) and blocking (`*_and_wait`)
so a chat agent can poll instead of hanging on a 5-minute render.
"""

from __future__ import annotations

import time
from pathlib import Path

from .config import settings
from .jobs import runner
from .pipeline import render_cover, render_vocal


def _voice_list() -> list[str]:
    d = Path(settings.model_path).parent
    return sorted(p.name for p in d.glob("*.pth")) if d.is_dir() else []


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("install the mcp extra: pip install 'xiaoxi-singer[mcp]'") from exc

    mcp = FastMCP("xiaoxi-singer")

    @mcp.tool()
    def singer_info() -> dict:
        """Describe the configured voice, model file and RVC installation."""
        return {
            "voice": Path(settings.model_path).name,
            "model_exists": Path(settings.model_path).is_file(),
            "voices": _voice_list(),
            "rvc_root": str(settings.rvc_root),
            "rvc_root_exists": Path(settings.rvc_root).is_dir(),
            "sample_rate": settings.sample_rate,
            "defaults": {
                "up_key": settings.up_key,
                "protect": settings.protect,
                "post_hf": settings.post_hf,
                "post_shelf": settings.post_shelf,
                "post_reverb": settings.post_reverb,
                "post_gate": settings.post_gate,
            },
        }

    @mcp.tool()
    def start_sing(
        vocal_path: str,
        out_path: str = "",
        instrumental_path: str = "",
        up_key: int = 0,
        protect: float = -1.0,
    ) -> dict:
        """Start converting a dry vocal stem into the target voice.

        Args:
            vocal_path: wav/flac of the *isolated* vocal (mono or stereo).
            out_path: where to write the result (.wav for a vocal only, .mp3 when mixing).
            instrumental_path: optional backing track; when given the output is a mixed mp3.
            up_key: semitones to transpose inside the model (use +7 for a male song sung by a female voice).
            protect: 0..1, how much of the source articulation to keep; -1 uses the default (0.5).
        """
        vocal = Path(vocal_path)
        if not vocal.is_file():
            return {"ok": False, "error": f"vocal not found: {vocal_path}"}
        out = out_path or str(settings.work_dir / f"sing_{time.strftime('%Y%m%d-%H%M%S')}.wav")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        prot = None if protect < 0 else protect

        def run(job) -> None:
            def hook(stage: str, pct: float) -> None:
                job.stage, job.progress = stage, float(pct)

            if instrumental_path:
                target = out if out.endswith(".mp3") else out.rsplit(".", 1)[0] + ".mp3"
                render_cover(vocal_path, instrumental_path, target, up_key=up_key, protect=prot, progress=hook)
                job.result = {"audio": target}
            else:
                render_vocal(vocal_path, out, up_key=up_key, protect=prot, progress=hook)
                job.result = {"audio": out}

        job = runner.submit("cover" if instrumental_path else "vocal", {"vocal": vocal_path}, run)
        return {"ok": True, "job_id": job.id, "status": job.status}

    @mcp.tool()
    def job_status(job_id: str) -> dict:
        """Poll a conversion job."""
        j = runner.get(job_id)
        return j.as_dict() if j else {"ok": False, "error": "job not found"}

    @mcp.tool()
    def sing_and_wait(
        vocal_path: str,
        out_path: str = "",
        instrumental_path: str = "",
        up_key: int = 0,
        protect: float = -1.0,
        timeout_s: int = 900,
    ) -> dict:
        """Convert and block until finished (or timeout). Returns the audio path."""
        started = start_sing(vocal_path, out_path, instrumental_path, up_key, protect)
        if not started.get("ok"):
            return started
        job_id = started["job_id"]
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            j = runner.get(job_id)
            if j is None:
                return {"ok": False, "error": "job vanished"}
            if j.status in {"done", "error"}:
                return {"ok": j.status == "done", "job": j.as_dict()}
            time.sleep(2)
        return {"ok": False, "error": "timeout", "job_id": job_id}

    @mcp.tool()
    def list_jobs(limit: int = 10) -> dict:
        """Recent jobs on this machine."""
        return {"jobs": [j.as_dict() for j in runner.list(limit)]}

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
