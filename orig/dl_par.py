import os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

BASE = "https://hf-mirror.com/ACE-Step/ACE-Step-v1-3.5B/resolve/main"
DEST = r"D:\UserProfile\wqy32\dsh\home\work\xiaoxi-singer\models\ace-step"
FILES = [
    ("ace_step_transformer/diffusion_pytorch_model.safetensors", 6611422728),
    ("music_dcae_f8c8/diffusion_pytorch_model.safetensors", 313646516),
    ("music_vocoder/diffusion_pytorch_model.safetensors", 206350988),
]
N = 8

def fetch(rel, size):
    out = os.path.join(DEST, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out) and os.path.getsize(out) == size:
        print("skip", rel, flush=True); return
    chunk = size // N + 1
    parts = []
    def one(i):
        a = i * chunk
        b = min(size - 1, (i + 1) * chunk - 1)
        p = f"{out}.part{i}"
        parts.append((p, b - a + 1))
        for _ in range(40):
            have = os.path.getsize(p) if os.path.exists(p) else 0
            if have >= b - a + 1:
                return
            subprocess.run(["curl", "-sL", "--fail", "-r", f"{a+have}-{b}",
                            "--connect-timeout", "20", "--max-time", "1800",
                            "-o", p, f"{BASE}/{rel}"], check=False)
            time.sleep(1)
        raise RuntimeError(f"part {i} failed")
    with ThreadPoolExecutor(max_workers=N) as ex:
        list(ex.map(one, range(N)))
    tmp = out + ".tmp"
    with open(tmp, "wb") as w:
        for p, _ in sorted(parts, key=lambda x: int(x[0].rsplit("part", 1)[1])):
            with open(p, "rb") as r:
                while True:
                    buf = r.read(1 << 22)
                    if not buf: break
                    w.write(buf)
    os.replace(tmp, out)
    for p, _ in parts: os.remove(p)
    print("ok", rel, os.path.getsize(out), flush=True)

for rel, size in FILES:
    fetch(rel, size)
print("ALLDONE", flush=True)
