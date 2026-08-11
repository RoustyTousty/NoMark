# Unicode watermarks

Every codepoint NoMark handles, what it is for, and why it is or is not safe to
remove. Source of truth is the tables at the top of `scripts/nomark_lib.py`.

## Why text can be watermarked at all

Unicode contains characters that render as nothing. A document can therefore
carry information that is invisible on screen, survives copy-paste, survives
reformatting, and survives being emailed. Two properties make this a watermark
rather than a curiosity:

- **It is per-copy.** Give each recipient a different invisible pattern and a
  leaked document identifies the leaker.
- **It is silent.** Nobody proofreads for characters they cannot see.

## Tier 1: always removed

No legitimate role in ordinary prose. Deleted in every profile including `safe`.

| Codepoint | Name | Notes |
|---|---|---|
| U+00AD | SOFT HYPHEN | Invisible unless a line breaks there |
| U+034F | COMBINING GRAPHEME JOINER | Almost never intentional |
| U+115F, U+1160 | HANGUL FILLERS | Render as blank |
| U+17B4, U+17B5 | KHMER VOWEL INHERENT | Invisible in practice |
| U+180E | MONGOLIAN VOWEL SEPARATOR | Reclassified as format char |
| U+200B | ZERO WIDTH SPACE | The classic marker |
| U+2060 | WORD JOINER | Zero-width, non-breaking |
| U+2061–U+2064 | INVISIBLE MATH OPERATORS | Only meaningful in MathML |
| U+206A–U+206F | DEPRECATED FORMAT CHARACTERS | Deprecated since Unicode 3 |
| U+3164 | HANGUL FILLER | Blank; famously used in usernames |
| U+FEFF | ZERO WIDTH NO-BREAK SPACE | BOM when leading, marker elsewhere |
| U+FFA0 | HALFWIDTH HANGUL FILLER | Blank |

## Tier 2: removed in context

**U+200C ZERO WIDTH NON-JOINER** and **U+200D ZERO WIDTH JOINER** do real work
in three places, so they are removed only when none apply:

- **Emoji sequences.** The family emoji is three people glued with ZWJ. Strip
  it and one glyph becomes three.
- **Non-Latin shaping.** Persian, Arabic, Hindi, and others use ZWNJ to control
  ligature formation. `می‌رود` and `میرود` are different words.
- **Combining marks.** Joiners interact with the marks around them.

`_joiner_matters()` decides this by inspecting both neighbours. Between two
Latin letters a joiner cannot affect rendering, so there it is stripped.

**Bidi controls** (U+061C, U+200E, U+200F, U+202A–U+202E, U+2066–U+2069) are
meaningful in genuinely bidirectional text. NoMark strips them only when the
document contains no RTL characters at all, where they are inert by definition.
U+202E RIGHT-TO-LEFT OVERRIDE is also the "Trojan Source" trick, which makes
source code read differently to a human than to a compiler.

## Tier 3: high-bandwidth channels

### Unicode Tags — U+E0000 to U+E007F

The single most important range here. U+E0020 through U+E007E are an exact
invisible shadow of printable ASCII: `U+E0041` is an invisible `A`. An arbitrary
message can be appended to any sentence and rendered as nothing at all.

Originally intended for language tags, deprecated, then partially revived for
flag emoji. Outside a flag sequence, a run of tag characters is a payload.

NoMark **decodes and reports** these before removing them, so the user learns
what was hidden rather than just that something was:

```
[!] hidden payload decoded: 'user=4471;doc=q3-draft'
```

This range is also the standard prompt-injection channel against LLMs: hidden
instructions ride invisibly in text a model reads. Scanning untrusted input for
tag characters is a defensive measure, not just a privacy one.

### Variation selectors — U+FE00–U+FE0F and U+E0100–U+E01EF

Together these address 0–255, so a run encodes an arbitrary byte stream and
therefore arbitrary UTF-8. Because selectors attach to a preceding base
character, an entire hidden message can trail a single emoji.

NoMark decodes runs as UTF-8 and reports them. A *lone* selector is ordinary
presentation markup (`❤️` is U+2764 U+FE0F), so only multi-byte runs are
reported as payloads, though all selectors are stripped.

## Confusable characters

### Spaces

Fifteen codepoints render like U+0020 but are not. Substituting a few into a
document is a durable per-copy fingerprint that survives retyping-by-eye.

U+00A0, U+1680, U+2000–U+200A, U+202F, U+205F, U+3000 → folded to U+0020.
U+2028 and U+2029 → folded to newline.

Folded in `standard` and above, left alone in `safe` because they are sometimes
load-bearing in fixed-width data.

### Homoglyphs

Cyrillic `о` (U+043E) and Latin `o` (U+006F) are visually identical in most
fonts. Swapping a handful encodes a fingerprint that survives reformatting,
retyping from sight, and screenshot-and-OCR.

The naive fix — replace every Cyrillic character with its Latin lookalike —
destroys genuine Russian and Greek text. NoMark instead folds only characters
inside words that *already mix scripts*:

- `passwоrd` (Latin word, one Cyrillic `о`) → folded, and flagged as high
  severity
- `Привет` (entirely Cyrillic) → untouched

`--profile aggressive` folds unconditionally. Correct for a document known to
be English, destructive otherwise.

## Typography

Not covert, but they mark text as machine-generated or word-processed rather
than typed. Folded in `standard` and above.

Curly quotes, prime marks, ellipsis, en dash, figure dash, non-breaking hyphen,
fraction slash, minus sign, `©`, `®`, `™` → ASCII equivalents.

**Em dash (U+2014)** is handled separately because it is the strongest current
typographic tell and the right replacement is sentence-dependent. Control it
with `--dash-style`; `comma` usually reads best in prose.

Removing every em dash is itself a signal — human writers use them. Prefer
varying them over eliminating them.

## What is deliberately not touched

- **Combining diacritics** in normal use — stripping breaks real words.
- **U+2800 BRAILLE PATTERN BLANK** — reported, but only removed in
  `aggressive`, since it is legitimate in braille documents.
- **Emoji and their modifiers** — content, not markup.
- **Anything in `safe` beyond the invisible tiers** — the guarantee of that
  profile is that no visible glyph changes, which is what makes it usable on
  code.
