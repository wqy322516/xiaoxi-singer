"""Local bridge the desktop client talks to: stdlib only, no extra installs.

The desktop app is deliberately thin (tkinter + urllib).  This module is the
"engine side" of that pair: it owns the GPU, runs the agent loop, and exposes a
three-route HTTP API on loopback.  FastAPI is optional everywhere else; here we
use http.server so ``python -m xiaoxi_singer.localapp`` always works.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .agent import AgentConfig, run_agent
from .config import settings

VERSION = "0.1.0"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg"}

_chats: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_gpu_lock = threading.Lock()  # one render at a time: the machine has one GPU


def _now() -> float:
    return time.time()


def _run_chat(chat_id: str, task: str, llm: dict[str, Any], max_steps: int) -> None:
    chat = _chats[chat_id]
    cfg = AgentConfig()
    if llm.get("base_url"):
        cfg.base_url = str(llm["base_url"])
    if llm.get("api_key"):
        cfg.api_key = str(llm["api_key"])
    if llm.get("model"):
        cfg.model = str(llm["model"])
    if max_steps:
        cfg.max_steps = int(max_steps)

    def on_step(step: dict[str, Any]) -> None:
        with _lock:
            chat["steps"].append(step)
            chat["updated_at"] = _now()

    with _gpu_lock:
        with _lock:
            chat.update(status="running", updated_at=_now())
        try:
            out = run_agent(task, cfg, trace=False, on_step=on_step)
            files = []
            for step in out.get("steps", []):
                res = step.get("result") or {}
                for key in ("audio", "out", "mp3"):
                    val = res.get(key)
                    if isinstance(val, str) and Path(val).suffix.lower() in AUDIO_EXT:
                        files.append(val)
            with _lock:
                chat.update(
                    status="done" if out.get("ok") else "error",
                    answer=out.get("answer", ""),
                    files=sorted(set(files)),
                    updated_at=_now(),
                )
        except Exception as exc:  # noqa: BLE001 - shown in the UI
            with _lock:
                chat.update(status="error", error=f"{type(exc).__name__}: {exc}", updated_at=_now())
            traceback.print_exc()


class Handler(BaseHTTPRequestHandler):
    server_version = f"xiaoxi-singer/{VERSION}"

    # ------------------------------------------------------------------ utils
    def _send(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        if os.environ.get("XIAOXI_HTTP_LOG"):
            super().log_message(fmt, *args)

    # ----------------------------------------------------------------- routes
    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/healthz":
            self._send(200, {
                "ok": True,
                "version": VERSION,
                "model": str(settings.model_path),
                "model_exists": Path(settings.model_path).is_file(),
                "rvc_root": str(settings.rvc_root),
                "rvc_root_exists": Path(settings.rvc_root).is_dir(),
                "python": os.sys.executable,
                "chats": len(_chats),
            })
            return
        if path.startswith("/chat/"):
            chat_id = path.split("/", 2)[2]
            with _lock:
                chat = _chats.get(chat_id)
                if chat is None:
                    self._send(404, {"error": "no such chat"})
                    return
                self._send(200, dict(chat))
            return
        if path == "/outputs":
            out = Path(settings.work_dir)
            items = []
            if out.is_dir():
                for p in sorted(out.glob("*"), key=lambda q: q.stat().st_mtime, reverse=True)[:40]:
                    if p.suffix.lower() in AUDIO_EXT:
                        items.append({"name": p.name, "path": str(p), "size": p.stat().st_size, "mtime": p.stat().st_mtime})
            self._send(200, {"dir": str(out), "items": items})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        body = self._body()
        if path == "/chat":
            task = str(body.get("task") or "").strip()
            if not task:
                self._send(400, {"error": "task is empty"})
                return
            chat_id = uuid.uuid4().hex[:12]
            with _lock:
                _chats[chat_id] = {
                    "id": chat_id,
                    "task": task,
                    "status": "queued",
                    "steps": [],
                    "answer": "",
                    "error": "",
                    "files": [],
                    "created_at": _now(),
                    "updated_at": _now(),
                }
            threading.Thread(
                target=_run_chat,
                args=(chat_id, task, body.get("llm") or {}, int(body.get("max_steps") or 0)),
                name=f"chat-{chat_id}",
                daemon=True,
            ).start()
            self._send(200, {"id": chat_id})
            return
        self._send(404, {"error": "not found"})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser("xiaoxi-singer localapp")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("XIAOXI_PORT", "8765")))
    a = ap.parse_args(argv)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"xiaoxi-singer local engine v{VERSION} on http://{a.host}:{a.port}", flush=True)
    print(f"  model: {settings.model_path}", flush=True)
    print(f"  rvc  : {settings.rvc_root}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
