#!/usr/bin/env bash
# Fetch the RVC fork this package runs on, and apply the sweet-zone patch.
#
#   RVC_DIR=vendor/Retrieval-based-Voice-Conversion-WebUI bash scripts/install_rvc.sh
#
set -euo pipefail

RVC_DIR="${RVC_DIR:-vendor/Retrieval-based-Voice-Conversion-WebUI}"
REPO="https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git"

if [ ! -d "$RVC_DIR/.git" ]; then
  echo ">> clone $REPO -> $RVC_DIR"
  mkdir -p "$(dirname "$RVC_DIR")"
  git clone --depth 1 "$REPO" "$RVC_DIR"
fi

cd "$RVC_DIR"

if grep -q "RVC_SWEET" infer/vc/pipeline.py; then
  echo ">> sweet-zone patch already applied"
else
  echo ">> applying patches/rvc-sweet-zone.patch"
  git apply --3way "$(cd - >/dev/null && pwd)/patches/rvc-sweet-zone.patch" || {
    echo "!! patch failed; the upstream file changed. Apply manually:" >&2
    echo "   see patches/rvc-sweet-zone.patch (only infer/vc/pipeline.py is touched)" >&2
    exit 1
  }
fi

cat <<'EOF'

>> RVC ready. Still required (upstream weights, not shipped here):
   assets/pretrained_v2/f0G40k.pth   assets/pretrained_v2/f0D40k.pth
   assets/hubert/hubert_base.pt      assets/rmvpe/rmvpe.pt
   Download them with:
     python - <<'PY'
     from huggingface_hub import snapshot_download
     snapshot_download("lj1995/VoiceConversionWebUI", local_dir="assets")
     PY

>> Then:
   export RVC_ROOT="$PWD"
   python -m pip install -e .[server,mcp]
EOF
