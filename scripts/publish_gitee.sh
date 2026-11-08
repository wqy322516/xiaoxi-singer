#!/usr/bin/env bash
# Publish this repository to Gitee (works from mainland China, no VPN).
#
#   1) register at gitee.com with a phone number
#   2) 头像 -> 设置 -> 私人令牌 -> 生成新令牌, scopes: projects
#   3) run:  GITEE_USER=<用户名> GITEE_TOKEN=<token> ./scripts/publish_gitee.sh [repo]
#
# Creates the repo through the Gitee API if it does not exist, then pushes main.
set -euo pipefail
: "${GITEE_USER:?set GITEE_USER}"
: "${GITEE_TOKEN:?set GITEE_TOKEN}"
REPO="${1:-xiaoxi-singer}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

api="https://gitee.com/api/v5"

echo "==> checking $GITEE_USER/$REPO"
code=$(curl -s -o /tmp/gt_repo.json -w '%{http_code}' "$api/repos/$GITEE_USER/$REPO")
if [ "$code" = "404" ]; then
  echo "==> creating repository"
  curl -s -X POST "$api/user/repos" \
    -d "access_token=$GITEE_TOKEN" \
    -d "name=$REPO" \
    -d "description=A singing voice you can call - RVC engine + LLM agent + desktop client" \
    -d "private=false" \
    -d "has_issues=true" \
    -o /tmp/gt_new.json
  grep -q '"full_name"' /tmp/gt_new.json || { echo "create failed:"; cat /tmp/gt_new.json; exit 1; }
elif [ "$code" != "200" ]; then
  echo "unexpected status $code"; cat /tmp/gt_repo.json; exit 1
fi

git remote remove gitee 2>/dev/null || true
git remote add gitee "https://${GITEE_USER}:${GITEE_TOKEN}@gitee.com/${GITEE_USER}/${REPO}.git"
git push -u gitee HEAD:master || git push -u gitee HEAD:main
git remote set-url gitee "https://gitee.com/${GITEE_USER}/${REPO}.git"

echo "==> done: https://gitee.com/$GITEE_USER/$REPO"
