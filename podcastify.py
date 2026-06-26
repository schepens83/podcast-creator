#!/usr/bin/env python3
"""podcastify -- orchestrate the full podcast-creator chain.

Three stages, each idempotent and independently runnable:
  1. summarize : source file (epub/pdf/md) -> spoken-monologue script.md  (claude/codex + bundled skills)
  2. render    : script.md                 -> episode.mp3                 (tts)
  3. publish   : episode.mp3               -> schepens.cc/podcast         (publish-to-schepens)

Writes <slug>.md and <slug>.mp3 to the current working directory. Re-running
skips stages whose output already exists (use --force to redo). Run a subset of
stages with --from / --to, e.g. `podcastify book.epub --to script`.

Run from anywhere.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from pcommon import CHAIN_HELP, preflight, slugify, titleize

DEFAULT_CLAUDE_MODEL = "sonnet"
DEFAULT_CODEX_MODEL = "gpt-5.5"

# Skills are bundled in this repo (skills/<name>/SKILL.md) and inlined into the
# prompt at runtime, so the pipeline does NOT depend on any skill being
# installed in ~/.claude, ~/.codex, or the launch directory.
SKILLS_DIR = Path(__file__).resolve().parent / "skills"

# Stage ordering. Index = how far along the pipeline a stage is.
SUMMARIZE, RENDER, PUBLISH = 0, 1, 2
FROM_POINTS = {"source": SUMMARIZE, "script": RENDER, "mp3": PUBLISH}
TO_POINTS = {"script": SUMMARIZE, "mp3": RENDER, "publish": PUBLISH}


def derive_description(script_path: Path) -> str | None:
    """First sentence of the script -> a one-line episode description."""
    if not script_path.exists():
        return None
    text = script_path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    return first[:300] or None


def load_skill(name: str) -> str:
    """Read a bundled skill's SKILL.md body (frontmatter stripped)."""
    text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
    # Strip a leading YAML frontmatter block (--- ... ---) if present.
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.strip()


def build_prompt(src: Path, out_md: Path) -> str:
    # Inline the bundled skills so the subprocess needs nothing installed.
    summarize_book = load_skill("summarize-book")
    podcast_summary = load_skill("podcast-summary")
    return f"""Produce a spoken-monologue podcast script from the source file at:
  {src}

Follow the two skill documents below, in order. They are inlined here in
full — do NOT look for, or rely on, any installed skill of the same name.

First, follow the SUMMARIZE-BOOK instructions to turn the source into a
SUMMARY.md. Pre-answer its interactive prompts with these defaults — do NOT
ask the user:
  - Summary depth: comprehensive
  - Flashcards per chapter: skip (none)
  - Parallel processing: yes

Then, follow the PODCAST-SUMMARY instructions to rewrite that SUMMARY.md into
the final spoken script.

================ SUMMARIZE-BOOK ================
{summarize_book}

================ PODCAST-SUMMARY ================
{podcast_summary}
===============================================

Write the final spoken script to exactly this path, and nothing else:
  {out_md}

Output ONLY the file. No commentary in your reply."""


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def build_llm_command(provider: str, prompt: str, src: Path, out_md: Path, model: str | None) -> list[str]:
    if provider == "claude":
        cmd = [
            "claude", "-p",
            "--dangerously-skip-permissions",
            "--verbose",
        ]
        if model:
            cmd.extend(["--model", model])
        cmd.append(prompt)
        return cmd

    if provider == "codex":
        cmd = [
            "codex", "exec",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            "-C", str(Path.cwd()),
        ]
        if src.parent != Path.cwd():
            cmd.extend(["--add-dir", str(src.parent)])
        if out_md.parent != Path.cwd() and out_md.parent != src.parent:
            cmd.extend(["--add-dir", str(out_md.parent)])
        if model:
            cmd.extend(["-m", model])
        cmd.append(prompt)
        return cmd

    raise ValueError(f"unsupported provider: {provider}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog=CHAIN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("source", type=Path, help="EPUB, PDF, .md, or .txt (only needed when summarizing)")
    ap.add_argument("title", nargs="?", help="Optional title (defaults to source filename stem)")
    ap.add_argument("--podcast", default="books", choices=["books", "youtube"], help="Feed to publish to (default: books)")
    ap.add_argument("--llm", choices=["claude", "codex"], default="claude", help="LLM CLI for the summarize step")
    ap.add_argument("--model", help="Model override for the selected LLM CLI")
    ap.add_argument("--description", help="Episode description (default: derived from the script)")
    ap.add_argument("--from", dest="from_point", choices=["auto", *FROM_POINTS], default="auto",
                    help="Stage to start at (auto resumes from the furthest existing artifact)")
    ap.add_argument("--to", dest="to_point", choices=list(TO_POINTS), default="publish",
                    help="Stage to stop after (default: publish)")
    ap.add_argument("--skip-upload", action="store_true", help="Alias for --to mp3 (render but don't publish)")
    ap.add_argument("--force", action="store_true", help="Redo stages even if their output already exists")
    args = ap.parse_args()

    # Title/slug drive the artifact filenames. Source need only exist if we summarize.
    title = args.title or titleize(args.source.stem)
    slug = slugify(title)
    cwd = Path.cwd()
    input_md = cwd / f"{slug}.md"
    output_mp3 = cwd / f"{slug}.mp3"

    end = RENDER if args.skip_upload else TO_POINTS[args.to_point]

    if args.from_point == "auto":
        if args.force:
            start = SUMMARIZE
        elif output_mp3.exists():
            start = PUBLISH
        elif input_md.exists():
            start = RENDER
        else:
            start = SUMMARIZE
    else:
        start = FROM_POINTS[args.from_point]

    if start > end:
        print(f"Nothing to do: requested stages [{start}..{end}] already satisfied "
              f"(script: {input_md.exists()}, mp3: {output_mp3.exists()}). Use --force to redo.")
        return 0

    description = args.description or derive_description(input_md)

    # Preflight only what the stages we'll actually run require.
    if start <= SUMMARIZE <= end:
        preflight(binaries=[args.llm], secrets=(["ANTHROPIC_API_KEY"] if args.llm == "claude" else None))
    if start <= RENDER <= end:
        preflight(secrets=["OPENAI_API_KEY"], binaries=["ffmpeg"])
    if start <= PUBLISH <= end:
        preflight(secrets=["SCHEPENS_API_TOKEN"])

    # --- Stage 1: summarize -------------------------------------------------
    if start <= SUMMARIZE <= end:
        src = args.source.resolve()
        if not src.exists():
            print(f"[error] source not found: {src}", file=sys.stderr)
            return 1
        model = args.model or (DEFAULT_CLAUDE_MODEL if args.llm == "claude" else DEFAULT_CODEX_MODEL)
        print("[1/3] summarize -> spoken monologue")
        print(f"      src:   {src}")
        print(f"      out:   {input_md}")
        print(f"      llm:   {args.llm}  model: {model}")
        run(build_llm_command(args.llm, build_prompt(src, input_md), src, input_md, model))
        if not input_md.exists() or input_md.stat().st_size == 0:
            print(f"[error] expected {input_md} to exist and be non-empty", file=sys.stderr)
            return 1
        description = args.description or derive_description(input_md)

    # --- Stage 2: render ----------------------------------------------------
    if start <= RENDER <= end:
        if not input_md.exists():
            print(f"[error] script not found: {input_md} (run the summarize stage first)", file=sys.stderr)
            return 1
        print(f"[2/3] render mp3 -> {output_mp3}")
        cmd = ["tts", str(input_md), "-o", str(output_mp3), "--title", title]
        if description:
            cmd += ["--description", description]
        if args.force:
            cmd += ["--force"]
        run(cmd)

    # --- Stage 3: publish ---------------------------------------------------
    if start <= PUBLISH <= end:
        if not output_mp3.exists():
            print(f"[error] mp3 not found: {output_mp3} (run the render stage first)", file=sys.stderr)
            return 1
        print(f"[3/3] publish -> schepens.cc ({args.podcast} feed)")
        cmd = ["publish-to-schepens", args.podcast, str(output_mp3), "--title", title]
        if description:
            cmd += ["--description", description]
        run(cmd)
        print(f"\nDone: {output_mp3}")
        print("Live at: https://schepens.cc/podcast/episodes")
        return 0

    print(f"\nDone (stopped at --to {args.to_point}).")
    if end >= RENDER:
        print(f"MP3: {output_mp3}")
    else:
        print(f"Script: {input_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
