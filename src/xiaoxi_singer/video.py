"""Render a lyric video (mp4) for a finished cover.

One still image (the Bilibili cover, or a generated gradient), the mixed audio, and
burned-in subtitles via libass. No timeline editing, no external service.

    make_video("cover.mp3", "cover.mp4", cover="cover.jpg", lrc="song.lrc")
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import lyrics as lyrics_mod

W, H = 1920, 1080
FONT = "Microsoft YaHei"


def _ffmpeg(ffmpeg: str) -> str:
    return shutil.which(ffmpeg) or ffmpeg


def _duration(audio: str | Path, ffmpeg: str) -> float:
    """Length in seconds. ffprobe is not always shipped next to ffmpeg, so be forgiving."""
    try:
        import soundfile as sf

        info = sf.info(str(audio))
        return float(info.frames) / float(info.samplerate)
    except Exception:
        pass
    exe = _ffmpeg(ffmpeg)
    r = subprocess.run([exe, "-hide_banner", "-i", str(audio)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    import re

    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr or "")
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

def _gradient(path: Path, title: str = "") -> Path:
    """Fallback artwork: a dark gradient with the title, so the video is never black."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return path
    img = Image.new("RGB", (W, H), (18, 20, 28))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(24 + 40 * t), int(22 + 26 * t), int(38 + 60 * t)))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(lines: list[tuple[float, str]], path: Path, title: str, total: float) -> Path:
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Lyric,{FONT},66,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,"
        "0,0,0,0,100,100,0,0,1,3,1,2,120,120,110,1",
        f"Style: Title,{FONT},34,&H00C8C8D2,&H00C8C8D2,&H00101010,&H80000000,"
        "0,0,0,0,100,100,1,0,1,2,0,9,80,80,60,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body = [f"Dialogue: 0,{_ass_time(0)},{_ass_time(max(4.0, total))},Title,,0,0,0,,{title}"]
    for i, (start, text) in enumerate(lines):
        end = lines[i + 1][0] if i + 1 < len(lines) else min(total, start + 8.0)
        end = max(end, start + 1.2)
        safe = text.replace("\\", "＼").replace("{", "(").replace("}", ")")
        body.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Lyric,,0,0,0,,"
            "{\\fad(180,180)}" + safe
        )
    path.write_text("\n".join(head + body) + "\n", encoding="utf-8-sig")
    return path


def make_video(
    audio: str | Path,
    out_mp4: str | Path,
    *,
    cover: str | Path | None = None,
    lrc: str | Path | None = None,
    title: str = "",
    query: str = "",
    lines: list[tuple[float, str]] | None = None,
    ffmpeg: str = "ffmpeg",
    work_dir: str | Path | None = None,
) -> dict:
    """Burn the lyrics over the artwork and mux the audio into an mp4.

    ``lines`` (already timed) wins over ``lrc``; ``lrc`` wins over transcription.
    """
    audio, out_mp4 = Path(audio).resolve(), Path(out_mp4).resolve()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    work = Path(work_dir) if work_dir else out_mp4.parent / "_video"
    work.mkdir(parents=True, exist_ok=True)

    if lines is None and lrc:
        lines = lyrics_mod.read_lrc(lrc)
        lines = [(t, s) for t, s in lines if s.strip()]
    transcribed = False
    if not lines:
        # 1) 网易云的正版歌词带时间轴，比对着唱腔做 ASR 准得多
        for q in (query, title):
            if not q:
                continue
            try:
                lines = lyrics_mod.from_netease(q)
            except Exception:
                lines = []
            if lines:
                break
    if not lines:
        lines = lyrics_mod.transcribe(audio)
        transcribed = True
    if not lines:
        raise RuntimeError("没有歌词也没转写出内容，没法做歌词视频")

    total = _duration(audio, ffmpeg)
    if total <= 0:
        total = max(t for t, _ in lines) + 8.0

    art = Path(cover) if cover else None
    if not art or not art.exists():
        art = _gradient(work / "cover.png", title)
    else:
        art = Path(shutil.copyfile(str(art), str(work / ("cover" + art.suffix))))
    _write_ass(lines, work / "lyrics.ass", title or out_mp4.stem, total)
    lyrics_mod.write_lrc(lines, out_mp4.with_suffix(".lrc"))

    exe = _ffmpeg(ffmpeg)
    cmd = [
        exe, "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", "2", "-i", art.name,
        "-i", str(audio),
        "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        "eq=brightness=-0.06:saturation=0.95,subtitles=lyrics.ass",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        "_out.mp4",
    ]
    r = subprocess.run(cmd, cwd=str(work), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 渲染失败：{(r.stderr or '').strip()[-300:]}")
    # ffmpeg runs inside the work dir, so move the result out
    shutil.move(str(work / "_out.mp4"), str(out_mp4))
    return {
        "video": str(out_mp4),
        "lrc": str(out_mp4.with_suffix(".lrc")),
        "lines": len(lines),
        "transcribed": transcribed,
        "duration_s": round(total, 2),
    }
