# Status

_Last updated: 2026-07-09_

Snapshot for anyone (human or agent) picking this repo up cold. What it is
and how to use it: [README](../README.md). Why it's built this way:
[WHY.md](WHY.md).

## Current state: working, no open work

All three commands (`tts`, `podcastify`, `publish-to-schepens`) are
implemented, installed via `uv tool install .`, and in personal use for
publishing book-summary episodes to https://schepens.cc/podcast/episodes.
Version 0.3.0. There are **no open plans, TODOs, or half-finished
branches** — the repo is in maintenance mode.

Git history is a single squashed commit (2026-06-26); don't expect to mine
it for decision context. That context lives in [WHY.md](WHY.md).

## How to verify it still works

```bash
uv tool install --reinstall --force .   # ALWAYS --reinstall --force, never --force alone
tts --help                              # every --help prints the full chain diagram
podcastify some-book.epub --to script   # cheapest end-to-end-ish check (LLM only, no TTS/upload)
```

Each command's `--help` epilog (from `pcommon.CHAIN_HELP`) documents the
chain, the idempotency contract, and which secrets each stage needs — the
tools are designed to be discoverable by an agent unaided.

## Gotchas a new maintainer should know

- **`uv tool install --force` alone silently does nothing** after code
  edits — uv reuses the cached wheel. Use `--reinstall --force`. A
  PostToolUse hook in `.claude/settings.json` runs this automatically after
  any `.py`/`pyproject.toml` edit in a Claude Code session started from
  this folder.
- **`input/` is gitignored.** A fresh clone won't have
  `input/SUMMARY_SPOKEN.md` (a legacy hand-prepped script that exists only
  on the author's machine). `input/` and `output/` are both vestigial;
  `podcastify` writes to CWD.
- **`publish-to-schepens` hardcodes yt-dlp at `~/.local/bin/yt-dlp`**
  (`YT_DLP` in `publish_to_schepens.py`). If yt-dlp is only on PATH
  elsewhere, preflight passes but the actual download call fails. Only
  affects YouTube-URL uploads, not the `podcastify` flow.
- **schepens.cc is personal infrastructure.** Uploads need
  `SCHEPENS_API_TOKEN`; the server dedupes by audio content hash (so
  re-uploads are no-ops) and reads title/description/date from the MP3's
  ID3 tags via ffprobe. Anyone else must repoint the constants in
  `publish_to_schepens.py` or use `--skip-upload`.
- **`docs/tts-walkthrough.md` describes an earlier revision of `tts.py`**
  (before pcommon, ID3 tagging, and idempotency were added). It's kept as
  a Python teaching doc; the chunk/render/concat core it explains is still
  accurate.
- **Secrets** are env vars with `*_FILE` fallbacks (`pcommon.get_secret`):
  `OPENAI_API_KEY` (tts), `ANTHROPIC_API_KEY` (headless claude),
  `SCHEPENS_API_TOKEN` (publish). Preflight fails fast, naming the missing
  variable, before any paid work.

## Related, outside this repo

- A shim at
  `~/Tinker/openclaw-pi/openclaw-workspace/tools/podcast/upload.py`
  `exec`s the installed `publish-to-schepens`, so the dobby agent's
  hardcoded `upload.py` references keep working. If you rename that
  command, update the shim.
- Cloud/headless runs go through `uvx --from git+ssh://...` inside
  per-run containers with Kamal-injected secrets — see
  [README § Running in the cloud](../README.md#running-in-the-cloud-digitalocean--kamal).
