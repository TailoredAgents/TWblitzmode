# Syncing /blitz Into TWblitzmode (One‑Liner)

Use this to copy all Blitz docs, examples, CI, and scripts into your TWblitzmode working copy without touching history.

One‑liner (from the legacy repo root)

```bash
TARGET=../TWblitzmode; \
mkdir -p "$TARGET/.github/workflows" "$TARGET/blitz" && \
rsync -a --delete blitz/ "$TARGET/blitz/" && \
cp blitz/examples/ci/ci.yml "$TARGET/.github/workflows/ci.yml" && \
[ -f "$TARGET/README.md" ] || cp blitz/NEW_REPO_README.stub.md "$TARGET/README.md" && \
( cd "$TARGET" && git add blitz .github/workflows/ci.yml README.md && git commit -m "Add Blitz docs/CI" )
```

Alternate script

- `bash blitz/scripts/sync_blitz_to_target.sh /absolute/path/to/TWblitzmode`

Notes

- This syncs only the /blitz assets and CI workflow. Application code import should follow the approved extraction process (see `/blitz/CODEX_EXECUTION_GUIDE.md`).
- Do not copy secrets; configure them in Render or your local environment.

