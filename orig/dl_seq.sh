#!/bin/bash
# 顺序、可续传地拉 ACE-Step 权重（hf-mirror 单连接最稳）
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
  for try in $(seq 1 60); do
    have=$(stat -c %s "$out" 2>/dev/null || echo 0)
    echo "[$(date +%H:%M:%S)] $f have=$have try=$try"
    curl -sL --fail -C - --retry 5 --retry-delay 5 --connect-timeout 20 \
         --speed-limit 20000 --speed-time 120 -o "$out" "$BASE/$f" && break
    sleep 3
  done
  echo "[$(date +%H:%M:%S)] done $f -> $(stat -c %s "$out" 2>/dev/null)"
done
echo ALLDONE
