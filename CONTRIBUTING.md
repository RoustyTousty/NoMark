# Contributing

Contributions are welcome. The most valuable ones are usually small and
specific: a codepoint that should be handled, a metadata field that leaks, a
document format that is not covered yet.

## Ground rules

**The standard library is the dependency budget.** Everything except PDF
rewriting must run on a bare Python 3.8+ install. This is a tool people clone
and run once on a sensitive file; asking them to build an environment first
defeats the purpose. If a feature genuinely needs a third-party package, make it
optional and degrade to inspection-only without it, the way PDF support does.

**Every change needs a test.** `tests/test_nomark.py` runs in under a second
with no setup. New codepoint, new metadata field, new format — add a case.

**Never break real text.** This is the constraint that shapes most of the design.
It is easy to write a cleaner that strips every non-ASCII character; it is
useless, because it destroys Russian, Greek, Persian, and every emoji. Two rules
follow:

- The `safe` profile must never change a visible glyph.
- Context-sensitive characters need context-sensitive handling. See
  `_joiner_matters()` for why ZWJ cannot be stripped unconditionally, and
  `fold_homoglyphs()` for why homoglyph folding is word-scoped.

If you are adding a character to a table, ask what legitimate text uses it. If
the answer is "some", it belongs in a context-sensitive tier, not in
`ALWAYS_STRIP`.

## Adding a codepoint

1. Add it to the right table in `skills/nomark/scripts/nomark_lib.py`:
   - `ALWAYS_STRIP` — no legitimate role in prose, safe to delete anywhere
   - `CONTEXT_STRIP` — meaningful in some scripts, needs a neighbour check
   - `SPACE_MAP` / `LINE_MAP` — renders as whitespace
   - `HOMOGLYPHS` — visually identical to a Latin character
   - `TYPOGRAPHY` — visible, but marks the text as machine-produced
   - `SUSPICIOUS` — reported but not removed by default
2. Add a test showing it is handled and that a legitimate use survives.
3. Add a row to `skills/nomark/references/unicode-watermarks.md` with a one-line rationale.

## Adding a metadata field

1. Add it to the relevant constant in `skills/nomark/scripts/clean_docs.py`.
2. Extend `_minimal_docx()` in the tests so the fixture actually carries it,
   then assert both that it is removed and that visible content survives.
3. Document it in `skills/nomark/references/document-metadata.md`, including *what it reveals*
   — that is the part readers actually want.

## Layout

`skills/nomark/scripts/` holds `nomark_lib.py` (character tables and the
scan/clean core), three tool CLIs, and `nomark.py`, a thin dispatcher that
forwards to them. A new subcommand needs one entry in `COMMANDS`; the tool
scripts stay independently runnable.

## Adding a format

Implement two functions: inspection (report without modifying) and cleaning.
Wire them into `inspect()` and `clean()`. Zip-based formats can reuse
`_read_zip` / `_write_zip`; note that ODF and EPUB require `mimetype` to be the
first entry and uncompressed, which is why entry order is preserved.

## Style

Match the surrounding code. Comments explain *why* a decision was made,
especially where the obvious implementation is wrong — those comments are the
ones that stop someone "simplifying" a context check back into a bug.

## Out of scope

Attacks on cryptographic content provenance (C2PA manifests and similar signed
chains for images and video) will not be merged. See the scope note in
`skills/nomark/references/limits.md`.

Please also do not submit changes framed around defeating a specific detector or
platform. Codepoint and metadata coverage is the goal; a cat-and-mouse game with
one vendor is not.
