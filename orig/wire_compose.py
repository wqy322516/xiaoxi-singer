from pathlib import Path
import ast

root = Path(r"D:\UserProfile\wqy32\dsh\home\work\xiaoxi-singer")

ap = root / "src" / "xiaoxi_singer" / "agent.py"
s = ap.read_text(encoding="utf-8")

helper = '''def _compose_song(brief: str, lyrics: str = "", image: str = "", duration: float = 90.0,
                  seed: int | None = None, out_dir: str = "") -> dict[str, Any]:
    """原创歌曲：ACE-Step 生成 -> 分离 -> 换成小汐音色 -> 混音。"""
    from .original import ComposeError, compose

    try:
        r = compose(
            brief,
            lyrics=lyrics or "",
            image=image or None,
            duration=float(duration or 90.0),
            seed=seed,
            out_dir=out_dir or None,
        )
    except ComposeError as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "final": str(r.final),
        "song": str(r.song),
        "seconds": round(r.seconds, 1),
        "prompt": r.prompt,
        "image_brief": r.image_brief,
    }


'''

if "_compose_song" not in s:
    anchor = "TOOLS: list[Tool] = ["
    assert anchor in s
    s = s.replace(anchor, helper + anchor, 1)

tool = '''    Tool(
        "compose_song",
        "做一首原创歌曲：给文字需求（可选图片路径），ACE-Step 生成整首 -> 分离人声 -> 换成小汐音色 -> 混音成 mp3。",
        {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "description": "想要什么样的歌：主题、风格、情绪、参考曲风"},
                "lyrics": {"type": "string", "description": "歌词（可选，不给就由模型自己唱）"},
                "image": {"type": "string", "description": "图片路径（可选，需要多模态模型才能读）"},
                "duration": {"type": "number", "description": "时长秒数，默认 90，最长约 240"},
                "seed": {"type": "integer", "description": "随机种子，想复现同一首歌时给固定值"},
            },
            "required": ["brief"],
        },
        _compose_song,
    ),
'''

if '"compose_song"' not in s:
    close = "\n]\n\nTOOL_MAP = {t.name: t for t in TOOLS}"
    assert close in s, "TOOLS tail not found"
    s = s.replace(close, "\n" + tool + "]\n\nTOOL_MAP = {t.name: t for t in TOOLS}", 1)

prompt_line = "- 做完用一句话汇报"
head = s.split("SYSTEM_PROMPT", 1)[1][:2000]
if "compose_song" not in head:
    s = s.replace(
        prompt_line,
        "- 用户要「原创/写一首/按这张图做歌」时用 compose_song；没配多模态模型（VISION_*）时，"
        "先请用户用文字描述图片内容。\n" + prompt_line,
        1,
    )
ast.parse(s)
ap.write_text(s, encoding="utf-8")
print("agent patched")

cp = root / "src" / "xiaoxi_singer" / "cli.py"
c = cp.read_text(encoding="utf-8")

cmd = '''

def cmd_compose(args: argparse.Namespace) -> int:
    """原创歌曲：文字（可带图）-> ACE-Step -> 分离 -> 换音色 -> 混音。"""
    from .original import ComposeError, compose

    try:
        r = compose(
            args.brief,
            lyrics=args.lyrics or "",
            image=args.image or None,
            duration=float(args.duration),
            out_dir=args.out_dir or None,
            seed=args.seed,
        )
    except ComposeError as exc:
        print(f"error: {exc}")
        return 2
    print(json.dumps({
        "final": str(r.final), "song": str(r.song), "seconds": round(r.seconds, 1),
        "prompt": r.prompt, "image_brief": r.image_brief,
    }, ensure_ascii=False, indent=2))
    return 0

'''

if "def cmd_compose" not in c:
    anchor2 = "\ndef cmd_info(_: argparse.Namespace) -> int:"
    assert anchor2 in c
    c = c.replace(anchor2, cmd + anchor2, 1)

parser = '''    cp = sub.add_parser("compose", help="original song: brief (+ image) -> generated song -> xiaoxi voice")
    cp.add_argument("brief", help="what the song should be about / sound like")
    cp.add_argument("--lyrics", default="", help="lyrics text (optional)")
    cp.add_argument("--image", default="", help="picture that suggests the brief (needs VISION_*)")
    cp.add_argument("--duration", type=float, default=90.0)
    cp.add_argument("--seed", type=int, default=None)
    cp.add_argument("--out-dir", default="")
    cp.set_defaults(func=cmd_compose)
'''

if 'sub.add_parser("compose"' not in c:
    anchor3 = '    i = sub.add_parser("info"'
    assert anchor3 in c
    c = c.replace(anchor3, parser + "\n" + anchor3, 1)
ast.parse(c)
cp.write_text(c, encoding="utf-8")
print("cli patched")
