#!/usr/bin/env bash
set -euo pipefail

# Blitz Import Script
# Purpose: initialize a fresh repo from link-core bundle or tarball and prepare for Render.

TARGET_DIR="${1:-./link-core}"
BUNDLE_PATH="${BUNDLE_PATH:-.blitz-out/link-core.bundle}"
TARBALL_PATH="${TARBALL_PATH:-.blitz-out/link-core.tar}"

mkdir -p "$TARGET_DIR"
cd "$TARGET_DIR"

if [ -f "../$BUNDLE_PATH" ]; then
  echo "[blitz] Initializing from bundle (history-preserving) ..."
  git init
  git pull "../$BUNDLE_PATH"
elif [ -f "../$TARBALL_PATH" ]; then
  echo "[blitz] Initializing from tarball (no history) ..."
  tar -xf "../$TARBALL_PATH" -C .
  git init
  git add .
  git commit -m "Blitz import of Link core"
else
  echo "[blitz] No bundle or tarball found at $BUNDLE_PATH or $TARBALL_PATH" >&2
  exit 1
fi

cat <<EOF

Next steps:
- Create a new Git remote and push:
    git remote add origin <NEW_REPO_URL>
    git branch -M main
    git push -u origin main
- Configure Render services (API + Frontend) with environment variables from blitz docs.
- Run migrations and seed, then deploy.
EOF

