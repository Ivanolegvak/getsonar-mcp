#!/usr/bin/env bash
# Build a history-free snapshot of mcp-server/ for the PUBLIC mirror repo
# github.com/Ivanolegvak/getsonar-mcp (the monorepo is private; Glama,
# mcp.so and the README badges need public source).
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

# Tracked files only (no .venv, caches or a stray .env), minus files that
# stay internal. DIRECTORIES.md is the maintainer's release and listing
# runbook (portal steps, operator decisions); it was removed from the mirror
# by hand twice before this exclusion existed. .env.example is a local-dev
# template (README's Configuration table documents the same variables); it
# was left out when the mirror root was still the Claude plugin folder and
# stays out.
EXCLUDE=(DIRECTORIES.md .env.example)
# tar -h copies the file a symlink points to: claude-plugin/icon.png is a
# symlink to the package icon here, and the Claude directory refuses
# symbolic links in a plugin.
git -C "$SRC" ls-files -z -- . "${EXCLUDE[@]/#/:(exclude)}" \
  | (cd "$SRC" && xargs -0 tar chf -) | (cd "$OUT" && tar xf -)
for f in "${EXCLUDE[@]}"; do
  if [ -e "$OUT/$f" ]; then
    echo "internal file $f ended up in the snapshot; aborting" >&2
    exit 1
  fi
done

# The Claude plugin is the claude-plugin/ folder (portal "Plugin path"),
# not the mirror root: the root carries Python, Docker, lock and CI files
# for PyPI, Glama and the MCP Registry, and the Claude directory accepts
# only Markdown, text, JSON, YAML and images in a plugin from an unverified
# organization. The folder must hold exactly these files, as regular files,
# and be the only .claude-plugin manifest in the mirror.
PLUGIN_DIR=claude-plugin
PLUGIN_FILES=(.claude-plugin/plugin.json .mcp.json README.md icon.png)
actual="$(cd "$OUT/$PLUGIN_DIR" && find . -mindepth 1 ! -type d | sed 's|^\./||' | LC_ALL=C sort)"
expected="$(printf '%s\n' "${PLUGIN_FILES[@]}" | LC_ALL=C sort)"
if [ "$actual" != "$expected" ]; then
  echo "$PLUGIN_DIR/ must hold exactly: ${PLUGIN_FILES[*]}; found:" >&2
  echo "$actual" >&2
  exit 1
fi
if [ -n "$(find "$OUT" -path "$OUT/.git" -prune -o -type l -print)" ]; then
  echo "symbolic link in the snapshot; aborting" >&2
  exit 1
fi
if [ "$(find "$OUT" -path "$OUT/.git" -prune -o -name .claude-plugin -print | wc -l | tr -d ' ')" != 1 ]; then
  echo "more than one .claude-plugin folder in the snapshot; aborting" >&2
  exit 1
fi

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
echo "Claude plugin folder (portal Plugin path): $PLUGIN_DIR"
echo "Review it (git -C '$OUT' show --stat), then publish with:"
if [ "$UPDATE" = 1 ]; then
  echo "  git -C '$OUT' push"
else
  echo "  git -C '$OUT' remote add origin git@github.com:Ivanolegvak/getsonar-mcp.git"
  echo "  git -C '$OUT' push -u origin main"
fi
