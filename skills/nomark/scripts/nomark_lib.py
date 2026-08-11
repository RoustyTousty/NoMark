#!/usr/bin/env python3
"""
NoMark core library -- detection and removal of text-layer watermarks.

Pure standard library, no third-party imports at module scope. Python 3.8+.

Four independent concerns live here:

  1. Invisible characters   -- zero-width, tag block, variation selectors, bidi
  2. Confusable characters  -- exotic spaces, Cyrillic/Greek homoglyphs
  3. Typographic tells      -- em dashes, curly quotes, ellipsis
  4. Payload decoding       -- reveal what smuggled codepoints actually spell

Everything is offered as detection first and mutation second, because knowing
what was in a file is often more useful than silently rewriting it.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

__version__ = "0.1.0"

# --------------------------------------------------------------------------
# Character tables
# --------------------------------------------------------------------------

# Codepoints with no legitimate role in ordinary prose. Safe to delete
# unconditionally in any profile.
ALWAYS_STRIP: Dict[int, str] = {
    0x00AD: "SOFT HYPHEN",
    0x034F: "COMBINING GRAPHEME JOINER",
    0x115F: "HANGUL CHOSEONG FILLER",
    0x1160: "HANGUL JUNGSEONG FILLER",
    0x17B4: "KHMER VOWEL INHERENT AQ",
    0x17B5: "KHMER VOWEL INHERENT AA",
    0x180E: "MONGOLIAN VOWEL SEPARATOR",
    0x200B: "ZERO WIDTH SPACE",
    0x2060: "WORD JOINER",
    0x2061: "FUNCTION APPLICATION",
    0x2062: "INVISIBLE TIMES",
    0x2063: "INVISIBLE SEPARATOR",
    0x2064: "INVISIBLE PLUS",
    0x206A: "INHIBIT SYMMETRIC SWAPPING",
    0x206B: "ACTIVATE SYMMETRIC SWAPPING",
    0x206C: "INHIBIT ARABIC FORM SHAPING",
    0x206D: "ACTIVATE ARABIC FORM SHAPING",
    0x206E: "NATIONAL DIGIT SHAPES",
    0x206F: "NOMINAL DIGIT SHAPES",
    0x3164: "HANGUL FILLER",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE (BOM)",
    0xFFA0: "HALFWIDTH HANGUL FILLER",
}

# Joiners that are load-bearing inside emoji sequences and in Indic, Arabic,
# and Persian text. Deleting them there corrupts real content, so they are only
# removed when both neighbours are plain ASCII/Latin -- the only situation in
# which they carry no meaning and are therefore almost certainly a marker.
CONTEXT_STRIP: Dict[int, str] = {
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
}

# Directionality controls. Meaningful in genuinely bidirectional text; pure
# noise (or a smuggling channel) in a document with no RTL characters at all.
BIDI_CONTROLS: Dict[int, str] = {
    0x061C: "ARABIC LETTER MARK",
    0x200E: "LEFT-TO-RIGHT MARK",
    0x200F: "RIGHT-TO-LEFT MARK",
    0x202A: "LEFT-TO-RIGHT EMBEDDING",
    0x202B: "RIGHT-TO-LEFT EMBEDDING",
    0x202C: "POP DIRECTIONAL FORMATTING",
    0x202D: "LEFT-TO-RIGHT OVERRIDE",
    0x202E: "RIGHT-TO-LEFT OVERRIDE",
    0x2066: "LEFT-TO-RIGHT ISOLATE",
    0x2067: "RIGHT-TO-LEFT ISOLATE",
    0x2068: "FIRST STRONG ISOLATE",
    0x2069: "POP DIRECTIONAL ISOLATE",
}

# Unicode Tags block. U+E0020..U+E007E map 1:1 onto printable ASCII, which
# makes this the highest-bandwidth invisible channel in Unicode -- an entire
# hidden message can ride inside a single visible sentence.
TAGS_START, TAGS_END = 0xE0000, 0xE007F

# Variation selectors. VS1-16 and VS17-256 together address 0..255, so a byte
# stream (and therefore arbitrary UTF-8) can be hidden after any base glyph.
VS_BMP_START, VS_BMP_END = 0xFE00, 0xFE0F
VS_SUP_START, VS_SUP_END = 0xE0100, 0xE01EF

# Braille blank is a real character in braille documents but a common padding
# trick elsewhere, so it is reported rather than stripped by default.
SUSPICIOUS: Dict[int, str] = {
    0x2800: "BRAILLE PATTERN BLANK",
}

# Whitespace that renders like U+0020 but is not U+0020.
SPACE_MAP: Dict[int, str] = {
    0x00A0: "NO-BREAK SPACE",
    0x1680: "OGHAM SPACE MARK",
    0x2000: "EN QUAD",
    0x2001: "EM QUAD",
    0x2002: "EN SPACE",
    0x2003: "EM SPACE",
    0x2004: "THREE-PER-EM SPACE",
    0x2005: "FOUR-PER-EM SPACE",
    0x2006: "SIX-PER-EM SPACE",
    0x2007: "FIGURE SPACE",
    0x2008: "PUNCTUATION SPACE",
    0x2009: "THIN SPACE",
    0x200A: "HAIR SPACE",
    0x202F: "NARROW NO-BREAK SPACE",
    0x205F: "MEDIUM MATHEMATICAL SPACE",
    0x3000: "IDEOGRAPHIC SPACE",
}

# Line/paragraph separators that behave like newlines but survive most
# copy-paste normalisation, making them a durable positional marker.
LINE_MAP: Dict[int, str] = {
    0x2028: "LINE SEPARATOR",
    0x2029: "PARAGRAPH SEPARATOR",
}

# Non-Latin characters that are visually identical (or near-identical) to a
# Latin letter. Substituting a few of these into a document encodes a durable
# per-recipient fingerprint that survives reformatting and retyping-by-eye.
HOMOGLYPHS: Dict[str, str] = {
    # Cyrillic uppercase
    "А": "A", "В": "B", "Е": "E", "З": "3", "К": "K",
    "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
    "Ѕ": "S", "Ү": "Y", "Ӏ": "I",
    # Cyrillic lowercase
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m",
    "н": "h", "о": "o", "р": "p", "с": "c", "т": "t",
    "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s",
    "ӏ": "l", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    # Greek uppercase
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "Β": "B",
    # Greek lowercase
    "α": "a", "ο": "o", "ρ": "p", "υ": "u", "ν": "v",
    "χ": "x", "ι": "i", "κ": "k",
    # Armenian / Cherokee lookalikes
    "Օ": "O", "Տ": "S", "Ꭰ": "D", "Ꭺ": "L", "Ꮐ": "G",
    # Fullwidth Latin -- visually distinct but folds to ASCII under NFKC
    "Ａ": "A", "Ｂ": "B", "Ｃ": "C",
}

# Punctuation that reads as "produced by an LLM or a word processor" rather
# than typed by a person in a plain text field.
TYPOGRAPHY: Dict[str, str] = {
    "‘": "'",   # LEFT SINGLE QUOTATION MARK
    "’": "'",   # RIGHT SINGLE QUOTATION MARK
    "‚": "'",   # SINGLE LOW-9 QUOTATION MARK
    "‛": "'",   # SINGLE HIGH-REVERSED-9
    "“": '"',   # LEFT DOUBLE QUOTATION MARK
    "”": '"',   # RIGHT DOUBLE QUOTATION MARK
    "„": '"',   # DOUBLE LOW-9 QUOTATION MARK
    "‟": '"',   # DOUBLE HIGH-REVERSED-9
    "′": "'",   # PRIME
    "″": '"',   # DOUBLE PRIME
    "…": "...",  # HORIZONTAL ELLIPSIS
    "‐": "-",   # HYPHEN
    "‑": "-",   # NON-BREAKING HYPHEN
    "‒": "-",   # FIGURE DASH
    "–": "-",   # EN DASH
    "―": "-",   # HORIZONTAL BAR
    "⁄": "/",   # FRACTION SLASH
    "∕": "/",   # DIVISION SLASH
    "×": "x",   # MULTIPLICATION SIGN
    "−": "-",   # MINUS SIGN
    "©": "(c)",
    "®": "(R)",
    "™": "(TM)",
}

# Em dash is handled separately: it is the single strongest typographic tell in
# current LLM output, and the right replacement depends on the sentence.
EM_DASH = "—"
DASH_STYLES = {
    "hyphen": " - ",
    "comma": ", ",
    "semicolon": "; ",
    "space": " ",
    "keep": None,
}

RTL_RANGES = (
    (0x0590, 0x05FF),  # Hebrew
    (0x0600, 0x06FF),  # Arabic
    (0x0700, 0x074F),  # Syriac
    (0x0780, 0x07BF),  # Thaana
    (0x07C0, 0x08FF),  # NKo, Samaritan, Arabic Extended-A
    (0xFB1D, 0xFDFF),  # Hebrew/Arabic presentation forms
    # Stops at FEFC, the last Arabic ligature. FEFF is the BOM, not an Arabic
    # letter -- including it would make any file with a BOM look bidirectional
    # and so suppress every bidi-control finding in it.
    (0xFE70, 0xFEFC),  # Arabic presentation forms-B
)


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    """One suspicious thing found at one place in the text."""

    kind: str               # invisible | tag | varsel | bidi | space | homoglyph | typography | suspicious
    name: str               # human-readable character name
    codepoint: Optional[int]
    line: int
    col: int
    severity: str           # high | medium | low
    detail: str = ""

    @property
    def label(self) -> str:
        if self.codepoint is None:
            return self.name
        return "U+%04X %s" % (self.codepoint, self.name)


@dataclass
class Report:
    """Aggregate result of scanning or cleaning a unit of text."""

    findings: List[Finding] = field(default_factory=list)
    decoded_payloads: List[str] = field(default_factory=list)
    removed: int = 0
    replaced: int = 0

    def counts_by_kind(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return out

    @property
    def clean(self) -> bool:
        return not self.findings

    def extend(self, other: "Report") -> None:
        self.findings.extend(other.findings)
        self.decoded_payloads.extend(other.decoded_payloads)
        self.removed += other.removed
        self.replaced += other.replaced


# --------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------

def is_tag_char(cp: int) -> bool:
    return TAGS_START <= cp <= TAGS_END


def is_variation_selector(cp: int) -> bool:
    return (VS_BMP_START <= cp <= VS_BMP_END) or (VS_SUP_START <= cp <= VS_SUP_END)


def is_rtl_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in RTL_RANGES)


def has_rtl(text: str) -> bool:
    return any(is_rtl_char(c) for c in text)


def _script_of(ch: str) -> str:
    """Coarse script name for a letter, derived from its Unicode name."""
    if not ch.isalpha():
        return ""
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return ""
    for script in ("LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC"):
        if name.startswith(script):
            return script
    return "OTHER"


def _joiner_matters(ch: Optional[str]) -> bool:
    """True if a joiner next to `ch` is load-bearing rather than decorative.

    Joiners do real work in three places: emoji sequences (the family emoji is
    three people glued by ZWJ), non-Latin scripts that use them for shaping
    (Persian, Hindi, Arabic), and next to combining marks. Everywhere else --
    notably between two Latin letters -- they are invisible and inert.
    """
    if ch is None:
        return False  # a string boundary is not a joining context
    cp = ord(ch)
    # Emoji, dingbats, symbols, and emoji modifiers.
    if 0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF:
        return True
    if unicodedata.category(ch) in ("So", "Sk", "Mn", "Mc", "Me", "Cs"):
        return True
    # A letter from any script that is not Latin may rely on the joiner.
    if ch.isalpha() and _script_of(ch) not in ("LATIN", ""):
        return True
    return False


def _joiner_is_inert(prev_ch: Optional[str], next_ch: Optional[str]) -> bool:
    """True when a joiner between these neighbours cannot affect rendering."""
    return not (_joiner_matters(prev_ch) or _joiner_matters(next_ch))


# --------------------------------------------------------------------------
# Payload decoding
# --------------------------------------------------------------------------

def decode_tag_payload(text: str) -> List[str]:
    """Decode runs of Unicode tag characters back into the ASCII they spell.

    U+E0020..U+E007E are an exact shadow of printable ASCII, so a run of them
    is almost always a hidden message rather than incidental noise.
    """
    payloads: List[str] = []
    current: List[str] = []
    for ch in text:
        cp = ord(ch)
        if is_tag_char(cp):
            if 0xE0020 <= cp <= 0xE007E:
                current.append(chr(cp - 0xE0000))
            # U+E0001 (language tag) and U+E007F (cancel) are delimiters
            elif current:
                payloads.append("".join(current))
                current = []
        elif current:
            payloads.append("".join(current))
            current = []
    if current:
        payloads.append("".join(current))
    return [p for p in payloads if p.strip()]


def decode_variation_payload(text: str) -> List[str]:
    """Decode variation-selector runs as a byte stream, then as UTF-8.

    VS1-16 encode bytes 0x00-0x0F and VS17-256 encode 0x10-0xFF, so a run of
    selectors after a single base character can carry arbitrary text.
    """
    payloads: List[str] = []
    current: List[int] = []

    def flush() -> None:
        if not current:
            return
        try:
            decoded = bytes(current).decode("utf-8")
        except UnicodeDecodeError:
            decoded = bytes(current).decode("latin-1", errors="replace")
        if decoded.strip():
            payloads.append(decoded)

    for ch in text:
        cp = ord(ch)
        if VS_BMP_START <= cp <= VS_BMP_END:
            current.append(cp - VS_BMP_START)
        elif VS_SUP_START <= cp <= VS_SUP_END:
            current.append(cp - VS_SUP_START + 16)
        else:
            flush()
            current = []
    flush()
    # A lone selector after an emoji is normal presentation markup, not a
    # payload; only multi-byte runs are worth reporting.
    return [p for p in payloads if len(p) > 1]


# --------------------------------------------------------------------------
# Scanning
# --------------------------------------------------------------------------

def scan_text(text: str) -> Report:
    """Find every watermark-shaped artefact in `text` without modifying it."""
    report = Report()
    doc_has_rtl = has_rtl(text)
    line, col = 1, 1

    for i, ch in enumerate(text):
        cp = ord(ch)
        prev_ch = text[i - 1] if i > 0 else None
        next_ch = text[i + 1] if i + 1 < len(text) else None

        if cp in ALWAYS_STRIP:
            report.findings.append(Finding(
                "invisible", ALWAYS_STRIP[cp], cp, line, col, "high",
                "invisible character with no role in ordinary text",
            ))
        elif cp in CONTEXT_STRIP:
            inert = _joiner_is_inert(prev_ch, next_ch)
            report.findings.append(Finding(
                "invisible", CONTEXT_STRIP[cp], cp, line, col,
                "high" if inert else "low",
                "invisible and inert between Latin characters" if inert
                else "load-bearing here (emoji or non-Latin neighbours)",
            ))
        elif is_tag_char(cp):
            report.findings.append(Finding(
                "tag", "UNICODE TAG", cp, line, col, "high",
                "tag block is a high-bandwidth hidden-text channel",
            ))
        elif is_variation_selector(cp):
            report.findings.append(Finding(
                "varsel", "VARIATION SELECTOR", cp, line, col, "medium",
                "variation selectors can smuggle a byte stream",
            ))
        elif cp in BIDI_CONTROLS:
            report.findings.append(Finding(
                "bidi", BIDI_CONTROLS[cp], cp, line, col,
                "low" if doc_has_rtl else "high",
                "document contains RTL text, so this may be genuine" if doc_has_rtl
                else "no RTL text in document, so this is inert",
            ))
        elif cp in SPACE_MAP:
            report.findings.append(Finding(
                "space", SPACE_MAP[cp], cp, line, col, "medium",
                "renders like a space but is not U+0020",
            ))
        elif cp in LINE_MAP:
            report.findings.append(Finding(
                "space", LINE_MAP[cp], cp, line, col, "medium",
                "unusual line separator",
            ))
        elif cp in SUSPICIOUS:
            report.findings.append(Finding(
                "suspicious", SUSPICIOUS[cp], cp, line, col, "low",
                "legitimate in braille documents, padding elsewhere",
            ))

        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1

    report.findings.extend(_scan_homoglyphs(text))
    report.findings.extend(_scan_typography(text))
    report.decoded_payloads.extend(decode_tag_payload(text))
    report.decoded_payloads.extend(decode_variation_payload(text))
    return report


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _mixed_script_words(text: str) -> Iterable[Tuple[int, str, set]]:
    """Yield (offset, word, scripts) for words drawing on more than one script."""
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        scripts = {s for s in (_script_of(c) for c in word) if s}
        if len(scripts) > 1:
            yield m.start(), word, scripts


def _line_col(text: str, index: int) -> Tuple[int, int]:
    line = text.count("\n", 0, index) + 1
    last_nl = text.rfind("\n", 0, index)
    return line, index - last_nl


def _scan_homoglyphs(text: str) -> List[Finding]:
    """Report non-Latin lookalikes sitting inside otherwise-Latin words.

    Scanning per word rather than per character is what keeps genuine Russian
    or Greek prose from being flagged wholesale: a Cyrillic 'о' is only
    suspicious when its neighbours are Latin.
    """
    findings: List[Finding] = []
    for offset, word, scripts in _mixed_script_words(text):
        if "LATIN" not in scripts:
            continue
        for j, ch in enumerate(word):
            if ch in HOMOGLYPHS and _script_of(ch) != "LATIN":
                line, col = _line_col(text, offset + j)
                try:
                    name = unicodedata.name(ch)
                except ValueError:
                    name = "UNKNOWN"
                findings.append(Finding(
                    "homoglyph", name, ord(ch), line, col, "high",
                    # ascii() rather than repr() so the offending codepoint is
                    # shown as an escape instead of an identical-looking glyph.
                    "reads as %r inside the Latin word %s"
                    % (HOMOGLYPHS[ch], ascii(word)),
                ))
    return findings


def _scan_typography(text: str) -> List[Finding]:
    """Report typographic characters that read as machine-generated."""
    findings: List[Finding] = []
    for i, ch in enumerate(text):
        if ch == EM_DASH or ch in TYPOGRAPHY:
            line, col = _line_col(text, i)
            try:
                name = unicodedata.name(ch)
            except ValueError:
                name = "UNKNOWN"
            findings.append(Finding(
                "typography", name, ord(ch), line, col, "low",
                "typographic form; common in generated and word-processed text",
            ))
    return findings


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------

PROFILES = ("safe", "standard", "aggressive")


def clean_text(
    text: str,
    profile: str = "standard",
    dash_style: str = "hyphen",
    collapse_whitespace: Optional[bool] = None,
) -> Tuple[str, Report]:
    """Return `text` with watermark-shaped artefacts removed, plus a report.

    Profiles:
      safe        Delete invisible characters only. Never changes a visible
                  glyph, so it is safe for source code, JSON, and CSV.
      standard    safe + exotic spaces folded to U+0020, mixed-script
                  homoglyphs folded to Latin, typographic punctuation
                  plainified. The default for prose.
      aggressive  standard + NFKC normalisation, whitespace collapsing, and
                  trailing-space removal.
    """
    if profile not in PROFILES:
        raise ValueError("unknown profile %r (expected one of %s)"
                         % (profile, ", ".join(PROFILES)))
    if dash_style not in DASH_STYLES:
        raise ValueError("unknown dash style %r (expected one of %s)"
                         % (dash_style, ", ".join(DASH_STYLES)))

    report = scan_text(text)
    doc_has_rtl = has_rtl(text)
    if collapse_whitespace is None:
        collapse_whitespace = profile == "aggressive"

    out: List[str] = []
    removed = 0
    replaced = 0
    # Set after a dash replacement so the spaces that flanked the original
    # dash are absorbed; "a — b" and "a—b" must both yield one separator.
    absorb_space = False

    for i, ch in enumerate(text):
        cp = ord(ch)
        prev_ch = text[i - 1] if i > 0 else None
        next_ch = text[i + 1] if i + 1 < len(text) else None

        # --- layer 1: invisible characters, stripped in every profile -----
        if cp in ALWAYS_STRIP:
            removed += 1
            continue
        if cp in CONTEXT_STRIP:
            if _joiner_is_inert(prev_ch, next_ch):
                removed += 1
                continue
            out.append(ch)
            continue
        if is_tag_char(cp):
            removed += 1
            continue
        if is_variation_selector(cp):
            removed += 1
            continue
        if cp in BIDI_CONTROLS:
            if not doc_has_rtl:
                removed += 1
                continue
            out.append(ch)
            continue
        if cp in LINE_MAP:
            out.append("\n")
            replaced += 1
            continue

        if profile == "safe":
            out.append(ch)
            continue

        # --- layer 2: confusables, standard and above ---------------------
        if absorb_space:
            if ch in (" ", "\t") or cp in SPACE_MAP:
                replaced += 1
                continue
            absorb_space = False

        if cp in SPACE_MAP:
            out.append(" ")
            replaced += 1
            continue
        if cp in SUSPICIOUS and profile == "aggressive":
            removed += 1
            continue

        # --- layer 3: typography, standard and above ----------------------
        if ch == EM_DASH:
            repl = DASH_STYLES[dash_style]
            if repl is None:
                out.append(ch)
            else:
                while out and out[-1] in (" ", "\t"):
                    out.pop()
                out.append(repl)
                replaced += 1
                absorb_space = True
            continue
        if ch in TYPOGRAPHY:
            out.append(TYPOGRAPHY[ch])
            replaced += 1
            continue

        out.append(ch)

    result = "".join(out)

    # --- layer 4: homoglyphs, applied on the reduced text ------------------
    if profile == "standard":
        result, n = fold_homoglyphs(result, mixed_script_only=True)
        replaced += n
    elif profile == "aggressive":
        result, n = fold_homoglyphs(result, mixed_script_only=False)
        replaced += n
        result = unicodedata.normalize("NFKC", result)

    if collapse_whitespace:
        result = re.sub(r"[ \t]{2,}", " ", result)
        result = re.sub(r"[ \t]+$", "", result, flags=re.MULTILINE)
        result = re.sub(r"\n{3,}", "\n\n", result)

    report.removed = removed
    report.replaced = replaced
    return result, report


def fold_homoglyphs(text: str, mixed_script_only: bool = True) -> Tuple[str, int]:
    """Replace non-Latin lookalikes with their Latin equivalents.

    With `mixed_script_only`, only characters inside words that already mix
    scripts are folded, which leaves genuine Cyrillic and Greek passages
    untouched. Without it, every mapped character is folded -- correct for
    de-fingerprinting a document known to be English, destructive otherwise.
    """
    if not mixed_script_only:
        count = 0
        out = []
        for ch in text:
            if ch in HOMOGLYPHS and _script_of(ch) != "LATIN":
                out.append(HOMOGLYPHS[ch])
                count += 1
            else:
                out.append(ch)
        return "".join(out), count

    edits: List[Tuple[int, str]] = []
    for offset, word, scripts in _mixed_script_words(text):
        if "LATIN" not in scripts:
            continue
        for j, ch in enumerate(word):
            if ch in HOMOGLYPHS and _script_of(ch) != "LATIN":
                edits.append((offset + j, HOMOGLYPHS[ch]))
    if not edits:
        return text, 0

    chars = list(text)
    for index, repl in edits:
        chars[index] = repl
    return "".join(chars), len(edits)


def strip_invisible(text: str) -> Tuple[str, int]:
    """Convenience wrapper: the `safe` profile with no other changes."""
    cleaned, report = clean_text(text, profile="safe")
    return cleaned, report.removed


# --------------------------------------------------------------------------
# Formatting helpers shared by the CLIs
# --------------------------------------------------------------------------

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def enable_utf8_stdio() -> None:
    """Make stdout/stderr able to carry any codepoint this tool reports.

    Windows consoles default to a legacy codepage (cp1250, cp437, ...) that
    cannot encode the very characters this tool exists to find, so printing a
    Cyrillic homoglyph finding would otherwise raise UnicodeEncodeError.
    Falling back to backslash escapes keeps output readable rather than fatal.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="backslashreplace")
        except (ValueError, OSError):
            pass  # already detached or redirected to something exotic


def format_report(report: Report, path: str = "", show_low: bool = False) -> str:
    """Render a Report as grouped, human-readable terminal output."""
    lines: List[str] = []
    findings = [f for f in report.findings if show_low or f.severity != "low"]

    if path:
        lines.append(path)

    if not findings and not report.decoded_payloads:
        lines.append("  clean - no watermark artefacts found")
        return "\n".join(lines)

    # Tag and variation-selector findings are only meaningful as a run -- the
    # individual codepoints are just the bytes of a payload -- so they collapse
    # into one line per kind instead of one line per distinct codepoint.
    RUN_KINDS = {"tag": "UNICODE TAG (run)", "varsel": "VARIATION SELECTOR (run)"}

    grouped: Dict[Tuple[str, str, Optional[int]], List[Finding]] = {}
    for f in findings:
        if f.kind in RUN_KINDS:
            key = (f.kind, RUN_KINDS[f.kind], None)
        else:
            key = (f.kind, f.name, f.codepoint)
        grouped.setdefault(key, []).append(f)

    ordered = sorted(
        grouped.items(),
        key=lambda kv: (SEVERITY_ORDER[kv[1][0].severity], -len(kv[1])),
    )

    for (kind, name, cp), group in ordered:
        first = group[0]
        label = name if kind in RUN_KINDS else first.label
        where = ", ".join("%d:%d" % (f.line, f.col) for f in group[:4])
        if len(group) > 4:
            where += ", +%d more" % (len(group) - 4)
        lines.append("  [%s] %-9s %-30s x%-4d %s"
                     % (first.severity[0].upper(), kind, label, len(group), where))
        if first.detail:
            lines.append("            %s" % first.detail)

    for payload in report.decoded_payloads:
        preview = payload if len(payload) <= 200 else payload[:197] + "..."
        lines.append("  [!] hidden payload decoded: %r" % preview)

    if report.removed or report.replaced:
        lines.append("  -> %d removed, %d replaced" % (report.removed, report.replaced))

    return "\n".join(lines)
