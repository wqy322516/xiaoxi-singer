# Whole-song pipeline

`cover_song` is the "just sing it" entry point. One call, no stems required:

```bash
xiaoxi-singer song "周杰伦 晴天" -o qingtian.mp3
xiaoxi-singer song "周杰伦 晴天" -o qingtian.mp3 --video        # also an mp4 with lyrics
xiaoxi-singer song --bv BV1xxxxxxx -o out.mp3                   # you already know the video
xiaoxi-singer song --audio mix.wav -o out.mp3                   # local file, skip search
```

Or through the agent (same code path):

```
you: 唱一下《晴天》，要带歌词的视频
agent: cover_song(query="周杰伦 晴天", out="qingtian.mp3", video=true)
```

## Stages

| # | Stage | Implementation | Notes |
|---|---|---|---|
| 1 | search | `song.search()` | Bilibili WBI-signed search (`w_rid`), fresh `buvid3` per attempt, falls back to the plain endpoint and then to a proxy |
| 2 | pick | `song.pick()` | drops covers / karaoke / vlogs / reaction clips, boosts label accounts and official uploads, 90–480 s only |
| 3 | download | `song.download()` | highest-bitrate dash audio, resumable (`Range`), ffmpeg integrity check, 48 kHz mono |
| 4 | separate | `song.separate()` | MDX-Net `Kim_Vocal_2` via `audio-separator`; stems are reused on re-runs |
| 5 | convert | `engine.RvcEngine.convert()` | chunked, silence-gated, spoken-slice aware; `up_key` auto (+7 for a male original) |
| 6 | post | `post.post_process()` | 55 Hz HP → exciter → 4 kHz shelf → de-harsh → reverb → noise gate |
| 7 | mix | `mix.mix_cover()` | vocal matched to the original vocal stem's RMS, lookahead limiter, 256 kbps mp3 |
| 8 | QA | `qa.check_cover()` | compares converted vs source vocal (see below) |
| 9 | video | `video.make_video()` | optional: cover art + burned lyrics (libass) → H.264 mp4 |

## QA — what it actually checks

`qa.check_cover(source_vocal, converted_vocal, mix)` returns:

| key | meaning | warn when |
|---|---|---|
| `dropped_spans` | windows where the source has voice but the output is ≥35 dB quieter | any span ≥0.5 s → a phrase may have been dropped |
| `noise_spans` | windows where the source is silent but the output is not | any span → the model invented sound |
| `pitch_mae_semitones` | mean |semitones| between the two f0 tracks (librosa pyin) | > 0.6 |
| `flatness` | spectral flatness on voiced frames | converted > 1.6× source → breathy / noisy |
| `hnr.converted_p10` | autocorrelation peak, 10th percentile | < 0.15 → brittle, likely to crack |
| `clipping_samples` | samples at full scale | > 0 |
| `verdict` | `pass` / `warn` / `fail` | — |

It is a smoke detector: `warn` means "listen to these timestamps", not "the render is broken".
No lyrics are needed for it — which is why it works for any song, in any language.

## Video

`video.make_video(audio, out.mp4, cover=?, lrc=?, title=?)`

- artwork: the Bilibili cover grabbed during download, else a generated gradient
- lyrics: an `.lrc` file if you have one, otherwise `faster-whisper` transcribes the
  **converted** vocal (that is what the listener hears) and writes the `.lrc` next to the mp4
- subtitles are rendered by libass, so any ffmpeg build with `--enable-libass` works

## Requirements

```bash
pip install -e ".[song]"     # requests + audio-separator (+ faster-whisper for lyrics)
export SEPARATOR_EXE=/path/to/audio-separator          # optional, if not on PATH
export SEPARATOR_MODEL=Kim_Vocal_2.onnx                # optional
```

## Failure modes seen in practice

- **Bilibili returns `v_voucher` instead of results** — the `buvid` cookie is flagged; a fresh
  uuid per attempt fixes it (already handled), and a residential proxy is the last resort.
- **audio-separator fails instantly with empty stderr** — its child ffmpeg is not on `PATH`;
  the package prepends the folder of `settings.ffmpeg` automatically.
- **Separator output is not GBK-decodable** — always decode its output as UTF-8 with
  `errors="replace"`; otherwise the reader thread dies and the pipeline hangs.
- **A 5-minute song takes minutes to separate** — stems are cached and reused on re-runs.
