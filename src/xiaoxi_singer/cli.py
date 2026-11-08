"""Command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import settings
from .pipeline import render_cover, render_vocal
from .song import cover_song as run_cover_song


def _bar(stage: str, pct: float) -> None:
    width = 24
    filled = int(width * max(0.0, min(1.0, pct)))
    sys.stderr.write(f"\r[{'#' * filled}{'.' * (width - filled)}] {pct * 100:5.1f}%  {stage:<20}")
    sys.stderr.flush()


def cmd_sing(args: argparse.Namespace) -> int:
    out = render_vocal(args.vocal, args.out, up_key=args.up_key, protect=args.protect, progress=_bar)
    print(f"\n{out}")
    return 0


def cmd_cover(args: argparse.Namespace) -> int:
    out = render_cover(
        args.vocal,
        args.instrumental,
        args.out,
        up_key=args.up_key,
        protect=args.protect,
        target_rms=args.target_rms,
        progress=_bar,
    )
    print(f"\n{out}")
    return 0



def cmd_song(args: argparse.Namespace) -> int:
    """Whole song: search -> download -> separate -> convert -> mix."""
    res = run_cover_song(
        args.query or args.audio or args.bv or "",
        args.out,
        bv=args.bv or None,
        audio=args.audio or None,
        up_key=args.up_key,
        progress=lambda stage, pct: _bar(stage, pct / 100.0),
        video=bool(getattr(args, "video", False)),
        lyrics=getattr(args, "lyrics", "") or None,
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    print(res['mp3'])
    return 0

def cmd_info(_: argparse.Namespace) -> int:
    d = Path(settings.model_path).parent
    print(
        json.dumps(
            {
                "voice": Path(settings.model_path).name,
                "model_exists": Path(settings.model_path).is_file(),
                "voices": sorted(p.name for p in d.glob("*.pth")) if d.is_dir() else [],
                "rvc_root": str(settings.rvc_root),
                "rvc_root_exists": Path(settings.rvc_root).is_dir(),
                "defaults": {
                    "up_key": settings.up_key,
                    "protect": settings.protect,
                    "rms_mix": settings.rms_mix,
                    "post": [settings.post_hf, settings.post_shelf, settings.post_reverb, settings.post_gate],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("xiaoxi_singer.server:app", host=args.host, port=args.port)
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    from .agent import cli_main as agent_main

    return agent_main([args.task])


def cmd_mcp(_: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="xiaoxi-singer", description="Callable singing-voice agent")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sing", help="convert an isolated vocal stem")
    s.add_argument("vocal")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--up-key", type=int, default=None, dest="up_key")
    s.add_argument("--protect", type=float, default=None)
    s.set_defaults(func=cmd_sing)

    so = sub.add_parser("song", help="whole song: search, download, separate, convert, mix")
    so.add_argument("query", nargs="?", default="", help="song name, e.g. 周杰伦 晴天")
    so.add_argument("-o", "--out", required=True, help="output mp3")
    so.add_argument("--bv", default="", help="Bilibili BV id (skips search)")
    so.add_argument("--audio", default="", help="local mixed audio (skips search + download)")
    so.add_argument("--up-key", type=int, default=None, help="semitones; auto +7 for male songs")
    so.add_argument("--video", action="store_true", help="also render a lyric mp4")
    so.add_argument("--lyrics", default="", help="existing .lrc; otherwise auto-transcribe")
    so.set_defaults(func=cmd_song)
    c = sub.add_parser("cover", help="convert a vocal and mix it with the instrumental")
    c.add_argument("vocal")
    c.add_argument("instrumental")
    c.add_argument("-o", "--out", required=True)
    c.add_argument("--up-key", type=int, default=None, dest="up_key")
    c.add_argument("--protect", type=float, default=None)
    c.add_argument("--target-rms", type=float, default=0.0, dest="target_rms")
    c.set_defaults(func=cmd_cover)

    i = sub.add_parser("info", help="show configuration and available voices")
    i.set_defaults(func=cmd_info)

    v = sub.add_parser("serve", help="run the HTTP API")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(func=cmd_serve)

    m = sub.add_parser("mcp", help="run the MCP server on stdio")
    m.set_defaults(func=cmd_mcp)

    ag = sub.add_parser("agent", help="LLM-driven agent: describe the task in natural language")
    ag.add_argument("task")
    ag.set_defaults(func=cmd_agent)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
