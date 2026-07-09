---
last_updated: 2026-07-09
---

# Why

## Purpose

This repo is a personal podcast pipeline: turn a book (EPUB, PDF, or
markdown) into a published episode on schepens.cc with a single command.
The intended audience is one person — the author — who reads a lot and
wants to listen to book summaries while commuting or doing other things.

The original workflow was entirely manual: download EPUB → run the
`summarize-book` Claude skill → paste the output into a "rewrite for
voice" prompt → hand the result to a TTS script → upload MP3 to the
website. This repo started as just the TTS step. It was extended in May
2026 to automate all five steps into `podcastify book.epub`.

## Decisions

### One uv package, three global commands

All three tools (`tts`, `podcastify`, `publish-to-schepens`) are entry
points in a single `pyproject.toml` and installed with `uv tool install .`.

The driver was cognitive load: "it's hard to remember how I installed
tools if I do this in different ways." A bash wrapper was considered and
briefly implemented for `podcastify` but replaced with Python precisely
because the `uv tool install` mental model only works if everything goes
through it.

Reinstalling requires `--reinstall --force`, not just `--force` — uv
caches built wheels by `(name, version)` and `--force` alone reuses the
cached wheel. A PostToolUse hook in `.claude/settings.json` runs the
reinstall automatically after any `.py` or `pyproject.toml` edit in this
folder.

### publish_to_schepens.py lives here, not in openclaw-pi

The upload script originated in
`openclaw-pi/openclaw-workspace/tools/podcast/upload.py`, where it served
the dobby agent's YouTube → podcast flow. It was moved here because
publishing to schepens.cc is this repo's concern, not openclaw-pi's.

A shim was left at the original path so dobby's hardcoded references in
`AGENTS.md`, `TOOLS.md`, and `skills/podcast/SKILL.md` keep working
without changes. The shim `shutil.which`s and `os.execv`s the installed
`publish-to-schepens` command. The file was also renamed from `upload.py`
to `publish_to_schepens.py` to be descriptive about what it actually does.

The script supports both YouTube URLs (downloads via yt-dlp) and local
MP3 paths (direct upload). Local file support was added specifically for
the `podcastify` flow, which always produces a local file.

### Summarization uses the summarize-book skill + a spoken-rewrite pass

Three approaches were considered:

- **A. Single prompt** — tell Claude to do everything in one pass. Risk:
  later chapters get less attention as the context fills.
- **B. Multi-step orchestration** — extract text, split chapters, loop
  `claude -p` per chapter, stitch. Better quality but reimplements what
  the `summarize-book` skill already does.
- **C. Use the summarize-book skill, then rewrite** — invoke the skill
  (pre-answering its interactive prompts in the prompt itself), wait for
  `SUMMARY.md`, then rewrite as a spoken monologue.

Option C was chosen: leverages an existing, tested skill for the
chapter-by-chapter treatment, and stays a single `claude -p` invocation
from `podcastify`'s point of view. Length targets ~10% of the source word
count so longer books produce proportionally longer episodes.

### claude -p runs with --dangerously-skip-permissions --verbose

`claude -p` in a non-interactive pipeline can't respond to permission
prompts. Without `--dangerously-skip-permissions`, it asked for approval
to write the output `.md` file and then silently failed when no answer
came. The flag is appropriate here because the prompt is fully
author-controlled and the only file write is the output monologue.

`--verbose` was added so the summarization step (which can take several
minutes) shows tool-call activity rather than a silent hang.

### Output files land in CWD, not input/output subdirs

An earlier version wrote to `./input/<slug>.md` and `./output/<slug>.mp3`.
The preference was simpler: files go directly in the current working
directory, no subdirs. This makes `podcastify` useful from any folder —
run it from the book's folder, the files land there.

### Every stage is idempotent; podcastify resumes from artifacts (June 2026)

The summarize and render stages cost real money and minutes, so a failed
publish must not force redoing them. Each stage skips work whose output
already exists: `tts` compares mtimes, the server dedupes uploads by
audio content hash, and `podcastify --from auto` starts from the
furthest-along artifact (`<slug>.mp3` → publish only, `<slug>.md` →
render onward). `--from`/`--to` make the resume point explicit; `--force`
redoes everything. The artifact files in CWD *are* the pipeline state —
there is no separate state file.

### Episode metadata rides as ID3 tags on the MP3

`tts` embeds `--title`/`--description`/`--date` as ID3 tags via ffmpeg
(`-c copy`, no re-encode), and the schepens.cc server reads them with
ffprobe on import. This makes the MP3 self-describing: the publish stage
needs no sidecar metadata file, and a bare
`publish-to-schepens books foo.mp3` does the right thing. CLI flags on
`publish-to-schepens` still override the tags.

### pcommon.py: shared secrets, preflight, and self-documenting --help (June 2026)

Extracted so all three entry points behave identically in cloud/headless
runs:

- **`get_secret`** reads each key from the environment with a `*_FILE`
  fallback (Docker/Kamal mounted-secret convention), so secrets never
  need to appear in the process environment / `docker inspect`.
- **`preflight`** fails fast — before any paid API call — naming the
  missing variable or binary, never its value. `podcastify` preflights
  only the stages it will actually run.
- **`CHAIN_HELP`** is appended to every command's `--help` epilog: the
  chain diagram, the idempotency contract, the secrets, and the `uvx`
  cloud invocation. The goal is that an unattended agent can discover how
  to drive the pipeline from `--help` alone.

### Git history is one squashed commit

The repo was committed as a single snapshot (2026-06-26) when it
stabilized. Decision history lives in this file, not in git archaeology.
