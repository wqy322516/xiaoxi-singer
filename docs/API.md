# HTTP API

```bash
xiaoxi-singer serve --host 127.0.0.1 --port 8000
# or: uvicorn xiaoxi_singer.server:app --port 8000
```

All paths are **server-side** paths. The API is meant for a trusted local network; there is no auth (put it behind a reverse proxy if you expose it).

## `GET /healthz`

```json
{
  "ok": true,
  "model": "models/xiaoxi_ft_e45_s74565.pth",
  "model_exists": true,
  "rvc_root": "vendor/Retrieval-based-Voice-Conversion-WebUI",
  "rvc_root_exists": true,
  "jobs": 3
}
```

## `GET /v1/voices`

Lists `.pth` files next to `XIAOXI_MODEL`.

```json
{ "default": "xiaoxi_ft_e45_s74565.pth", "voices": ["xiaoxi_ft_e45_s74565.pth"] }
```

## `POST /v1/sing`

```json
{
  "vocal": "/data/song_vocals.wav",
  "instrumental": "/data/song_inst.wav",
  "out": "/data/cover.mp3",
  "up_key": 7,
  "protect": 0.5,
  "target_rms": 0.118
}
```

`instrumental` is optional: without it you get a converted vocal (`.wav`); with it you get a mixed `.mp3`. The call returns immediately:

```json
{
  "job": { "id": "9f2c1a7b0d31", "status": "queued", "progress": 0.0, "stage": "queued" },
  "out": "/data/cover.mp3"
}
```

## `GET /v1/jobs/{id}`

```json
{
  "id": "9f2c1a7b0d31",
  "kind": "cover",
  "status": "running",
  "progress": 0.63,
  "stage": "converting",
  "result": {},
  "error": ""
}
```

`status` is one of `queued`, `running`, `done`, `error`. When `done`, `result.audio` holds the output path.

## `GET /v1/jobs?limit=20`

Recent jobs, newest first.

## Errors

- `400` — input file missing or unreadable.
- `404` — unknown job id.
- `500` — conversion failed; the job carries `error` with the exception text.

## Notes

- One worker thread: jobs queue up rather than competing for the GPU.
- Output files are written by the worker, so `GET /v1/jobs/{id}` reaching `done` means the file is on disk and complete.
