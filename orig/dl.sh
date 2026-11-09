#!/bin/bash
BASE="https://hf-mirror.com/ACE-Step/ACE-Step-v1-3.5B/resolve/main"
DEST="D:/UserProfile/wqy32/dsh/home/work/xiaoxi-singer/models/ace-step"
for f in config.json ace_step_transformer/config.json ace_step_transformer/diffusion_pytorch_model.safetensors music_dcae_f8c8/config.json music_dcae_f8c8/diffusion_pytorch_model.safetensors music_vocoder/config.json music_vocoder/diffusion_pytorch_model.safetensors; do
  out="$DEST/$f"
  mkdir -p "$(dirname "$out")"
  for try in 1 2 3 4 5 6 7 8; do
    curl -L --fail --retry 3 --retry-delay 3 -C - --connect-timeout 20 --max-time 3600 -o "$out" "$BASE/$f" && break
    echo "retry $try $f"; sleep 5
  done
  echo "done $f $(stat -c %s "$out" 2>/dev/null)"
done
echo ALLDONE
