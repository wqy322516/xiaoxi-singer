#!/bin/bash
# 拉 umt5-base（ACE-Step 的文本编码器）到 models/ace-step/umt5-base
BASE="https://hf-mirror.com/google/umt5-base/resolve/main"
DEST="D:/UserProfile/wqy32/dsh/home/work/xiaoxi-singer/models/ace-step/umt5-base"
FILES=(config.json generation_config.json pytorch_model.bin tokenizer.json tokenizer_config.json special_tokens_map.json spiece.model)
mkdir -p "$DEST"
for f in "${FILES[@]}"; do
  out="$DEST/$f"
  total=$(curl -sIL -m 30 "$BASE/$f" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
  have=$(stat -c %s "$out" 2>/dev/null || echo 0)
  echo "[$(date +%H:%M:%S)] $f total=$total have=$have"
  if [ -n "$total" ] && [ "$total" -gt 1000 ] && [ "$have" = "$total" ]; then echo "  complete"; continue; fi
  for try in $(seq 1 120); do
    have=$(stat -c %s "$out" 2>/dev/null || echo 0)
    if [ -n "$total" ] && [ "$have" -ge "${total:-0}" ]; then break; fi
    curl -sL --retry 5 --retry-delay 5 --connect-timeout 20 \
         --speed-limit 15000 --speed-time 90 -C - -o "$out" "$BASE/$f"
    have2=$(stat -c %s "$out" 2>/dev/null || echo 0)
    echo "  try=$try have=$have2/$total"
    if [ -n "$total" ] && [ "$have2" -ge "$total" ]; then break; fi
    sleep 2
  done
done
echo UMT5DONE
