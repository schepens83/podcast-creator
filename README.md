# podcast-creator

Three small tools for turning books into a personal podcast:

| Command | What it does |
| --- | --- |
| `tts` | Render a markdown/text script to MP3 via OpenAI `gpt-4o-mini-tts`. |
| `podcastify` | Full pipeline: book → spoken-monologue summary → MP3 → uploaded episode. |
| `publish-to-schepens` | Upload an MP3 (or YouTube URL) to schepens.cc/podcast. |

All three are installed by a single `uv tool install .`.

New here? [docs/STATUS.md](docs/STATUS.md) is the taking-over snapshot
(current state, gotchas); [docs/WHY.md](docs/WHY.md) is the decision log.

## What the pipeline does

`podcastify book.epub` runs three steps:

1. **Summarize.** Shells out to either `claude -p` or `codex exec` with a
   prompt that inlines two bundled skills from `skills/` — `summarize-book`
   (extract chapters, summarize each into a combined `SUMMARY.md`) and
   `podcast-summary` (rewrite that summary as a single spoken monologue with
   the voice rules). The skill text is embedded in the prompt at runtime, so
   nothing needs to be installed in the agent and you can run from any
   directory.
2. **Render.** Shells out to `tts` to turn that monologue markdown into an
   MP3. Long scripts are auto-chunked on paragraph boundaries (4000 chars/
   chunk) and stitched together losslessly with `ffmpeg -c copy`.
3. **Publish.** Shells out to `publish-to-schepens` to upload the MP3 to
   `https://schepens.cc/podcast/episodes` (the `books` feed) with a bearer
   token. Title/description/date ride along as ID3 tags on the MP3 and are
   read server-side.

Output: `<slug>.md` and `<slug>.mp3` land in your current working directory.
The summarize step also leaves its `<book-title>/` folder there
(chapter files, plan, etc.) — useful keeps, or `.gitignore` them.

## Idempotency & running stages independently

Each command is a stage of one chain, and each is **idempotent** — re-running
skips work that's already done:

- `tts` skips rendering if the output MP3 is newer than the script (`--force`
  to re-render).
- `publish-to-schepens` is a no-op if the identical audio is already live (the
  server dedupes by content hash); `--replace` deletes the same-named episode
  first and re-uploads.
- `podcastify` auto-detects existing `<slug>.md` / `<slug>.mp3` and resumes from
  the furthest-along artifact. Run a subset with `--from {auto,source,script,mp3}`
  and `--to {script,mp3,publish}`:

  ```bash
  podcastify book.epub --to script     # just produce the spoken script
  podcastify book.epub --to mp3        # script + render, no upload
  podcastify book.epub --from script   # reuse an existing script.md, render + publish
  podcastify book.epub --force         # redo every stage from scratch
  ```

Every command's `--help` prints the full chain diagram, the secrets it needs,
and the cloud invocation — so an agent can discover how to use it unaided.

## Dependencies

### Required for everything

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** — installer/runner.
- **OpenAI API key** with billing — TTS is not covered by ChatGPT Plus/Pro.
  Set `OPENAI_API_KEY` in your shell. Pricing: ~$0.60 per 1M input chars
  (a 30-min episode is well under a cent).

> **Secrets:** every key below is read from the environment, each with a
> `*_FILE` fallback — e.g. `OPENAI_API_KEY` **or** `OPENAI_API_KEY_FILE=/run/secrets/openai`.
> The `*_FILE` form reads the secret from a mounted file so it never appears in
> the process environment / `docker inspect`. Never commit keys to the repo
> (private or not). See [Running in the cloud](#running-in-the-cloud-digitalocean--kamal).

### Required for `tts` (and therefore `podcastify`)

- **`ffmpeg`** on PATH. Only invoked when a script exceeds ~4000 chars and
  needs to be chunked and concatenated. Most podcast-length scripts hit
  this.

### Required for `podcastify`

- **One LLM CLI on PATH:**
  - **`claude`** CLI, authenticated. Default path. `podcastify` uses the
    `sonnet` model unless you pass `--model`. For **headless/cloud** runs (no
    interactive login), set `ANTHROPIC_API_KEY` (or `ANTHROPIC_API_KEY_FILE`)
    in the environment and the CLI uses it directly.
  - **`codex`** CLI, authenticated. Optional alternative. `podcastify`
    passes no model with `--llm codex`, so Codex uses the one set in its own
    `config.toml`; override it with `--model`.
- **No skill install needed.** The `summarize-book` and `podcast-summary`
  instructions ship in this repo under `skills/` and are inlined into the
  prompt at runtime, so the chosen agent doesn't need them installed and you
  can run from any directory.
- **`pandoc` and/or `pdftotext`** for EPUB and PDF source files. The LLM
  agent may shell out to these via its Bash tool. Not needed if you only
  feed `.md` or `.txt`.

### Required for `publish-to-schepens`

- **A schepens.cc account** with podcast upload privileges. Uploads hit
  the API endpoint (`https://schepens.cc/podcast/api/episodes`) with a
  bearer token read from the `SCHEPENS_API_TOKEN` environment variable.
  Export it in your shell (add to `~/.bashrc` to persist):

  ```bash
  export SCHEPENS_API_TOKEN=...
  ```

  This is personal infrastructure, not a public service. If you're not
  the author, either:
  - Point it at your own podcast host (edit `PODCAST_URL` and the auth
    header / `requests.post` payload shape), or
  - Run `podcastify` with `--skip-upload`, then upload the resulting MP3
    by hand.
- **`yt-dlp`** at `~/.local/bin/yt-dlp` — only used when uploading
  YouTube URLs (not for the `podcastify` flow, which only ever uploads
  local MP3s).
- Network access to `https://schepens.cc/podcast/episodes`.

## Install

From the project root:

```bash
uv tool install .
```

Adds three executables to `~/.local/bin/`: `tts`, `podcastify`,
`publish-to-schepens`. Make sure `~/.local/bin` is on your `PATH`.

After editing any of the `.py` files, reinstall to pick up changes:

```bash
uv tool install --reinstall --force .
```

`--force` alone is **not** enough — uv reuses the cached wheel and your
edits silently don't land. In Claude Code sessions started from this
folder, a PostToolUse hook in `.claude/settings.json` runs the reinstall
automatically after any `.py`/`pyproject.toml` edit.

(`-e` editable installs also work: `uv tool install -e .`.)

Set your OpenAI key (add to `~/.bashrc` to persist):

```bash
export OPENAI_API_KEY=sk-...
```

## Running in the cloud (DigitalOcean + Kamal)

The pipeline runs unattended on a server with no Docker image of its own — the
host already runs each job in a container, so we just run inside it and pull this
(private) repo per run with `uvx`:

```bash
# inside the per-run container; clones the private repo and runs one stage
uvx --from git+ssh://git@github.com/<you>/podcast-creator podcastify book.epub
uvx --from git+ssh://git@github.com/<you>/podcast-creator tts script.md -o ep.mp3
uvx --from git+ssh://git@github.com/<you>/podcast-creator publish-to-schepens books ep.mp3
```

(The container needs an SSH deploy key or token with read access to the repo, plus
`ffmpeg`, `pandoc`/`pdftotext`, and the `claude`/`codex` CLI for the summarize stage.)

### Secrets via Kamal

Keys never live in the repo. They ride the same channel as the rest of the
server — the gitignored Kamal secrets file, injected into each container as env:

1. Add the keys to your Kamal secrets file (gitignored, pushed on deploy):

   ```bash
   # .kamal/secrets  (NOT committed)
   OPENAI_API_KEY=$OPENAI_API_KEY
   ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
   SCHEPENS_API_TOKEN=$SCHEPENS_API_TOKEN
   ```

2. Declare them in `config/deploy.yml` so Kamal injects them into the container:

   ```yaml
   env:
     secret:
       - OPENAI_API_KEY
       - ANTHROPIC_API_KEY
       - SCHEPENS_API_TOKEN
   ```

The tools read these straight from the environment. If you'd rather mount secrets
as files (Docker/K8s secrets), use the `*_FILE` variant — e.g.
`SCHEPENS_API_TOKEN_FILE=/run/secrets/schepens` — and nothing changes on the tool
side. A missing key fails fast at startup with a message that names the variable
(never its value).

## Usage

### Full pipeline

```bash
# anywhere on disk — outputs land in CWD
podcastify ~/Downloads/some-book.epub

# with a pretty title (drives the filename slug + episode title)
podcastify ~/Downloads/some-book.epub "The Title I Want"

# preview the mp3 first, don't upload
podcastify ~/Downloads/some-book.epub --skip-upload

# use Codex instead of Claude
podcastify ~/Downloads/some-book.epub --llm codex

# override the LLM model explicitly
podcastify ~/Downloads/some-book.epub --llm codex --model <model>
```

### TTS only

If you already have a script and just want audio:

```bash
tts script.md
tts script.md --voice sage
tts script.md --instructions "Calm late-night radio host. Long pauses."
tts script.md --instructions-file prompts/host_voice.txt
tts script.md -o output/pilot_v3.mp3
```

Voices: `alloy`, `ash` (default), `ballad`, `coral`, `nova`, `sage`,
`shimmer`. See `prompts/rewrite_for_voice.md` for the rewriting prompt
to paste into Claude/ChatGPT if you want to prep a script manually.

### Upload only

```bash
# local mp3 (title/description default to the mp3's ID3 tags)
publish-to-schepens books output/foo.mp3

# override metadata
publish-to-schepens books output/foo.mp3 --title "My Episode" --description "..."

# overwrite an existing same-named episode (delete + re-upload)
publish-to-schepens books output/foo.mp3 --replace

# YouTube URL (downloads + transcodes via yt-dlp first)
publish-to-schepens youtube "https://youtube.com/watch?v=..."
```

## Tuning the output

Two knobs that matter most for audio quality:

- **`tts --instructions`** — `gpt-4o-mini-tts` is steerable. Describe
  tone, pacing, emotion, accent. "Thoughtful, slightly amused, slow down
  on technical terms, leave a beat after rhetorical questions" produces
  noticeably different audio than the default.
- **The script itself.** Short sentences, contractions, em-dashes for
  breath, spelled-out numbers. The voice rules in
  `skills/podcast-summary/SKILL.md` (mirrored in `prompts/rewrite_for_voice.md`)
  enforce this.

## Customizing

- **Voice rules & summarization behavior.** Edit the bundled skills under
  `skills/` — `skills/podcast-summary/SKILL.md` (voice rules, spoken-monologue
  rewrite) and `skills/summarize-book/SKILL.md` (chaptering, summary depth).
  They're inlined into the prompt at runtime, so no reinstall is needed for
  edits to take effect.
- **Prompt orchestration.** Edit `build_prompt()` in `podcastify.py` to change
  how the two skills are framed or ordered.
- **LLM defaults.** Edit `DEFAULT_CLAUDE_MODEL` and `DEFAULT_CODEX_MODEL`
  in `podcastify.py`.
- **Upload destination.** Edit the constants at the top of
  `publish_to_schepens.py`.

## Layout

```
├── pyproject.toml                # 3 entry points, deps: openai, requests
├── pcommon.py                    # shared: secrets (*_FILE), preflight, chain help, slugify
├── tts.py                        # tts command
├── podcastify.py                 # podcastify command
├── publish_to_schepens.py        # publish-to-schepens command
├── skills/                       # bundled, inlined into the prompt at runtime
│   ├── summarize-book/SKILL.md   # source -> chaptered SUMMARY.md
│   └── podcast-summary/SKILL.md  # SUMMARY.md -> spoken monologue + voice rules
├── prompts/
│   ├── rewrite_for_voice.md      # standalone voice-rewriting prompt
│   └── sympathetic.md            # example --instructions-file voice preset
├── docs/
│   ├── STATUS.md                 # taking-over snapshot: state, gotchas
│   ├── WHY.md                    # decision log
│   └── tts-walkthrough.md        # Python teaching tour of (an earlier) tts.py
├── .claude/settings.json         # hook: auto `uv tool install --reinstall --force` on edit
├── input/                        # legacy hand-prepped scripts (gitignored, local only)
└── output/                       # legacy mp3s (empty)
```

The `input/` and `output/` folders are vestigial — `tts` will still write
to `output/` by default when given a relative path, but `podcastify` now
drops files directly in CWD.

## Related

A shim at
`/home/sander/Tinker/openclaw-pi/openclaw-workspace/tools/podcast/upload.py`
forwards to the installed `publish-to-schepens` command, so the dobby
agent's hardcoded `upload.py` references keep working.

## Uninstall

```bash
uv tool uninstall podcast-creator
```
