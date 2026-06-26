---
name: summarize-book
description: Transform books (PDF or markdown chapters) into comprehensive summaries and Anki flashcards for spaced repetition learning.
---

# Summarize Book

Transform books into structured summaries and Anki flashcards optimized for long-term retention through spaced repetition.

## Usage

```
/summarize-book <pdf-path-or-folder>
```

Accepts:
- **PDF file**: Extracts and splits into chapters
- **Folder with chapters**: Uses existing chapter markdown files (named `book-title-chapter-##.md`)

## Output

Creates organized folder structure:
```
book-title/
├── PLAN.md                          # Progress tracking and approach
├── SUMMARY.md                       # All chapter summaries combined
├── book-title-chapter-01.md        # Chapter text
├── book-title-chapter-02.md
├── flashcards-chapter-01.csv       # Anki flashcards per chapter
├── flashcards-chapter-02.csv
└── ...
```

## Workflow

### Phase 1: Setup & Detection

1. **Identify input type**:
   - PDF → Extract text with `pdftotext -layout -nopgbrk`
   - Folder → Use existing chapter files

2. **Extract metadata**:
   - Book title (from filename or PDF)
   - Chapter count

3. **Split into chapters** (if PDF):
   - Detect chapter boundaries using patterns (CHAPTER 1, Chapter 1:, etc.)
   - Create individual `book-title-chapter-##.md` files
   - If auto-detection fails, prompt user to split manually

### Phase 2: Planning

1. **Create PLAN.md** with:
   - Book metadata
   - Summary format template
   - Chapter checklist (all `[ ]` initially)

2. **Create SUMMARY.md** skeleton

3. **Ask user preferences** (via interactive prompts):
   - Summary depth: brief / standard / comprehensive
   - Flashcards per chapter: auto / custom number
   - Parallel processing: yes / no (auto for 5+ chapters)

### Phase 3: Chapter Processing

For each chapter:

1. **Read chapter file**

2. **Generate structured summary**:

```markdown
## Chapter N: Title

### Core Concept
[1 paragraph: main thesis, why it matters, how it connects to book theme]

### Key Techniques & Concepts
- **Technique Name**:
  - What it is: Clear definition
  - Why it works: Psychological/practical reasoning
  - How to use it: Actionable steps

### Key Example
[1-2 paragraphs: most illustrative story demonstrating concepts]

### Additional Notes (Optional)
[Edge cases, caveats, interdependencies with other chapters, or context that doesn't fit above sections]
```

3. **Create flashcards**:
   - Invoke `/flashcards` skill on chapter summary
   - Generate 15-25 cards per chapter (mix of Basic and Cloze)
   - More for important chapters, less for unimportant
   - Tags: `book-title::Ch##` + concept/technique tags
   - Max answer length: 1-7 words
   - Save to `flashcards-chapter-##.csv`

4. **Update tracking**:
   - Append summary to SUMMARY.md
   - Mark chapter complete in PLAN.md: `[x]`

**Parallel processing** (5+ chapters):
- Launches subagents (one per chapter)
- Each processes independently
- Main agent aggregates results
- Significant speed improvement

### Phase 4: Finalization

1. **Verify completeness**: All chapters have summaries and flashcards

2. **Generate statistics**:
```
✓ Total chapters: 10
✓ Total summary words: 5,234
✓ Total flashcards: 203 (118 Basic, 85 Cloze)
✓ Average cards per chapter: 20.3
```

3. **Report file locations and next steps**

## Flashcard Format

Uses Anki CSV format with proper headers:

```csv
#notetype column:1
#separator:semicolon
Notetype;Field1;Field2;Tags
Basic;Question;Short answer (1-7 words);book-title::Ch01 concept::topic
Cloze;{{c1::Answer}} in context;;book-title::Ch01 technique::name
```

**Flashcard principles**:
- Atomic facts: One concept per card
- Short answers: 1-7 words maximum
- Progressive disclosure: Build understanding incrementally
- Hierarchical tags: `book-title::ChXX topic::subtopic`

**Card types**:
- Definitions and terminology
- Core concepts and principles
- "What/Why/How" questions
- Examples and applications
- Connections between ideas

## Integration with Ankify Skill

Invokes the `/ankify` skill to generate flashcards from chapter summaries:
```
/ankify <chapter-summary-text>
  --output-format anki-csv
  --max-answer 7
  --types basic,cloze
  --tags "book-title::Ch##"
```

The ankify skill creates Anki-compatible CSV files with semantic, hierarchical tagging for flexible deck organization and spaced repetition scheduling.

## Summary Quality Guidelines

**Comprehensive but Concise**:
- Capture all major ideas without verbosity
- Focus on actionable knowledge
- Preserve important examples

**Structured for Learning**:
- Clear hierarchy: concept → technique → application
- Progressive detail: overview first, specifics after
- Show relationships between ideas

**Retention-Optimized**:
- Memorable examples and stories
- Clear "why" explanations (not just "what")
- Practical "how" instructions
- Spaced repetition friendly

## Tips for Best Results

**For PDF Input**:
- Ensure PDF has clear chapter divisions
- Text-based PDFs work best (not scanned images)
- May need to manually verify chapter splits

**For Markdown Folder Input**:
- Name files consistently: `book-title-chapter-##.md`
- One chapter per file
- Include chapter titles in markdown headers

**Summary Depth**:
- Brief: Key points only
- Standard: Recommended balance
- Comprehensive: Detailed coverage

**Flashcard Volume**:
- Typical: 15-25 cards per chapter
- More for important chapters, less for unimportant
- Adjust based on complexity
- Quality over quantity

## Use Cases

- **Technical Books**: Programming, business, science
- **Non-Fiction**: Self-help, psychology, biography
- **Textbooks**: Academic material requiring retention
- **Professional Development**: Career, negotiation, leadership

## Limitations

- PDF extraction may struggle with complex layouts, images, or scanned documents
- Works best with prose-heavy content (not reference books or cookbooks)
- Chapter detection heuristics may need manual verification

## Advanced Options

Optional flags:
- `--summary-depth [brief|standard|comprehensive]` - Detail level (default: standard)
- `--flashcards-per-chapter N` - Target cards (default: auto)
- `--parallel` - Process chapters in parallel (default: auto-detect)
- `--tag-prefix "custom"` - Custom tag namespace (default: book title)
- `--no-flashcards` - Skip flashcard generation
- `--chapters 1,3,5` - Process specific chapters only (useful for re-summarizing chapters 1, 3, 5 without re-processing the entire book; results are merged into existing SUMMARY.md and flashcard files)

## Example Invocation

```bash
# Process a PDF book
/summarize-book ~/Documents/books/atomic-habits.pdf

# Process existing chapter files
/summarize-book ~/Documents/books/never-split-the-difference/

# The skill will:
# 1. Analyze the book structure
# 2. Create PLAN.md with approach
# 3. Generate summaries for each chapter
# 4. Create flashcards using /flashcards skill
# 5. Compile everything into SUMMARY.md
# 6. Report completion with statistics
```

## Technical Notes

**PDF Processing**:
- Uses `pdftotext` command (requires poppler-utils)
- Identifies chapters via heading patterns
- Preserves formatting in markdown output

**Parallel Processing**:
- Processes multiple chapters simultaneously using subagents
- Significantly faster for books with 5+ chapters
- Automatic fallback to sequential if needed

**Tag Hierarchy**:
- Format: `book-title::Ch##` for chapter
- Additional: `concept::name`, `technique::name`, `example::name`
- Enables flexible Anki deck organization
