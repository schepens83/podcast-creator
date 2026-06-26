---
name: podcast-summary
description: Turn a book summary (a SUMMARY.md from the summarize-book skill, or any structured summary/markdown) into a single-host spoken podcast monologue — walking through the book chapter by chapter, in the author's spirit, rewritten for the ear rather than the page.
---

# Podcast Summary

Rewrite a book summary into a finished **spoken podcast script**: one host,
no second voice, walking the listener through the book chapter by chapter in
the author's spirit. The output is meant to be read aloud by a
text-to-speech voice (e.g. `gpt-4o-mini-tts`), so it must sound like speech,
not like a document being recited.

This is the back half of the podcast pipeline. The front half —
[[summarize-book]] — produces a `SUMMARY.md` with all chapter summaries
combined. This skill consumes that and emits the script.

## Usage

```
/podcast-summary <path-to-SUMMARY.md-or-summary-folder> [output.md]
```

Accepts:
- **A `SUMMARY.md` file** produced by the `summarize-book` skill (preferred).
- **A folder** containing `SUMMARY.md` — the skill reads `SUMMARY.md` inside it.
- **Any structured summary or markdown** with chapter/section headings.

If no output path is given, write `<source-stem>.md` next to the source.

## Workflow

### 1. Get the summary

If the input is a raw book (PDF, EPUB, chapter folder) rather than a summary,
run the [[summarize-book]] skill first with these defaults — do **not** stop
to ask:
- Summary depth: **comprehensive**
- Flashcards per chapter: **skip (none)**
- Parallel processing: **yes**

Then read the resulting `SUMMARY.md`.

If the input is already a `SUMMARY.md` (or other summary), just read it.

### 2. Rewrite into a spoken monologue

Walk through the book **chapter by chapter, in the author's spirit**. Use
natural spoken transitions between chapters — "Moving on to chapter four —",
"The next section is where the author…".

- Give each chapter its **own dedicated treatment**, roughly proportional to
  the chapter's importance and length.
- **Don't pad.** Don't be exhaustive about every example — pick the ones that
  land.
- **Total length should scale with the source**: roughly **ten percent of the
  original word count**.
- Open with a brief spoken intro that names the book and frames what the
  listener is about to hear; close with a short wrap. Keep both tight.

### 3. Apply the voice rules

Apply **all** of these to the final script:

- **Sentences short.** Average 12–18 words. Break long ones at natural breath
  points. Use em-dashes — like this — for pauses mid-thought.
- **Contractions everywhere** ("it's", "you're", "we'll", "that's").
- **Spell out numbers, dates, units, and symbols** the way a person says
  them: "twenty twenty-six" not "2026", "about seventy percent" not "~70%".
- **Expand acronyms on first use** unless obvious (API, URL are fine; RAG,
  MCP, TTS should be expanded once).
- **No bullet lists, no headings, no markdown.** Convert lists into prose with
  signposts: "Three things going on here. First… Second… And the third…"
- **No parentheticals or footnote-style asides.** Inline them or cut them.
- **No URLs, no code blocks, no inline code.** Describe instead ("their
  pricing page", "the slash-loop command").
- **Light signposting** so the listener doesn't get lost: "Here's the thing.",
  "Step back for a second.", "The punchline is —". Use sparingly.
- **Read it aloud in your head.** Rewrite anything you stumble on. No awkward
  consonant clusters, tongue-twisters, or ambiguous this/that references.
- **Preserve the source's tone.** If it's dry and wry, stay dry and wry.
  Don't make it peppy.

### 4. Write the file

Write the final spoken script to the output path and nothing else. No
headings, no markdown scaffolding, no commentary in your reply — just the
spoken prose, ready for text-to-speech.

## Output

A single markdown file containing only the spoken script — continuous prose,
chapter-by-chapter, no headings or list formatting. This file feeds directly
into a TTS step (`tts <script.md> -o <episode.mp3>`).

## Notes

- The script is **one host**, a monologue — not a two-person dialogue.
- "In the author's spirit" means carry the author's argument and voice, not
  impersonate them in the first person. Stay the narrator walking the listener
  through the book.
- Quality over completeness: a listener should finish understanding the book's
  spine and best examples, not every sub-point.
