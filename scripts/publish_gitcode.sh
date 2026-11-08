#!/usr/bin/env bash
# Publish this repository to GitCode (CSDN), which is reachable from mainland
# China without a VPN.
#
#   1) register / log in at gitcode.com (CSDN account works)
#   2) 头像 -> 设置 -> 访问令牌 (Access Token) -> 新建, scope: repo / projects
#   3) run:  GITCODE_USER=<用户名> GITCODE_TOKEN=<token> ./scripts/publish_gitcode.sh [repo]
#
# Creates the repository through the API when it does not exist, then pushes main.
set -euo pipefail
: "${GITCODE_USER:?set GITCODE_USER}"
: "${GITCODE_TOKEN:?set GITCODE_TOKEN}"
REPO="${1:-xiaoxi-singer}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

api="https://api.gitcode.com/api/v5"

echo "==> checking $GITCODE_USER/$REPO"
code=$(curl -s -o /tmp/gc_repo.json -w '%{http_code}' "$api/repos/$GITCODE_USER/$REPO?access_token=$GITCODE_TOKEN")
if [ "$code" = "404" ]; then
  echo "==> creating repository"
  curl -s -X POST "$api/user/repos?access_token=$GITCODE_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$REPO\",\"description\":\"A singing voice you can call - RVC engine + LLM agent + desktop client\",\"public\":1,\"auto_init\":false,\"default_branch\":\"main\"}" \
    -o /tmp/gc_new.json
  grep -q '"full_name"\|"path"' /tmp/gc_new.json || { echo "create failed:"; cat /tmp/gc_new.json; exit 1; }
elif [ "$code" != "200" ]; then
  echo "unexpected status $code"; head -c 300 /tmp/gc_repo.json; exit 1
fi

git remote remove gitcode 2>/dev/null || true
git remote add gitcode "https://${GITCODE_USER}:${GITCODE_TOKEN}@gitcode.com/${GITCODE_USER}/${REPO}.git"
git push -u gitcode HEAD:main
git remote set-url gitcode "https://gitcode.com/${GITCODE_USER}/${REPO}.git"

git tag -f v0.1.0 >/dev/null
git push gitcode v0.1.0 || true

echo "==> done: https://gitcode.com/$GITCODE_USER/$REPO"
