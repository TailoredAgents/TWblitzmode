#!/usr/bin/env bash
set -euo pipefail

# Push the current repo to GitHub using a Personal Access Token (PAT).
# Usage:
#   export GITHUB_TOKEN=...   # repo scope
#   ./push.sh [target]
#
# target:
#   main               Push to origin/main (default)
#   blitz-main-ready   Push local main to origin/blitz-main-ready

REPO_URL="https://github.com/TailoredAgents/TWblitzmode.git"
TARGET_BRANCH="${1:-main}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  echo "GITHUB_TOKEN not set. Export a PAT with repo scope:"
  echo "  export GITHUB_TOKEN=YOUR_TOKEN_HERE"
  exit 1
fi

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "Not a git repository. Run from repo root."
  exit 1
fi

# Ensure remote exists and is authenticated via PAT
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "https://x-access-token:${GITHUB_TOKEN}@github.com/TailoredAgents/TWblitzmode.git"
else
  git remote add origin "https://x-access-token:${GITHUB_TOKEN}@github.com/TailoredAgents/TWblitzmode.git"
fi

git branch -M main

if [[ "${TARGET_BRANCH}" == "main" ]]; then
  echo "Pushing to origin/main..."
  git push -u origin main
else
  echo "Pushing local main to origin/${TARGET_BRANCH}..."
  git push -u origin main:"${TARGET_BRANCH}"
fi

echo "Done. If branch protection blocks main, set default to '${TARGET_BRANCH}' or open a PR."

