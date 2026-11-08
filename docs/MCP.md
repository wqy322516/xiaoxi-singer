# MCP: letting an agent sing

`xiaoxi-singer mcp` speaks MCP over stdio. Any MCP-capable client (Claude Desktop, DSH, your own orchestrator) can spawn it and call tools.

## Wiring it up

```jsonc
{
  "mcpServers": {
    "xiaoxi-singer": {
      "command": "xiaoxi-singer",
      "args": ["mcp"],
      "env": {
        "RVC_ROOT": "/opt/rvc",
        "XIAOXI_MODEL": "/opt/models/xiaoxi_ft_e45_s74565.pth",
        "RVC_UP_KEY": "7"
      }
    }
  }
}
```

## Tools

| tool | blocking | purpose |
|---|---|---|
| `singer_info` | no | voice file, RVC install, current defaults |
| `start_sing` | no | queue a conversion, return `job_id` |
| `job_status` | no | `queued / running / done / error` + progress |
| `sing_and_wait` | yes (timeout) | queue and poll until finished |
| `list_jobs` | no | recent jobs |

`start_sing` / `sing_and_wait` arguments:

```jsonc
{
  "vocal_path": "song_vocals.wav",       // required, isolated vocal
  "instrumental_path": "song_inst.wav",  // optional; when set, output is a mixed mp3
  "out_path": "out/cover.mp3",           // optional
  "up_key": 7,                           // semitones inside the model
  "protect": -1                          // -1 = use server default (0.5)
}
```

## A worked transcript

```
user: 把这首歌换成女声唱，男声那段升高一点

agent → singer_info()
      ← {"voice": "xiaoxi_ft_e45_s74565.pth", "defaults": {"up_key": 0, ...}}

agent → start_sing(vocal_path="/data/song_vocals.wav",
                   instrumental_path="/data/song_inst.wav",
                   out_path="/data/cover.mp3",
                   up_key=7)
      ← {"ok": true, "job_id": "9f2c1a7b0d31", "status": "running"}

agent → job_status("9f2c1a7b0d31")   # once every few seconds
      ← {"status": "running", "progress": 0.63, "stage": "converting"}

agent → job_status("9f2c1a7b0d31")
      ← {"status": "done", "result": {"audio": "/data/cover.mp3"}}

agent: 好了，放在 /data/cover.mp3 了，男声那段按 +7 个半音处理过。
```

## Why jobs instead of one blocking call

A 4-minute song is ~90 s of GPU work (or ~15 min on CPU). Chat agents usually have 30–60 s tool timeouts, so a blocking tool would be reported as a failure while the render still finishes. The `start_*` / `job_status` pair is timeout-proof; `sing_and_wait` exists for runtimes that allow long tools.

## Using it from Python

```python
from xiaoxi_singer.pipeline import render_cover

render_cover("vocal.wav", "inst.wav", "cover.mp3", up_key=7, target_rms=0.118)
```

Or through the job runner, which is what the MCP server uses internally:

```python
from xiaoxi_singer.jobs import runner
from xiaoxi_singer.pipeline import render_cover

job = runner.submit("cover", {}, lambda j: render_cover("vocal.wav", "inst.wav", "cover.mp3"))
print(job.id)
```
