#!/bin/bash
# 顺序、可续传地拉 ACE-Step 权重；先查远端大小，已完整就跳过（避免 416）
BASE="https://hf-mirror.com/ACE-Step/ACE-Step-v1-3.5B/resolve/main"
DEST="D:/UserProfile/wqy32/dsh/home/work/xiaoxi-singer/models/ace-step"
FILES=(
  "config.json"
  "ace_step_transformer/config.json"
  "ace_step_transformer/diffusion_pytorch_model.safetensors"
  "music_dcae_f8c8/config.json"
  "music_dcae_f8c8/diffusion_pytorch_model.safetensors"
  "music_vocoder/config.json"
  "music_vocoder/diffusion_pytorch_model.safetensors"
)
for f in "${FILES[@]}"; do
  out="$DEST/$f"
  mkdir -p "$(dirname "$out")"
  total=$(curl -sIL -m 30 "$BASE/$f" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
  have=$(stat -c %s "$out" 2>/dev/null || echo 0)
  echo "[$(date +%H:%M:%S)] $f total=$total have=$have"
  if [ -n "$total" ] && [ "$have" = "$total" ]; then
    echo "  already complete"
    continue
  fi
  for try in $(seq 1 200); do
    have=$(stat -c %s "$out" 2>/dev/null || echo 0)
    if [ -n "$total" ] && [ "$have" -ge "${total:-0}" ]; then break; fi
    curl -sL --retry 5 --retry-delay 5 --connect-timeout 20 \
         --speed-limit 15000 --speed-time 90 -C - -o "$out" "$BASE/$f"
    rc=$?
    have2=$(stat -c %s "$out" 2>/dev/null || echo 0)
    echo "  try=$try rc=$rc have=$have2/$total"
    [ "$rc" = "0" ] && [ -n "$total" ] && [ "$have2" -ge "$total" ] && break
    sleep 2
  done
  echo "[$(date +%H:%M:%S)] done $f -> $(stat -c %s "$out" 2>/dev/null)"
done
echo ALLDONE
