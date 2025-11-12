#!/usr/bin/env bash
set -euo pipefail

# Blitz Extract Script (history-preserving or tarball)
# Purpose: create an artifact containing only Link core (backend, frontend UI, schema, docs)
# Note: Review ALLOWLIST before running. This script does NOT scrub secrets.

REPO_DIR="${REPO_DIR:-$(pwd)}"
OUT_DIR="${OUT_DIR:-$REPO_DIR/.blitz-out}"
mkdir -p "$OUT_DIR"

# Allowlist paths (edit to match your repo layout exactly)
ALLOWLIST=(
  "api/**"
  "services/**"
  "integrations/**"
  "core/**"
  "migrations/**"
  "frontend/src/app/**"
  "frontend/src/components/**"
  "frontend/src/services/**"
  "frontend/src/contexts/**"
  "frontend/src/types/**"
  "frontend/src/lib/**"
  "README.md"
  "AGENTS.md"
  "blitz/**"
)

echo "[blitz] Creating filelist..."
FILELIST_PATH="$OUT_DIR/allowlist.txt"
printf '%s\n' "${ALLOWLIST[@]}" > "$FILELIST_PATH"

echo "[blitz] Preparing tarball (no history) ..."
TARBALL_PATH="$OUT_DIR/link-core.tar"
git archive -o "$TARBALL_PATH" HEAD $(tr '\n' ' ' < "$FILELIST_PATH")
echo "[blitz] Tarball written: $TARBALL_PATH"

echo "[blitz] Preparing bundle (history-preserving) ..."
BUNDLE_PATH="$OUT_DIR/link-core.bundle"
git bundle create "$BUNDLE_PATH" HEAD
echo "[blitz] Bundle written: $BUNDLE_PATH"

cat <<EOF

Artifacts:
- Tarball (no history):   $TARBALL_PATH
- Bundle (full history):  $BUNDLE_PATH

Next:
- Use blitz_import.sh to initialize the new repo and push.
EOF

