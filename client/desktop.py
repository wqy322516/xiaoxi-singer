"""Xiaoxi Singer desktop client.

Thin tkinter app: it talks HTTP to the local engine (``xiaoxi_singer.localapp``),
which it starts on demand with the configured Python interpreter.  No third-party
dependency, so the same file runs from source and from the PyInstaller bundle.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, StringVar, Tk, filedialog
from tkinter import ttk
import tkinter as tk

APP = "Xiaoxi Singer"
VER = "0.1.0"
CFG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "xiaoxi-singer"
CFG_FILE = CFG_DIR / "client.json"

BG = "#14161a"
BG2 = "#1c1f26"
FG = "#e8eaf0"
DIM = "#8b93a7"
ACCENT = "#7cc4ff"
USER = "#9be7c4"
TOOL = "#ffd479"
ERR = "#ff8a8a"

DEFAULT_CFG = {
    "server_url": "http://127.0.0.1:8765",
    "backend": {
        # Interpreted on the user's machine; "python" means "whatever is on PATH".
        "python": "python",
        "cwd": "",
        "module": "xiaoxi_singer.localapp",
        "port": 8765,
    },
    "llm": {"base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "api_key": ""},
    "model": "",
    "rvc_root": "",
    "output_dir": str(Path.home() / "Music" / "XiaoxiSinger"),
}


# --------------------------------------------------------------------- config
def load_cfg() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if CFG_FILE.is_file():
        try:
            data = json.loads(CFG_FILE.read_text(encoding="utf-8"))
            for k, v in data.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass
    if os.environ.get("LLM_API_KEY") and not cfg["llm"].get("api_key"):
        cfg["llm"]["api_key"] = os.environ["LLM_API_KEY"]
    return cfg


def save_cfg(cfg: dict) -> None:
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------- http
def http_json(url: str, payload: dict | None = None, timeout: float = 6.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


class App:
    def __init__(self, root: Tk, cfg: dict, demo: str | None = None) -> None:
        self.root = root
        self.cfg = cfg
        self.demo = demo
        self.backend = None
        self.vocal = ""
        self.inst = ""
        self.chat_id = ""
        self.polling = False
        self._seen_steps = 0
        self._build_ui()
        self.root.after(120, self.ensure_backend)

    # ------------------------------------------------------------------- ui
    def _build_ui(self) -> None:
        self.root.title(f"{APP} v{VER}")
        self.root.geometry("1120x840")
        self.root.minsize(820, 600)
        self.root.configure(bg=BG)

        head = tk.Frame(self.root, bg=BG2, height=64)
        head.pack(fill=X)
        head.pack_propagate(False)
        tk.Label(head, text="小汐 · 唱歌 Agent", bg=BG2, fg=FG,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side=LEFT, padx=18)
        self.dot = tk.Label(head, text="●", bg=BG2, fg="#555b6b", font=("Segoe UI", 12))
        self.dot.pack(side=RIGHT, padx=(0, 6))
        self.engine_lbl = tk.Label(head, text="引擎未连接", bg=BG2, fg=DIM, font=("Microsoft YaHei UI", 9))
        self.engine_lbl.pack(side=RIGHT, padx=(0, 10))
        tk.Button(head, text="设置", command=self.open_settings, bg=BG2, fg=ACCENT, bd=0,
                  activebackground=BG2, activeforeground=FG,
                  font=("Microsoft YaHei UI", 9)).pack(side=RIGHT, padx=6)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill=BOTH, expand=True, padx=14, pady=(10, 0))
        self.text = tk.Text(body, bg=BG2, fg=FG, bd=0, wrap="word", padx=14, pady=12,
                            font=("Microsoft YaHei UI", 10), insertbackground=FG,
                            spacing1=2, spacing3=4)
        self.text.pack(side=LEFT, fill=BOTH, expand=True)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.text.configure(yscrollcommand=sb.set, state="disabled")
        self.text.tag_configure("user", foreground=USER, font=("Microsoft YaHei UI", 10, "bold"))
        self.text.tag_configure("tool", foreground=TOOL, font=("Consolas", 9))
        self.text.tag_configure("ok", foreground=FG)
        self.text.tag_configure("dim", foreground=DIM, font=("Microsoft YaHei UI", 9))
        self.text.tag_configure("err", foreground=ERR)

        attach = tk.Frame(self.root, bg=BG)
        attach.pack(fill=X, padx=14, pady=(8, 0))
        tk.Button(attach, text="＋ 人声干声", command=lambda: self.pick("vocal"), bg=BG2, fg=FG, bd=0,
                  activebackground="#2a2e38", activeforeground=FG, padx=10, pady=3,
                  font=("Microsoft YaHei UI", 9)).pack(side=LEFT)
        tk.Button(attach, text="＋ 伴奏", command=lambda: self.pick("inst"), bg=BG2, fg=FG, bd=0,
                  activebackground="#2a2e38", activeforeground=FG, padx=10, pady=3,
                  font=("Microsoft YaHei UI", 9)).pack(side=LEFT, padx=6)
        self.attach_lbl = tk.Label(attach, text="未选择文件（也可以直接描述任务，让它自己决定）",
                                   bg=BG, fg=DIM, font=("Microsoft YaHei UI", 9))
        self.attach_lbl.pack(side=LEFT, padx=10)

        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(fill=X, padx=14, pady=10)
        self.entry = tk.Text(bottom, height=3, bg=BG2, fg=FG, bd=0, padx=12, pady=8, wrap="word",
                             font=("Microsoft YaHei UI", 10), insertbackground=FG)
        self.entry.pack(side=LEFT, fill=BOTH, expand=True)
        self.entry.bind("<Control-Return>", lambda e: (self.send(), "break")[1])
        right = tk.Frame(bottom, bg=BG)
        right.pack(side=RIGHT, padx=(10, 0), fill=Y)
        self.send_btn = tk.Button(right, text="发送\nCtrl+Enter", command=self.send, bg=ACCENT,
                                  fg="#08222f", bd=0, font=("Microsoft YaHei UI", 9, "bold"),
                                  width=11, height=3, activebackground="#a5d8ff", cursor="hand2")
        self.send_btn.pack(fill=BOTH, expand=True)

        self.status = tk.Label(self.root, text="就绪", bg=BG, fg=DIM, anchor="w",
                               font=("Microsoft YaHei UI", 9))
        self.status.pack(fill=X, padx=16, pady=(0, 8))
        self.append("dim", f"{APP} v{VER} — 用一句话交给它：它会自己选工具、看结果、决定下一步。\n")

    # --------------------------------------------------------------- helpers
    def append(self, tag: str, msg: str) -> None:
        self.text.configure(state="normal")
        prefix = {"user": "你 › ", "dim": "", "ok": "小汐 › ", "err": "⚠ ", "tool": ""}.get(tag, "")
        self.text.insert(END, prefix + msg.rstrip() + "\n", tag)
        self.text.configure(state="disabled")
        self.text.see(END)

    def set_status(self, msg: str) -> None:
        self.status.configure(text=msg)

    def pick(self, which: str) -> None:
        p = filedialog.askopenfilename(
            title="选择音频",
            filetypes=[("音频", "*.wav *.mp3 *.flac *.m4a *.ogg"), ("全部", "*.*")])
        if not p:
            return
        if which == "vocal":
            self.vocal = p
        else:
            self.inst = p
        bits = []
        if self.vocal:
            bits.append(f"人声 {Path(self.vocal).name}")
        if self.inst:
            bits.append(f"伴奏 {Path(self.inst).name}")
        self.attach_lbl.configure(text="  ·  ".join(bits) or "未选择文件")

    # --------------------------------------------------------------- backend
    def health(self):
        try:
            return http_json(self.cfg["server_url"].rstrip("/") + "/healthz", timeout=1.5)
        except Exception:
            return None

    def ensure_backend(self) -> None:
        if self.health():
            self.mark_online()
            return
        b = self.cfg.get("backend") or {}
        py = b.get("python") or sys.executable
        cwd = b.get("cwd") or ""
        module = b.get("module") or "xiaoxi_singer.localapp"
        port = str(b.get("port") or 8765)
        if py != "python" and not Path(py).is_file():
            self.append("err", f"找不到 Python 解释器：{py}（在「设置」里改）\n")
            self.set_status("引擎未启动：解释器路径不对")
            return
        self.set_status(f"正在启动本地引擎…（{Path(py).name}）")
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        if self.cfg.get("model"):
            env["XIAOXI_MODEL"] = str(self.cfg["model"])
        if self.cfg.get("rvc_root"):
            env["RVC_ROOT"] = str(self.cfg["rvc_root"])
        roots = [Path(cwd)] if cwd else []
        roots += [Path(cwd) / "src"] if cwd else []
        parts = [str(p) for p in roots if p.is_dir()]
        if parts:
            env["PYTHONPATH"] = os.pathsep.join(parts + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            self.backend = subprocess.Popen(
                [py, "-m", module, "--port", port],
                cwd=cwd or None,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.append("err", f"启动引擎失败：{exc}\n")
            self.set_status("引擎启动失败")
            return
        threading.Thread(target=self._wait_backend, daemon=True).start()

    def _wait_backend(self, tries: int = 45) -> None:
        for _ in range(tries):
            time.sleep(0.8)
            if self.health():
                self.root.after(0, self.mark_online)
                return
            if self.backend is not None and self.backend.poll() is not None:
                code = self.backend.returncode
                self.root.after(0, lambda c=code: (
                    self.set_status(f"引擎启动失败（退出码 {c}）"),
                    self.append("err", "引擎进程退出了。「设置」里确认 Python 解释器装了本包（"
                                       "pip install -e .），或先在终端手动运行 "
                                       "python -m xiaoxi_singer.localapp 看报错。\n")))
                return
        self.root.after(0, lambda: (self.set_status("引擎启动超时，请检查「设置」里的 Python 路径"),
                                    self.append("err", "引擎启动超时。\n")))

    def mark_online(self) -> None:
        h = self.health() or {}
        self.dot.configure(fg="#5ee08a")
        model = Path(h.get("model", "")).name or "?"
        self.engine_lbl.configure(text=f"引擎在线 · {model}")
        self.set_status("就绪")
        if self.demo:
            task, self.demo = self.demo, None
            self.entry.insert("1.0", task)
            self.root.after(400, self.send)

    def mark_offline(self) -> None:
        self.dot.configure(fg="#555b6b")
        self.engine_lbl.configure(text="引擎未连接")

    # ---------------------------------------------------------------- sending
    def send(self) -> None:
        task = self.entry.get("1.0", END).strip()
        if not task:
            return
        if self.polling:
            self.set_status("上一条还在跑，稍等…")
            return
        extra = []
        if self.vocal:
            extra.append(f"人声干声文件：{self.vocal}")
        if self.inst:
            extra.append(f"伴奏文件：{self.inst}")
        if self.cfg.get("output_dir"):
            extra.append(f"输出目录：{self.cfg['output_dir']}")
        full = task + ("\n\n" + "\n".join(extra) if extra else "")

        self.entry.delete("1.0", END)
        self.append("user", task)
        self.set_status("思考中…")
        self._seen_steps = 0
        payload = {"task": full, "llm": self.cfg.get("llm") or {}}
        threading.Thread(target=self._post_chat, args=(payload,), daemon=True).start()

    def _post_chat(self, payload: dict) -> None:
        try:
            r = http_json(self.cfg["server_url"].rstrip("/") + "/chat", payload, timeout=10)
            self.chat_id = r["id"]
            self.polling = True
            threading.Thread(target=self._poll, daemon=True).start()
        except Exception as exc:
            self.root.after(0, lambda e=exc: (self.append("err", f"发送失败：{e}\n"),
                                              self.set_status("发送失败")))

    def _poll(self) -> None:
        url = self.cfg["server_url"].rstrip("/") + "/chat/" + self.chat_id
        while True:
            time.sleep(0.8)
            try:
                chat = http_json(url, timeout=8)
            except Exception:
                continue
            steps = chat.get("steps") or []
            while self._seen_steps < len(steps):
                s = steps[self._seen_steps]
                self._seen_steps += 1
                self.root.after(0, lambda s=s: self._render_step(s))
            if chat.get("status") in ("done", "error"):
                self.root.after(0, lambda c=chat: self._finish(c))
                return

    def _render_step(self, s: dict) -> None:
        res = s.get("result") or {}
        brief = json.dumps(res, ensure_ascii=False)
        if len(brief) > 120:
            brief = brief[:117] + "…"
        self.append("tool", f"  🔧 {s['tool']}  [{s.get('seconds', '?')}s]  {brief}")
        self.set_status(f"执行中：{s['tool']}")

    def _finish(self, chat: dict) -> None:
        self.polling = False
        if chat.get("status") == "error":
            self.append("err", (chat.get("error") or "未知错误") + "\n")
            self.set_status("出错")
            return
        self.append("ok", (chat.get("answer") or "") + "\n")
        for f in chat.get("files") or []:
            self.append("dim", f"  成品：{f}")
        if chat.get("files"):
            btn = tk.Button(self.text, text="打开成品文件夹", bg="#2a2e38", fg=ACCENT, bd=0,
                            command=lambda p=chat["files"][0]: os.startfile(str(Path(p).parent)))
            self.text.configure(state="normal")
            self.text.window_create(END, window=btn)
            self.text.insert(END, "\n")
            self.text.configure(state="disabled")
        self.set_status(f"完成 · 用时 {time.time() - chat.get('created_at', time.time()):.0f}s")

    # --------------------------------------------------------------- settings
    def open_settings(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.configure(bg=BG)
        win.geometry("640x430")
        rows = [
            ("引擎地址", "server_url"),
            ("Python 解释器", "python"),
            ("项目目录", "cwd"),
            ("LLM 接口", "llm.base_url"),
            ("模型名", "llm.model"),
            ("API Key", "llm.api_key"),
            ("音色模型 .pth", "model"),
            ("RVC 目录", "rvc_root"),
            ("输出目录", "output_dir"),
        ]
        vars_ = {}

        def getv(path: str) -> str:
            cur = self.cfg
            for part in path.split("."):
                cur = cur.get(part, "") if isinstance(cur, dict) else ""
            return str(cur or "")

        for i, (label, path) in enumerate(rows):
            tk.Label(win, text=label, bg=BG, fg=DIM, font=("Microsoft YaHei UI", 9)).grid(
                row=i, column=0, sticky="w", padx=14, pady=8)
            v = StringVar(value=getv(path))
            vars_[path] = v
            tk.Entry(win, textvariable=v, bg=BG2, fg=FG, bd=0, insertbackground=FG,
                     font=("Consolas", 9)).grid(row=i, column=1, sticky="we", padx=(0, 14), pady=8)
        win.grid_columnconfigure(1, weight=1)

        def apply() -> None:
            for path, v in vars_.items():
                cur = self.cfg
                parts = path.split(".")
                for part in parts[:-1]:
                    cur = cur.setdefault(part, {})
                cur[parts[-1]] = v.get().strip()
            save_cfg(self.cfg)
            win.destroy()
            self.set_status("设置已保存")
            if not self.health():
                self.mark_offline()
                self.ensure_backend()

        tk.Button(win, text="保存", command=apply, bg=ACCENT, fg="#08222f", bd=0,
                  font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=6).grid(
            row=len(rows), column=1, sticky="e", padx=14, pady=12)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser("xiaoxi-singer desktop client")
    ap.add_argument("--demo", default=None, help="auto-send this task once the engine is ready")
    a = ap.parse_args(argv)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = Tk()
    cfg = load_cfg()
    if not CFG_FILE.is_file():
        save_cfg(cfg)
    App(root, cfg, demo=a.demo)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
