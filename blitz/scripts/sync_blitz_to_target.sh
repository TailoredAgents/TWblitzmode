#!/usr/bin/env bash
set -euo pipefail

# Sync /blitz assets into a target repo working copy.
# Usage:
#   bash blitz/scripts/sync_blitz_to_target.sh /path/to/TWblitzmode
# or set env TARGET_DIR=/path/to/TWblitzmode and run without args.

TARGET_DIR="${1:-${TARGET_DIR:-}}"
if [ -z "${TARGET_DIR}" ]; then
  echo "Usage: $0 /absolute/path/to/TWblitzmode" >&2
  exit 2
fi

if [ ! -d "${TARGET_DIR}" ]; then
  echo "Target directory does not exist: ${TARGET_DIR}" >&2
  exit 2
fi

echo "[blitz] Syncing /blitz to ${TARGET_DIR} ..."

# Create necessary directories
mkdir -p "${TARGET_DIR}/blitz"
mkdir -p "${TARGET_DIR}/.github/workflows"

# Copy entire blitz folder
rsync -a --delete blitz/ "${TARGET_DIR}/blitz/"

# Promote CI workflow
cp -f blitz/examples/ci/ci.yml "${TARGET_DIR}/.github/workflows/ci.yml"

# Seed README if absent
if [ ! -f "${TARGET_DIR}/README.md" ]; then
  cp blitz/NEW_REPO_README.stub.md "${TARGET_DIR}/README.md"
fi

cat <<EOF
[blitz] Sync complete.
Next steps in ${TARGET_DIR}:
  git add blitz .github/workflows/ci.yml README.md
  git commit -m "Add Blitz docs, CI, and scaffolding"
  git push -u origin main
EOF

