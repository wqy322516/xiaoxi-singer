#!/usr/bin/env bash
# Publish this repository to GitHub once an account exists.
#
#   1) create a token (classic): Settings -> Developer settings -> Personal access
#      tokens -> Tokens (classic) -> Generate new token, scopes: repo + workflow
#   2) run:  GITHUB_USER=<你的用户名> GITHUB_TOKEN=<token> ./scripts/publish.sh [repo-name]
#
# Safe to re-run: it creates the repo only if it does not exist, then pushes main.
set -euo pipefail
: "${GITHUB_USER:?set GITHUB_USER}"
: "${GITHUB_TOKEN:?set GITHUB_TOKEN}"
REPO="${1:-xiaoxi-singer}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

api="https://api.github.com"
auth=(-H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json")

echo "==> checking $GITHUB_USER/$REPO"
code=$(curl -s -o /tmp/gh_repo.json -w '%{http_code}' "${auth[@]}" "$api/repos/$GITHUB_USER/$REPO")
if [ "$code" = "404" ]; then
  echo "==> creating repository"
  curl -s -X POST "${auth[@]}" "$api/user/repos" \
    -d "{\"name\":\"$REPO\",\"description\":\"A singing voice you can call - RVC engine + LLM agent + desktop client\",\"private\":false,\"has_issues\":true}" \
    -o /tmp/gh_new.json
  grep -q '"full_name"' /tmp/gh_new.json || { echo "create failed:"; cat /tmp/gh_new.json; exit 1; }
elif [ "$code" != "200" ]; then
  echo "unexpected status $code"; cat /tmp/gh_repo.json; exit 1
fi

git remote remove origin 2>/dev/null || true
git remote add origin "https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO}.git"
git push -u origin HEAD:main
git remote set-url origin "https://github.com/${GITHUB_USER}/${REPO}.git"   # keep the token out of .git/config

echo "==> done: https://github.com/$GITHUB_USER/$REPO"
echo "==> tag: git tag v0.1.0 && git push origin v0.1.0"
