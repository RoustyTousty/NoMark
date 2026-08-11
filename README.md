# NoMark — remove invisible Unicode watermarks, hidden characters, and document metadata

**Find and remove text watermarks, zero-width characters, hidden Unicode payloads, homoglyph fingerprints, and document metadata from `.txt`, `.md`, `.html`, `.docx`, `.xlsx`, `.pptx`, `.odt`, `.epub`, and `.pdf` files.**

A [Claude skill](https://docs.claude.com/en/docs/claude-code/skills) and a standalone Python CLI. Pure standard library — no dependencies except optional PDF rewriting. Works on Windows, macOS, and Linux.

[![tests](https://github.com/RoustyTousty/NoMark/actions/workflows/ci.yml/badge.svg)](https://github.com/RoustyTousty/NoMark/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python: 3.8+](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#requirements)

---

## Contents

- [What NoMark does](#what-nomark-does)
- [Quick start](#quick-start)
- [Install](#install)
- [How it works](#how-it-works)
- [Usage](#usage)
- [What it detects](#what-it-detects-full-list)
- [FAQ](#faq)
- [Limitations](#limitations-read-this)
- [Development](#development)

---

## What NoMark does

Text can carry information you cannot see.

Unicode contains characters that render as *nothing*. The tag block (`U+E0000`–`U+E007F`) is an exact invisible shadow of printable ASCII, so an entire hidden message fits inside an ordinary-looking sentence and survives copy-paste, reformatting, and email. Documents carry more: a `.docx` records the authoring application, the company name from the Office install, and a table of revision IDs that reconstructs which sentences were written in which editing session.

NoMark shows you exactly what is there, decodes it, then removes it.

```
$ nomark scan report.md

  [H] tag       UNICODE TAG (run)              x21   3:90, 3:91, 3:92, +18 more
  [H] invisible U+200B ZERO WIDTH SPACE        x2    3:37, 5:20
  [H] homoglyph U+0430 CYRILLIC SMALL LETTER A x1    5:6
            reads as 'a' inside the Latin word 'pаsswоrd'
  [!] hidden payload decoded: 'recipient=4471;copy=b'
```

That last line is the point. Most tools delete invisible characters silently. **NoMark decodes them first**, so you learn *what* was tracking the file and who it identified you as.

### Who this is for

- **Writers and researchers** publishing documents that should not carry an employer's name, a template path, or an editing timeline
- **Privacy-conscious users** sanitizing files before sharing them — the same job [`mat2`](https://0xacab.org/jvoisin/mat2) and [`exiftool`](https://exiftool.org/) do, extended to fingerprints those tools miss
- **Security engineers** checking untrusted input for [ASCII smuggling](#what-is-ascii-smuggling) and hidden prompt-injection payloads
- **Developers** stripping zero-width junk that breaks parsers, diffs, and search
- **Anyone editing AI-generated text** who wants it to read like a person wrote it

---

## Quick start

```bash
git clone https://github.com/RoustyTousty/NoMark.git
cd NoMark

# see what's hiding in a file
python skills/nomark/scripts/nomark.py scan yourfile.md

# clean it
python skills/nomark/scripts/nomark.py text yourfile.md --in-place --backup

# strip document metadata
python skills/nomark/scripts/nomark.py docs report.docx --in-place --backup
```

Try it on the included fixture, which carries every artifact class at once:

```bash
python examples/make_sample.py
python skills/nomark/scripts/nomark.py scan examples/watermarked_sample.md
```

---

## Install

### As a Claude skill

Copy the skill directory into your Claude skills folder:

```bash
# macOS / Linux
git clone https://github.com/RoustyTousty/NoMark.git
cp -r NoMark/skills/nomark ~/.claude/skills/nomark
```

```powershell
# Windows (PowerShell)
git clone https://github.com/RoustyTousty/NoMark.git
Copy-Item -Recurse NoMark\skills\nomark $env:USERPROFILE\.claude\skills\nomark
```

### As a Claude Code plugin

```
/plugin marketplace add RoustyTousty/NoMark
/plugin install nomark@nomark
```

Either way, Claude picks the skill up automatically. Just ask:

> Scan this file for hidden characters
> Strip the metadata from report.docx before I send it
> Is there anything invisible in this text someone pasted me?
> Clean this up and make it read less like AI wrote it

### As a standalone CLI

No install step. Clone and run — or copy `skills/nomark/scripts/` anywhere you like, since the scripts import nothing outside the standard library.

### Requirements

Python 3.8 or newer. That is the whole list.

PDF **rewriting** additionally needs `pip install pypdf`. PDF **inspection** works without it, as does everything else.

---

## How it works

Watermarks live in four independent layers. A file can be spotless at one layer and heavily marked at another, which is why NoMark works through all four instead of stopping at the first hit.

```
┌─ Layer 1 ── Invisible characters ─────────────── scripts/scan.py
│  Zero-width chars, U+E0000 tag block, variation
│  selectors, bidi overrides, soft hyphens         → decoded, then removed
│
├─ Layer 2 ── Confusable characters ────────────── scripts/clean_text.py
│  Cyrillic/Greek homoglyphs, no-break and narrow
│  spaces, typographic punctuation                 → folded to ASCII
│
├─ Layer 3 ── Document metadata ────────────────── scripts/clean_docs.py
│  Authors, tool versions, rsid revision IDs,
│  paragraph GUIDs, thumbnails, zip timestamps     → removed / normalized
│
└─ Layer 4 ── Writing style ────────────────────── references/style-tells.md
   Uniform sentence length, tricolons, symmetric
   hedging, abstraction                            → Claude rewrites
```

**Layers 1–3 are deterministic** and handled by scripts. **Layer 4 is judgment** and handled by Claude, guided by [style-tells.md](skills/nomark/references/style-tells.md). Trying to do layer 4 with a regex is the mistake every "AI humanizer" makes — see [the FAQ](#why-doesnt-nomark-just-replace-ai-words-like-delve).

### Design decisions worth knowing

**It never breaks real text.** Writing a cleaner that strips every non-ASCII character is easy and useless, because it destroys Russian, Greek, Persian, and every emoji. So:

- A zero-width joiner is **kept** between emoji (the family emoji is three people glued with ZWJ) and in Persian or Hindi, where it controls letter shaping. It is removed only between two Latin letters, where it cannot affect rendering.
- Homoglyphs are folded **only inside words that already mix scripts**. `passwоrd` with a Cyrillic `о` gets fixed; `Привет` is left alone.
- Bidi controls are stripped only when the document contains no right-to-left text at all.

**Three profiles, chosen by what you are cleaning:**

| Profile | Changes | Use for |
|---|---|---|
| `safe` | Invisible characters only. **Never alters a visible glyph.** | Source code, JSON, CSV, YAML — anything parsed |
| `standard` *(default)* | `safe` + space folding + mixed-script homoglyphs + plain punctuation | Prose |
| `aggressive` | `standard` + NFKC + whitespace collapsing + unconditional homoglyph folding | English text you want maximally normalized |

---

## Usage

The unified entry point dispatches everything:

```bash
nomark.py scan  FILE     # report only, change nothing
nomark.py text  FILE     # clean invisible + confusable characters
nomark.py docs  FILE     # strip document metadata
nomark.py check PATH     # CI gate: exit 1 if anything is found
```

### Scan

```bash
python skills/nomark/scripts/nomark.py scan FILE
python skills/nomark/scripts/nomark.py scan DIR --ext .md,.txt   # sweep a tree
python skills/nomark/scripts/nomark.py scan FILE --show-low      # + typographic tells
python skills/nomark/scripts/nomark.py scan FILE --json          # machine-readable
```

Exits non-zero when it finds something, so it works as a pre-commit hook or CI gate. Use `--exclude` (repeatable, glob, gitignore-style) to skip deliberate fixtures:

```yaml
- name: Fail if any hidden characters were committed
  run: |
    python skills/nomark/scripts/nomark.py check . \
      --exclude 'tests/*' --exclude 'fixtures'
```

A bare name like `fixtures` excludes a directory of that name at any depth; `tests/*` works whether the path is relative or absolute.

### Clean text

```bash
python skills/nomark/scripts/nomark.py text FILE                      # preview to stdout
python skills/nomark/scripts/nomark.py text FILE --in-place --backup  # rewrite, keep .bak
python skills/nomark/scripts/nomark.py text FILE --diff               # see what changes
python skills/nomark/scripts/nomark.py text DIR --ext .py --profile safe --in-place
cat file.txt | python skills/nomark/scripts/nomark.py text -          # stdin
```

`--diff` escapes non-ASCII, so invisible removals are actually visible. Without escaping, a diff of invisible-character removal is two identical-looking lines:

```diff
-It\u2019s worth noting that this document\u200b represents a comprehensive\xa0overview of our findings\U000e0072\U000e0065\U000e0063...
+It's worth noting that this document represents a comprehensive overview of our findings.
```

`--dash-style` controls em dash replacement: `hyphen` (default), `comma`, `semicolon`, `space`, `keep`. For prose, `comma` usually reads best.

### Clean documents

```bash
python skills/nomark/scripts/nomark.py docs FILE --inspect            # report only
python skills/nomark/scripts/nomark.py docs FILE --in-place --backup  # strip in place
python skills/nomark/scripts/nomark.py docs FILE -o clean.docx        # strip to a copy
python skills/nomark/scripts/nomark.py docs FILE -o out.docx --clean-text  # metadata + text
python skills/nomark/scripts/nomark.py docs papers/ --in-place        # whole folder
```

Real output on a `.docx`:

```
  - core.xml: removed dc:creator='Jane Doe'
  - core.xml: removed cp:lastModifiedBy='Jane Doe'
  - core.xml: dcterms:created: '2026-03-04T10:11:12Z' -> '1980-01-01T00:00:00Z'
  - app.xml: removed Application='Microsoft Office Word'
  - app.xml: removed Company='Acme Corp'
  - word/settings.xml: removed rsid table
  - word/settings.xml: removed 1 document GUID(s)
  - word/document.xml: removed 4 rsid attribute(s)
  - word/document.xml: removed 2 paragraph GUID(s)
  - word/document.xml: anonymised 1 authorship attribute(s)
  - removed word/people.xml (comment author registry)
  - rebuilt container with normalised timestamps and host OS
```

Note the parts most metadata tools miss — **rsid revision IDs** and **paragraph GUIDs**. Word stamps a Revision Save ID on every run it touches, so the rsid table reveals how many editing sessions produced a document and which sentences came from which one. Two files sharing an `rsidRoot` came from the same original. Paragraph GUIDs survive copying between documents.

On HTML, it also catches Word's "Save as Web Page" output:

```
  [M] local filesystem path leaked: 'file:///C:/Users/jdoe/AppData/Local/Temp/report_files/filelist.xml'
  [M] 1 Word conditional comment block(s) carrying document properties
```

That `file:///` path contains the author's **operating-system username**.

Document titles are kept by default (usually content, not identity); `--strip-all` drops them too.

---

## What it detects (full list)

### Invisible characters

Zero-width space, zero-width joiner/non-joiner, word joiner, invisible math operators, soft hyphen, combining grapheme joiner, Mongolian vowel separator, Hangul fillers, Khmer inherent vowels, byte-order mark, deprecated format characters, braille blank.

### Hidden payload channels

- **Unicode tag block** (`U+E0000`–`U+E007F`) — decoded to the ASCII it spells
- **Variation selectors** (`U+FE00`–`U+FE0F`, `U+E0100`–`U+E01EF`) — decoded as a UTF-8 byte stream
- **Bidi controls** including `U+202E`, the [Trojan Source](https://trojansource.codes/) trick that makes source code read differently to a human than to a compiler

### Confusables

Cyrillic, Greek, Armenian, and Cherokee homoglyphs; fifteen space characters that render like `U+0020`; line and paragraph separators; curly quotes, primes, ellipsis, en/em dashes, fraction slashes.

### Document metadata

| Format | Fields |
|---|---|
| `.docx` `.xlsx` `.pptx` | `dc:creator`, `cp:lastModifiedBy`, revision count, timestamps, `Application`, `AppVersion`, `Company`, `Template`, `TotalTime`, custom properties, **rsid tables**, **`w14:paraId` GUIDs**, document GUIDs, tracked-change authors, comment author registry, embedded thumbnails, zip timestamps, host-OS byte |
| `.odt` `.ods` `.odp` | `meta:generator` (pins OS and patch level), initial creator, editing cycles, editing duration, document statistics |
| `.pdf` | Info dictionary, XMP packet (`xmpMM:DocumentID`, edit history), `/ID` trailer |
| `.epub` | OPF creator, contributor, publisher, generator |
| `.html` | generator/author/ProgId meta tags, Word MSO conditional blocks, `file:///` paths, Office namespace tags |

Full detail: [unicode-watermarks.md](skills/nomark/references/unicode-watermarks.md) and [document-metadata.md](skills/nomark/references/document-metadata.md).

---

## FAQ

### What is ASCII smuggling?

Unicode's tag block maps one-to-one onto printable ASCII but renders as nothing. `U+E0041` is an invisible `A`. Appending a run of these to a sentence hides an arbitrary message in plain sight — it survives copy-paste and email, and nobody proofreads for characters they cannot see. It is used both for per-recipient watermarking and for smuggling prompt-injection instructions into text an LLM will read. `nomark scan` decodes it.

### How do I find zero-width characters in a file?

```bash
python skills/nomark/scripts/nomark.py scan yourfile.txt
```

You will get every occurrence with line and column numbers. `--json` gives structured output.

### Does this remove ChatGPT or Claude watermarks?

It removes every *artifact-based* marker: invisible characters, homoglyphs, metadata, and typographic tells. It **cannot** remove statistical watermarks like [SynthID-Text](https://deepmind.google/technologies/synthid/), which bias token sampling across a whole passage — there is no character to delete. Only substantive rewriting degrades those, and you cannot verify the result without the detector key. See [Limitations](#limitations-read-this).

### Why doesn't NoMark just replace AI words like "delve"?

Because that does not work. The signature of generated prose is **structural, not lexical**: sentences cluster around one length, every list has three items, every claim is hedged symmetrically, and abstractions never resolve into specifics. Swapping vocabulary leaves all of that intact. [style-tells.md](skills/nomark/references/style-tells.md) targets the structure instead, and Claude applies it as a rewrite. Word lists are a secondary pass at best.

### Will it corrupt my emoji or non-English text?

No. That constraint shapes the whole design — see [Design decisions](#design-decisions-worth-knowing). Emoji ZWJ sequences, Persian and Hindi shaping, and genuine Cyrillic/Greek text are all preserved. The test suite has cases for each.

### Is it safe to run on source code?

Use `--profile safe`, which is guaranteed never to change a visible glyph. It removes invisible characters and nothing else — including `U+202E`, the Trojan Source override.

### Does removing metadata make my file untraceable?

No, and be careful here. Google Docs version history, Word autosave, submission-platform logs, and email headers all live outside the file and are untouched by any local tool. If you already sent the original, cleaning your copy achieves nothing.

### Does it work offline?

Yes. Nothing here makes a network request.

---

## Limitations (read this)

Stated plainly, because tools in this space routinely overclaim.

- **Statistical watermarks cannot be stripped.** SynthID-Text and similar bias the token sampler across an entire passage. There is no character to remove, no scanner can point at it, and you cannot confirm removal without the detector key. NoMark never claims a file is "watermark-free" — only that the artifacts it found are gone.
- **AI detectors are unreliable in both directions**, with documented false positives on non-native English writing. A clean file guarantees nothing.
- **Re-saving undoes it.** Opening a cleaned `.docx` in Word repopulates the properties from your Office profile. Clean last, immediately before sending.
- **PDF signatures break** when the file is rewritten. That is inherent — the signature covers the bytes being changed.
- **Unaccepted tracked changes still contain deleted text.** NoMark anonymizes authorship; it does not accept revisions.
- **Cleaning is itself detectable.** All-epoch timestamps and a missing rsid table obviously indicate a scrubbed file.

Full detail: [limits.md](skills/nomark/references/limits.md).

### Scope

NoMark handles unsigned metadata and text-layer artifacts — information an author never chose to publish. It deliberately does **not** implement attacks on cryptographic content provenance (C2PA manifests and similar signed chains for images and video), which exist so people can verify a photograph is what it claims to be.

If you are subject to a disclosure rule — coursework, a client contract, a journal submission — cleaning a file does not change what you owe. That is your call, not this tool's, but it is worth saying once.

---

## Development

```bash
python -m unittest discover -s tests -v     # 77 tests, no dependencies, ~0.3s
python examples/make_sample.py              # build a watermarked fixture
```

CI runs the suite on Linux, macOS, and Windows across Python 3.8, 3.11, and 3.13. Windows is included deliberately: its consoles default to a legacy codepage that cannot encode the characters this tool reports.

```
skills/nomark/          the skill; this is what you install
  SKILL.md              the definition Claude loads
  scripts/
    nomark.py           unified CLI entry point
    nomark_lib.py       character tables, scanning, cleaning
    scan.py             detection
    clean_text.py       text cleaning
    clean_docs.py       document + HTML metadata
  references/           loaded on demand by Claude
    unicode-watermarks.md
    document-metadata.md
    style-tells.md
    limits.md
.claude-plugin/         plugin + marketplace manifests
tests/                  unittest suite
examples/               sample generator
```

Contributions welcome — new codepoints, formats, and metadata fields especially. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

---

<sub>**Keywords:** remove invisible characters · zero-width space remover · Unicode tag block decoder · ASCII smuggling detector · homoglyph detection · docx metadata remover · PDF metadata stripper · EXIF-style document sanitizer · rsid removal · Trojan Source detection · prompt injection scanner · AI text humanizer · Claude skill · Claude Code plugin · text watermark removal</sub>
