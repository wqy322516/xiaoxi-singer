"""HTTP API (FastAPI). Run with: ``xiaoxi-singer serve`` or ``uvicorn xiaoxi_singer.server:app``."""

from __future__ import annotations

from pathlib import Path

from .config import settings
from .jobs import runner
from .pipeline import render_cover, render_vocal

try:  # keep the package importable without the optional extra installed
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except Exception:  # pragma: no cover
    FastAPI = None  # type: ignore
    BaseModel = object  # type: ignore


class SingRequest(BaseModel):  # type: ignore[misc]
    vocal: str
    instrumental: str | None = None
    out: str | None = None
    up_key: int | None = None
    protect: float | None = None
    target_rms: float = 0.0


def build_app():
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError("install the server extra: pip install 'xiaoxi-singer[server]'")

    def _progress(job):
        def hook(stage: str, pct: float) -> None:
            job.stage = stage
            job.progress = float(pct)

        return hook

    app = FastAPI(title="xiaoxi-singer", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict:
        return {
            "ok": True,
            "model": str(settings.model_path),
            "model_exists": Path(settings.model_path).is_file(),
            "rvc_root": str(settings.rvc_root),
            "rvc_root_exists": Path(settings.rvc_root).is_dir(),
            "jobs": len(runner.list()),
        }

    @app.get("/v1/voices")
    def voices() -> dict:
        models_dir = Path(settings.model_path).parent
        items = sorted(p.name for p in models_dir.glob("*.pth")) if models_dir.is_dir() else []
        return {"default": Path(settings.model_path).name, "voices": items}

    @app.post("/v1/sing")
    def sing(req: SingRequest) -> dict:
        if not Path(req.vocal).is_file():
            raise HTTPException(status_code=400, detail=f"vocal not found: {req.vocal}")
        out = req.out or str(settings.work_dir / "api_out.wav")
        Path(out).parent.mkdir(parents=True, exist_ok=True)

        if req.instrumental:
            if not Path(req.instrumental).is_file():
                raise HTTPException(status_code=400, detail=f"instrumental not found: {req.instrumental}")
            out = out if out.endswith(".mp3") else out.rsplit(".", 1)[0] + ".mp3"

            def run(job) -> None:
                render_cover(
                    req.vocal,
                    req.instrumental,
                    out,
                    up_key=req.up_key,
                    protect=req.protect,
                    target_rms=req.target_rms,
                    progress=_progress(job),
                )

            job = runner.submit("cover", req.model_dump(), run)
        else:

            def run_vocal(job) -> None:
                render_vocal(
                    req.vocal,
                    out,
                    up_key=req.up_key,
                    protect=req.protect,
                    progress=_progress(job),
                )

            job = runner.submit("vocal", req.model_dump(), run_vocal)

        return {"job": job.as_dict(), "out": out}

    @app.get("/v1/jobs")
    def jobs(limit: int = 20) -> dict:
        return {"jobs": [j.as_dict() for j in runner.list(limit)]}

    @app.get("/v1/jobs/{job_id}")
    def job(job_id: str) -> dict:
        j = runner.get(job_id)
        if not j:
            raise HTTPException(status_code=404, detail="job not found")
        return j.as_dict()

    return app


app = build_app() if FastAPI is not None else None
