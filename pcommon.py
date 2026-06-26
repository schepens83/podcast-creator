"""Shared helpers for the podcast-creator pipeline.

The three commands form one chain, and each stage is independently runnable
and idempotent:

    source(.epub/.pdf/.md) --[podcastify: summarize via claude/codex]--> script.md
    script.md              --[tts: render via OpenAI gpt-4o-mini-tts]--> episode.mp3
    episode.mp3            --[publish-to-schepens]-------------------> schepens.cc/podcast

This module is bundled into the wheel (see pyproject `only-include`) so all
three entry points can `import pcommon`.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

# Shown as the --help epilog of every command so an agent (or future-you) can
# see the whole chain, the idempotency contract, and how secrets are supplied.
CHAIN_HELP = """\
PART OF A 3-STAGE CHAIN (each stage runs on its own; all are idempotent):

  source(.epub/.pdf/.md) --[podcastify: summarize]--> script.md
  script.md              --[tts: render]------------> episode.mp3
  episode.mp3            --[publish-to-schepens]----> schepens.cc/podcast

  podcastify  orchestrates all three; --from/--to run a subset of stages.
  tts         stage 2 only: script.md -> episode.mp3
  publish-to-schepens  stage 3 only: episode.mp3 -> live episode

Re-running skips work already done (pass --force to redo). Uploading the same
audio twice is a no-op (the server dedupes by content hash); use --replace to
overwrite an episode.

SECRETS are read from the environment, each with a *_FILE fallback (read the
secret from the file at that path -- Docker/Kamal mounted-secret convention):
  OPENAI_API_KEY      tts / podcastify render stage
  ANTHROPIC_API_KEY   podcastify summarize stage (claude/codex CLI, headless)
  SCHEPENS_API_TOKEN  publish-to-schepens

CLOUD / HEADLESS (e.g. a per-run container that clones the private repo):
  uvx --from git+ssh://git@github.com/<you>/podcast-creator tts script.md
"""


def get_secret(name: str) -> str | None:
    """Return secret `name` from the environment.

    Falls back to reading the file at `<name>_FILE` so secrets can be mounted as
    files (Docker/Kamal secrets) rather than passed as env vars that show up in
    the process environment / `docker inspect`.
    """
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    file_path = os.environ.get(f"{name}_FILE")
    if file_path:
        p = Path(file_path)
        if p.is_file():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                return content
    return None


def preflight(secrets: list[str] | None = None, binaries: list[str] | None = None) -> None:
    """Exit early with a clear message if required secrets/binaries are missing.

    Prints only the NAMES of what's missing -- never secret values.
    """
    missing: list[str] = []
    for name in secrets or []:
        if not get_secret(name):
            missing.append(f"{name}  (set env {name} or {name}_FILE=<path>)")
    for binary in binaries or []:
        if shutil.which(binary) is None:
            missing.append(f"{binary}  (not found on PATH)")
    if missing:
        print("[preflight] missing required configuration:", file=sys.stderr)
        for item in missing:
            print(f"  - {item}", file=sys.stderr)
        sys.exit(1)


def slugify(text: str) -> str:
    """Filesystem-safe lowercase slug, e.g. 'The Title!' -> 'the-title'."""
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "episode"


_SMALL_WORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "for", "to", "of", "in",
    "on", "at", "by", "vs", "via",
}


def titleize(slug: str) -> str:
    """Best-effort human title from a slug/stem.

    'return-to-the-little-kingdom' -> 'Return to the Little Kingdom'
    """
    words = [w for w in re.split(r"[-_\s]+", slug.strip()) if w]
    out: list[str] = []
    for i, w in enumerate(words):
        if i != 0 and w.lower() in _SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out) or slug
