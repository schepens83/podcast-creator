#!/usr/bin/env python3
"""tts -- stage 2 of the podcast-creator chain: render a script to an MP3.

Renders a markdown/text script to an MP3 using OpenAI's gpt-4o-mini-tts. The
input is a spoken-monologue script (produced by podcastify's summarize stage /
the podcast-summary skill); the output mp3 is consumed by publish-to-schepens.

Usage:
    tts script.md
    tts script.md --voice ash --instructions "Thoughtful, slow."
    tts script.md -o output/my_name.mp3
    tts script.md --title "Return to the Little Kingdom" --description "Apple's founding."

Reads OPENAI_API_KEY from the environment (or OPENAI_API_KEY_FILE). Splits long
scripts on paragraph (then sentence) boundaries to stay under the 4096-character
per-request limit, renders each chunk, and concatenates with ffmpeg. Any
--title/--description/--date is embedded as ID3 tags, which the podcast server
reads automatically.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from openai import OpenAI

from pcommon import CHAIN_HELP, get_secret, preflight

MODEL = "gpt-4o-mini-tts"
CHUNK_LIMIT = 4000  # leave a little headroom under the 4096 ceiling

DEFAULT_VOICE = "ash"
DEFAULT_INSTRUCTIONS = (
    "Warm, conversational podcast host. Natural pacing with light pauses "
    "between ideas. Slightly amused, thoughtful — not performative. Slow "
    "down on technical terms."
)


def split_into_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Greedily pack paragraphs into chunks <= limit chars.

    Falls back to sentence-splitting for any paragraph that exceeds the limit
    on its own.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf.strip())
            buf = ""

    for para in paragraphs:
        if len(para) > limit:
            flush()
            sentences = re.split(r"(?<=[.!?])\s+", para)
            sbuf = ""
            for s in sentences:
                if len(s) > limit:
                    # last resort: hard-wrap a single overlong sentence
                    if sbuf:
                        chunks.append(sbuf.strip())
                        sbuf = ""
                    for i in range(0, len(s), limit):
                        chunks.append(s[i : i + limit])
                    continue
                if len(sbuf) + len(s) + 1 > limit:
                    chunks.append(sbuf.strip())
                    sbuf = s
                else:
                    sbuf = f"{sbuf} {s}".strip()
            if sbuf:
                chunks.append(sbuf.strip())
            continue

        if len(buf) + len(para) + 2 > limit:
            flush()
            buf = para
        else:
            buf = f"{buf}\n\n{para}".strip()

    flush()
    return chunks


def render_chunk(client: OpenAI, text: str, out_path: Path, voice: str, instructions: str) -> None:
    with client.audio.speech.with_streaming_response.create(
        model=MODEL,
        voice=voice,
        input=text,
        instructions=instructions,
        response_format="mp3",
    ) as response:
        response.stream_to_file(out_path)


def metadata_args(title: str | None, description: str | None, date: str | None) -> list[str]:
    """ffmpeg -metadata flags. The podcast server reads title/comment/date via ffprobe."""
    args: list[str] = []
    if title:
        args += ["-metadata", f"title={title}"]
    if description:
        # 'comment' is the field the importer reads for description on mp3.
        args += ["-metadata", f"comment={description}"]
    if date:
        args += ["-metadata", f"date={date}"]
    return args


def concat_mp3s(parts: list[Path], out_path: Path, metadata: list[str] | None = None) -> None:
    """Concatenate MP3 files losslessly with ffmpeg's concat demuxer."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        listfile = Path(f.name)
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c", "copy",
                *(metadata or []),
                str(out_path),
            ],
            check=True,
        )
    finally:
        listfile.unlink(missing_ok=True)


def tag_mp3(in_path: Path, out_path: Path, metadata: list[str]) -> None:
    """Copy an mp3 to out_path, writing the given ID3 metadata (no re-encode)."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_path),
            "-c", "copy",
            *metadata,
            str(out_path),
        ],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog=CHAIN_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("script", type=Path, help="Path to the input script (.md/.txt)")
    ap.add_argument("-o", "--output", type=Path, help="Output mp3 path (default: output/<script-stem>.mp3)")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"Voice name (default: {DEFAULT_VOICE})")
    ap.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS, help="Steering instructions for tone/pacing")
    ap.add_argument("--instructions-file", type=Path, help="Read instructions from a file (overrides --instructions)")
    ap.add_argument("--title", help="Episode title -> embedded as an ID3 tag (the server reads it)")
    ap.add_argument("--description", help="Episode description -> embedded as an ID3 comment tag")
    ap.add_argument("--date", help="Episode date (e.g. 2026-06-26) -> embedded as an ID3 date tag")
    ap.add_argument("--force", action="store_true", help="Re-render even if the output is already up to date")
    args = ap.parse_args()

    if not args.script.exists():
        print(f"error: script not found: {args.script}", file=sys.stderr)
        return 1

    out_path = args.output or Path("output") / f"{args.script.stem}.mp3"

    # Idempotency: skip if the mp3 already exists and is newer than the script.
    if out_path.exists() and not args.force:
        if out_path.stat().st_mtime >= args.script.stat().st_mtime:
            print(f"skipping render: {out_path} is up to date (use --force to re-render)")
            return 0

    metadata = metadata_args(args.title, args.description, args.date)

    # Fail fast before doing any paid work. ffmpeg is needed for chunked scripts
    # and for ID3 tagging.
    preflight(secrets=["OPENAI_API_KEY"])

    instructions = args.instructions_file.read_text().strip() if args.instructions_file else args.instructions
    text = args.script.read_text().strip()
    if not text:
        print("error: script is empty", file=sys.stderr)
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = split_into_chunks(text)
    if len(chunks) > 1 or metadata:
        preflight(binaries=["ffmpeg"])

    print(f"script: {args.script}  ({len(text):,} chars -> {len(chunks)} chunk(s))")
    print(f"voice:  {args.voice}")
    print(f"output: {out_path}")

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    if len(chunks) == 1:
        if metadata:
            with tempfile.TemporaryDirectory() as tmp:
                raw = Path(tmp) / "raw.mp3"
                render_chunk(client, chunks[0], raw, args.voice, instructions)
                tag_mp3(raw, out_path, metadata)
        else:
            render_chunk(client, chunks[0], out_path, args.voice, instructions)
        print("done.")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        parts: list[Path] = []
        for i, chunk in enumerate(chunks, 1):
            part = Path(tmp) / f"part_{i:03d}.mp3"
            print(f"  [{i}/{len(chunks)}] rendering {len(chunk):,} chars...")
            render_chunk(client, chunk, part, args.voice, instructions)
            parts.append(part)
        print("  concatenating...")
        concat_mp3s(parts, out_path, metadata)

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
