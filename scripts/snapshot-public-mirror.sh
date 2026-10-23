#!/usr/bin/env bash
# Build a history-free snapshot of mcp-server/ for the PUBLIC mirror repo
# github.com/Ivanolegvak/getsonar-mcp (the monorepo is private; Glama,
# mcp.so, Smithery and the README badges need public source).
#
# It only builds a local git repo with one commit. It never pushes: the
# script prints the push command for a human to run after reviewing the
# tree. No monorepo history is copied, so nothing outside mcp-server/
# (and no old commit) can leak.
#
# Usage:
#   first release:  mcp-server/scripts/snapshot-public-mirror.sh [NEW_EMPTY_DIR]
#   later releases: git clone git@github.com:Ivanolegvak/getsonar-mcp.git /tmp/m
#                   mcp-server/scripts/snapshot-public-mirror.sh /tmp/m
#     (an existing clone gets its files replaced and one new commit on top)
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$(mktemp -d)/getsonar-mcp}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/src/getsonar_mcp/__init__.py")"

if [ -d "$OUT/.git" ]; then
  UPDATE=1
  git -C "$OUT" rm -rq --ignore-unmatch . >/dev/null
elif [ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ]; then
  echo "refusing to write into non-empty $OUT (not a git clone)" >&2
  exit 1
else
  UPDATE=0
  mkdir -p "$OUT"
fi

# Tracked files only (no .venv, caches or a stray .env).
git -C "$SRC" ls-files -z -- . | (cd "$SRC" && xargs -0 tar cf -) | (cd "$OUT" && tar xf -)

# Belt and braces: refuse if anything looks like a live key.
if grep -rIlE 'sk-sonar-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|BEGIN (RSA|OPENSSH) PRIVATE KEY' "$OUT"; then
  echo "possible secret in the snapshot above; aborting" >&2
  exit 1
fi

[ "$UPDATE" = 1 ] || git -C "$OUT" init -q -b main
git -C "$OUT" add -A
if [ "$UPDATE" = 1 ] && git -C "$OUT" diff --cached --quiet; then
  echo "Mirror at $OUT already matches mcp-server/ ($VERSION); nothing to commit."
  exit 0
fi
git -C "$OUT" -c user.name="SONAR" -c user.email="ivan@getsonar.report" \
  commit -q -m "getsonar-mcp $VERSION (snapshot of the SONAR monorepo mcp-server/)"

echo "Snapshot ready: $OUT (version $VERSION, $(git -C "$OUT" ls-files | wc -l | tr -d ' ') files)"
echo "Review it (git -C '$OUT' show --stat), then publish with:"
if [ "$UPDATE" = 1 ]; then
  echo "  git -C '$OUT' push"
else
  echo "  git -C '$OUT' remote add origin git@github.com:Ivanolegvak/getsonar-mcp.git"
  echo "  git -C '$OUT' push -u origin main"
fi
