# A Linear Walkthrough of `tts.py`

> **Note (2026-07):** this walks through an earlier, simpler revision of
> `tts.py`. The current file additionally imports `pcommon` (secrets +
> preflight), embeds ID3 metadata via `--title`/`--description`/`--date`,
> and skips re-rendering when the MP3 is newer than the script (`--force`
> to override). The core logic explained here — chunk splitting,
> `render_chunk`, `concat_mp3s`, and the overall control flow — is still
> accurate. Kept as a Python teaching doc, not as a spec.

This is a top-to-bottom tour of `tts.py`, a small command-line script that turns a text file into an MP3 by calling OpenAI's `gpt-4o-mini-tts` model. It assumes you already program but haven't spent much time in Python.

We'll walk through the file in the order it appears.

---

## 1. The shebang and module docstring

```python
#!/usr/bin/env python3
"""Render a text script to an MP3 using OpenAI's gpt-4o-mini-tts.

Usage:
    python tts.py input/episode01.txt
    ...
"""
```

- **`#!/usr/bin/env python3`** — the "shebang." If you mark the file executable (`chmod +x tts.py`) and run `./tts.py`, the OS uses this line to find the interpreter. Otherwise it's just a comment.
- **The triple-quoted string** at the top of the file is the **module docstring**. Python keeps it accessible at runtime as `__doc__`. Later, the script feeds `__doc__` straight into `argparse` so `--help` prints this same usage block. Triple quotes (`"""..."""`) are how Python writes multi-line strings.

---

## 2. Imports

```python
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from openai import OpenAI
```

- **`from __future__ import annotations`** — a forward-compatibility switch. It tells Python to treat all type hints as plain strings (evaluated lazily). Practically, this lets the file write `list[str]` instead of `List[str]` even on older Python versions, and it avoids import-order issues with type hints.
- **`import argparse`** — standard-library command-line parser. Builds the `--voice`, `-o`, `--help`, etc. flags.
- **`import re`** — regular expressions, used here to split text on blank lines and on sentence boundaries.
- **`import subprocess`** — runs external programs. Used to shell out to `ffmpeg`.
- **`import sys`** — interpreter-level stuff. Used for `sys.stderr` (printing errors) and `sys.exit` (returning an exit code).
- **`import tempfile`** — creates throwaway files and directories that auto-clean.
- **`from pathlib import Path`** — modern object-oriented file paths. `Path("a") / "b"` joins paths; `p.read_text()` reads a file. Replaces older string-based `os.path` code.
- **`from openai import OpenAI`** — third-party SDK. `OpenAI` is the client class.

The `from X import Y` form pulls a single name out of a module; plain `import X` brings the whole module in under its name.

---

## 3. Module-level constants

```python
MODEL = "gpt-4o-mini-tts"
CHUNK_LIMIT = 4000  # leave a little headroom under the 4096 ceiling

DEFAULT_VOICE = "ash"
DEFAULT_INSTRUCTIONS = (
    "Warm, conversational podcast host. Natural pacing with light pauses "
    "between ideas. Slightly amused, thoughtful — not performative. Slow "
    "down on technical terms."
)
```

Python doesn't have a `const` keyword. The convention is: **uppercase names are constants by social agreement** — nothing prevents reassignment.

The parentheses around `DEFAULT_INSTRUCTIONS` aren't a tuple; they group adjacent string literals. **Adjacent string literals in Python are automatically concatenated at parse time**, so those three lines become one string. It's a tidy way to wrap long literals without `\n` showing up in the output.

---

## 4. `split_into_chunks` — fitting text under the API limit

```python
def split_into_chunks(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
```

- **`def`** declares a function.
- **`text: str`** and **`limit: int = CHUNK_LIMIT`** are type-hinted parameters. Hints are not enforced at runtime — they're for readers and tools (mypy, editors). `= CHUNK_LIMIT` makes `limit` optional with a default.
- **`-> list[str]`** is the return-type hint: a list of strings.

```python
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
```

This single line does a lot:

- **`re.split(r"\n\s*\n", text)`** — splits the input on any blank line (a newline, optional whitespace, another newline). The `r"..."` is a **raw string**, so `\n` is passed verbatim to the regex engine instead of being interpreted by Python first.
- **`[ ... for p in ... if ... ]`** is a **list comprehension** — Python's compact `map`+`filter`. Read it as: "for each `p` in the split result, if `p.strip()` is truthy, include `p.strip()`." `strip()` removes leading/trailing whitespace. Empty strings are falsy, so the `if p.strip()` clause discards them.

```python
    chunks: list[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf.strip())
            buf = ""
```

- `chunks` and `buf` are the accumulator state.
- **`def flush()` defined inside another function** is a **nested (closure) function**. It can read variables from the enclosing scope.
- **`nonlocal buf`** is the key bit: without it, assigning to `buf` inside `flush` would create a *new local* `buf` and leave the outer one alone. `nonlocal` says "I mean the `buf` in the enclosing function." (`global` would mean the module level.)
- `if buf:` — empty strings are falsy in Python, so this means "if `buf` has content."

```python
    for para in paragraphs:
        if len(para) > limit:
            flush()
            sentences = re.split(r"(?<=[.!?])\s+", para)
```

Outer loop: walk paragraph by paragraph.

- If a single paragraph is *itself* longer than the limit, flush whatever was being accumulated, then split that paragraph into sentences.
- The regex `(?<=[.!?])\s+` is a **positive lookbehind**: split on whitespace, but only where the preceding character was `.`, `!`, or `?`. The lookbehind isn't consumed, so the punctuation stays attached to the previous sentence.

```python
            sbuf = ""
            for s in sentences:
                if len(s) > limit:
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
```

A second-level packer for sentences:

- If a single *sentence* is still oversized (rare but possible), it's hard-wrapped into fixed-size slices using **slicing**: `s[i : i + limit]` returns the substring from index `i` up to (but not including) `i + limit`. **`range(0, len(s), limit)`** generates `0, limit, 2*limit, ...` up to but not past `len(s)`.
- Otherwise, sentences are greedily packed into `sbuf` until adding the next one would overflow.
- **`f"{sbuf} {s}"`** is an **f-string** (formatted string literal). Anything in `{...}` is evaluated and inserted. It's Python's preferred string interpolation since 3.6.
- **`continue`** skips the rest of the outer loop iteration and moves on to the next paragraph.

```python
        if len(buf) + len(para) + 2 > limit:
            flush()
            buf = para
        else:
            buf = f"{buf}\n\n{para}".strip()

    flush()
    return chunks
```

The "normal-sized paragraph" branch: pack paragraphs into `buf`, separated by blank lines (`\n\n`), flushing whenever a new one would push us past `limit`. After the loop, one final `flush()` empties any leftover, and the function returns the assembled list.

---

## 5. `render_chunk` — calling the TTS API

```python
def render_chunk(client: OpenAI, text: str, out_path: Path, voice: str, instructions: str) -> None:
    with client.audio.speech.with_streaming_response.create(
        model=MODEL,
        voice=voice,
        input=text,
        instructions=instructions,
        response_format="mp3",
    ) as response:
        response.stream_to_file(out_path)
```

- **`-> None`** — the function returns nothing meaningful.
- **`with ... as response:`** is a **context manager**. The OpenAI SDK opens a streaming HTTP response; the `with` block guarantees it gets cleaned up (closed) when the block exits, even on error. Same idea as `try/finally` but compact.
- The named arguments (`model=`, `voice=`, etc.) are **keyword arguments**. Python lets you pass them by name in any order.
- `response.stream_to_file(out_path)` writes the streamed MP3 bytes straight to disk — no need to buffer the whole thing in memory.

---

## 6. `concat_mp3s` — stitching parts together with ffmpeg

```python
def concat_mp3s(parts: list[Path], out_path: Path) -> None:
    """Concatenate MP3 files losslessly with ffmpeg's concat demuxer."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        listfile = Path(f.name)
        for p in parts:
            f.write(f"file '{p.resolve()}'\n")
```

ffmpeg's "concat demuxer" needs a manifest file listing the inputs, one per line, in a specific format:

```
file '/abs/path/part_001.mp3'
file '/abs/path/part_002.mp3'
```

- `tempfile.NamedTemporaryFile("w", ...)` opens a temp file in write-text mode.
- **`delete=False`** — by default the temp file is deleted as soon as the `with` block exits. We want it to outlive the block (ffmpeg needs to read it next), so we disable that and clean up manually below.
- `p.resolve()` converts each path to an absolute path. The single quotes around `{p.resolve()}` are required by ffmpeg's manifest syntax.

```python
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-c", "copy",
                str(out_path),
            ],
            check=True,
        )
    finally:
        listfile.unlink(missing_ok=True)
```

- **`subprocess.run([...], check=True)`** runs `ffmpeg` as a child process. Passing the command as a **list of strings** (rather than one big string) avoids any shell escaping/injection concerns. `check=True` raises an exception if ffmpeg exits non-zero.
- The ffmpeg flags: `-y` overwrites the output, `-hide_banner` and `-loglevel error` quiet the noise, `-f concat -safe 0 -i listfile` invokes the concat demuxer, and `-c copy` says "don't re-encode, just copy the audio streams" — that's why this is lossless and fast.
- **`try/finally`** guarantees the manifest is deleted even if ffmpeg raises. **`unlink(missing_ok=True)`** is `pathlib`'s name for "delete the file"; the flag means "no error if it's already gone."

---

## 7. `main` — argument parsing and the orchestration

```python
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", type=Path, help="Path to the input .txt script")
    ap.add_argument("-o", "--output", type=Path, help="Output mp3 path (default: output/<script-stem>.mp3)")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help=f"Voice name (default: {DEFAULT_VOICE})")
    ap.add_argument("--instructions", default=DEFAULT_INSTRUCTIONS, help="Steering instructions for tone/pacing")
    ap.add_argument("--instructions-file", type=Path, help="Read instructions from a file (overrides --instructions)")
    args = ap.parse_args()
```

- `__doc__` is the module docstring from the top of the file — argparse will print it as the description for `--help`. `RawDescriptionHelpFormatter` keeps your line breaks instead of reflowing them.
- Each `add_argument` call defines one CLI flag/positional. **`type=Path`** tells argparse to feed the raw string into `Path(...)` before storing.
- After `parse_args()`, `args` is an object with attributes named after the flags (`args.script`, `args.voice`, etc.). Argparse converts hyphens to underscores: `--instructions-file` → `args.instructions_file`.

```python
    if not args.script.exists():
        print(f"error: script not found: {args.script}", file=sys.stderr)
        return 1
```

Standard "fail fast" check. **`file=sys.stderr`** routes the print to stderr so it doesn't pollute stdout. Returning `1` from `main()` becomes the process exit code (any non-zero means failure).

```python
    instructions = args.instructions_file.read_text().strip() if args.instructions_file else args.instructions
```

A **conditional expression** (Python's ternary): `A if cond else B`. If the user passed `--instructions-file`, read it from disk; otherwise use the inline `--instructions` value (or its default).

```python
    text = args.script.read_text().strip()
    if not text:
        print("error: script is empty", file=sys.stderr)
        return 1

    out_path = args.output or Path("output") / f"{args.script.stem}.mp3"
    out_path.parent.mkdir(parents=True, exist_ok=True)
```

- **`A or B`** in Python returns `A` if truthy, otherwise `B` — a common idiom for "use the explicit value, else fall back." If `--output` wasn't passed, `args.output` is `None` (falsy), so we use `output/<stem>.mp3`. `args.script.stem` is the filename without extension (`episode01.txt` → `episode01`).
- **`/`** is overloaded by `pathlib` to mean "join paths" — it's not division here.
- **`mkdir(parents=True, exist_ok=True)`** is the equivalent of `mkdir -p`: create intermediate directories if needed, don't error if it already exists.

```python
    chunks = split_into_chunks(text)
    print(f"script: {args.script}  ({len(text):,} chars -> {len(chunks)} chunk(s))")
    print(f"voice:  {args.voice}")
    print(f"output: {out_path}")

    client = OpenAI()
```

- `{len(text):,}` — the **`:,` format spec** inserts thousands separators (`12345` → `12,345`).
- `OpenAI()` constructs the API client. With no arguments, it picks up `OPENAI_API_KEY` from the environment.

```python
    if len(chunks) == 1:
        render_chunk(client, chunks[0], out_path, args.voice, instructions)
        print("done.")
        return 0
```

Fast path: one chunk, one API call, write directly to the final output. No ffmpeg, no temp dir.

```python
    with tempfile.TemporaryDirectory() as tmp:
        parts: list[Path] = []
        for i, chunk in enumerate(chunks, 1):
            part = Path(tmp) / f"part_{i:03d}.mp3"
            print(f"  [{i}/{len(chunks)}] rendering {len(chunk):,} chars...")
            render_chunk(client, chunk, part, args.voice, instructions)
            parts.append(part)
        print("  concatenating...")
        concat_mp3s(parts, out_path)

    print("done.")
    return 0
```

Multi-chunk path:

- **`tempfile.TemporaryDirectory()`** as a context manager creates a fresh directory and recursively wipes it when the block exits — a clean way to handle scratch files.
- **`enumerate(chunks, 1)`** yields `(1, chunks[0]), (2, chunks[1]), ...`. In `for i, chunk in ...`, Python unpacks each pair so `i` is the counter and `chunk` is the actual string item. The second arg sets the start index; default is 0.
- **`f"part_{i:03d}.mp3"`** — the format spec `:03d` means "integer, zero-padded, width 3" → `part_001.mp3`, `part_002.mp3`. Helps the files sort correctly.
- After all chunks render, hand the list to `concat_mp3s`, then exit cleanly with `0`.

---

## 8. The script entrypoint

```python
if __name__ == "__main__":
    sys.exit(main())
```

A Python idiom every script uses. When the file is **run directly**, the interpreter sets the special variable `__name__` to `"__main__"`. When the file is **imported as a module**, `__name__` is set to the module's name (`"tts"`). So this guard means: "only run the CLI when the user actually runs this file; if someone imports it, just expose the functions and don't execute anything."

`sys.exit(main())` runs `main()` and uses its return value as the process exit code.

---

## TL;DR control flow

1. Parse CLI args.
2. Read the script file; bail if missing or empty.
3. Resolve the output path (default: `output/<stem>.mp3`).
4. Split the text into chunks ≤ 4000 chars on paragraph and sentence boundaries.
5. For each chunk, call the OpenAI TTS API and stream the MP3 bytes to disk.
6. If there were multiple chunks, concatenate them losslessly with `ffmpeg -c copy`.
7. Exit with status 0.
