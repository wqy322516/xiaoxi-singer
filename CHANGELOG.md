# Changelog

Releases follow `vX.Y.Z` tags on `main`.

## v0.4.0 — original songs (ACE-Step) + a one-sentence agent

**One sentence in, a finished track out.** Saying `唱一首《小幸运》` in the desktop client
now runs the whole cover pipeline (search → download → separate → convert → post → mix)
in ~160 s without the LLM having to guess which tool to call.

### Added
- `original.py` — composer pipeline on top of ACE-Step: `generate()` → `separate()` →
  `convert()` → `mix_cover()`; `describe_image()` turns a reference picture into a music
  brief through any OpenAI-compatible vision endpoint.
- Agent tool `compose_song` (brief / lyrics / image / duration / seed) — 8 tools total.
- CLI `xiaoxi-singer compose "<brief>" [--lyrics] [--image] [--duration] [--seed]`.
- `docs/ORIGINAL.md` — environment variables, knobs, failure modes.
- `deterministic cover routing` in `agent.py`: `唱/点歌/cover + <song>` skips the planner
  and calls `cover_song` directly, so a bare song name can never be mistaken for a file.

### Fixed
- `ensure_ffmpeg_on_path()` in `config.py`: resolves `ffmpeg` from `FFMPEG`, `PATH`, or
  the usual install locations, so an engine started by the desktop client (whose `PATH`
  lacks ffmpeg) no longer dies at the mixing stage with `FileNotFoundError`.
- Desktop client 0.1.1: grid layout keeps the input row on screen at any window size;
  Enter sends, Shift+Enter breaks the line, the box keeps focus.

## v0.3.0 — self-check + lyric video

### Added
- `qa.py` — every cover is checked before delivery: dropped spans, noise spans, pitch MAE
  (60 s window, ~24 s for a 5-minute song), spectral flatness, HNR, clipping.
- `lyrics.py` / `video.py` — LRC (explicit file → NetEase timeline → faster-whisper
  fallback) burned into a 1920×1080 H.264 video with the cover art behind it.
- Agent tools `find_song`, `cover_song`, `make_video`; CLI `song --video --lyrics`.
- `docs/SONG.md` — stages, QA field meanings, failure modes.

## v0.2.0 — whole-song pipeline

### Added
- `song.py` — Bilibili search (WBI-signed), candidate ranking, best-audio download with
  Range resume, MDX-Net separation, and `cover_song()` end to end.
- Whole-song chunked conversion: 30 s windows, 1 s overlap, source-referenced silence
  gate, per-chunk spoken-word detection, automatic sweet-zone clamping.

## v0.1.0 — first public cut

- `engine.py` (RVC wrapper), `post.py` (post chain), `mix.py` (RMS-aligned mix + limiter),
  `pipeline.py` (chunked conversion), `jobs.py` / `server.py` (FastAPI), `mcp_server.py`,
  `cli.py`, `agent.py` (LLM tool loop), `patches/rvc-sweet-zone.patch`.
- Desktop client (`client/desktop.py`, Tkinter) + PyInstaller build script.
