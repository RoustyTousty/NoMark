#!/usr/bin/env python3
"""
nomark clean-docs -- strip identifying metadata from documents.

Handles the container formats people actually submit:

    .docx .xlsx .pptx   OOXML  -- core/app/custom properties, rsid revision
                                  fingerprints, w14 paragraph IDs, document
                                  GUIDs, tracked-change authors, comment
                                  authors, thumbnails
    .odt .ods .odp      ODF    -- meta.xml generator, authors, editing cycles
    .epub               EPUB   -- OPF creator/contributor/generator
    .pdf                PDF    -- Info dictionary, XMP packet, /ID trailer
    .html .htm          HTML   -- generator/author meta, Word export blocks,
                                  leaked file:/// paths containing the username

Zip-based formats are rebuilt with normalised entry timestamps and host-OS
bytes, because those alone identify the machine that produced the file.

PDF rewriting needs `pypdf` (pip install pypdf); inspection works without it.

Examples:
    python scripts/clean_docs.py report.docx --inspect
    python scripts/clean_docs.py report.docx --in-place --backup
    python scripts/clean_docs.py report.docx -o clean.docx
    python scripts/clean_docs.py papers/ --in-place
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nomark_lib import (  # noqa: E402
    DASH_STYLES,
    PROFILES,
    Report,
    clean_text,
    enable_utf8_stdio,
    format_report,
    scan_text,
)

# Zip epoch. Matches the earliest timestamp the format can represent, so it
# reads as "unset" rather than as a plausible-but-wrong authoring time.
EPOCH_ZIP = (1980, 1, 1, 0, 0, 0)
EPOCH_ISO = "1980-01-01T00:00:00Z"

OOXML_EXTS = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"}
ODF_EXTS = {".odt", ".ods", ".odp", ".odg", ".odf"}
EPUB_EXTS = {".epub"}
PDF_EXTS = {".pdf"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
ZIP_EXTS = OOXML_EXTS | ODF_EXTS | EPUB_EXTS

# --- OOXML ---------------------------------------------------------------

# Identity fields in docProps/core.xml -- removed outright.
CORE_IDENTITY = [
    "dc:creator", "cp:lastModifiedBy", "cp:revision", "cp:lastPrinted",
    "cp:category", "cp:contentStatus", "dc:identifier", "cp:version",
    "cp:keywords", "dc:description", "dc:language",
]
# Descriptive fields -- kept unless --strip-all, since they are often content.
CORE_DESCRIPTIVE = ["dc:title", "dc:subject"]
# Date fields -- normalised to the epoch rather than removed.
CORE_DATES = ["dcterms:created", "dcterms:modified"]

# docProps/app.xml -- the authoring application's own fingerprint.
APP_FIELDS = [
    "Application", "AppVersion", "Company", "Manager", "Template",
    "TotalTime", "DocSecurity", "PresentationFormat", "HyperlinkBase",
]

# Revision Save IDs. Word stamps these on every run and paragraph; together
# they reconstruct the editing session that produced the document.
RSID_ATTRS = [
    "w:rsidR", "w:rsidRPr", "w:rsidRDefault", "w:rsidP", "w:rsidTr",
    "w:rsidDel", "w:rsidSect", "w:rsidroot", "w:rsidRoot",
]
# Durable per-paragraph GUIDs, stable across edits and copies.
PARA_ID_ATTRS = ["w14:paraId", "w14:textId", "w15:paraId", "w15:textId"]
# Tracked-change and comment authorship.
AUTHOR_ATTRS = ["w:author", "w:date", "w15:author", "w16cid:author"]

THUMBNAIL_RE = re.compile(r"^docProps/thumbnail\.", re.IGNORECASE)

# --- ODF -----------------------------------------------------------------

ODF_META_FIELDS = [
    "meta:generator", "meta:initial-creator", "dc:creator",
    "meta:editing-cycles", "meta:editing-duration", "meta:print-date",
    "meta:printed-by", "meta:document-statistic", "meta:user-defined",
    "meta:template",
]
ODF_DATE_FIELDS = ["meta:creation-date", "dc:date"]

# --- EPUB ----------------------------------------------------------------

EPUB_FIELDS = ["dc:creator", "dc:contributor", "dc:publisher", "dc:date"]

# --- PDF -----------------------------------------------------------------

PDF_INFO_KEYS = [
    "Producer", "Creator", "Author", "Title", "Subject", "Keywords",
    "CreationDate", "ModDate", "Company", "SourceModified", "Trapped",
]


# =========================================================================
# XML helpers
# =========================================================================

def _remove_elements(xml: str, tags: List[str]) -> Tuple[str, List[str]]:
    """Delete `<tag>...</tag>` and `<tag/>` entirely. Returns (xml, removed)."""
    removed: List[str] = []
    for tag in tags:
        pattern = re.compile(
            r"<%s(?:\s[^>]*)?(?:/>|>(.*?)</%s>)" % (re.escape(tag), re.escape(tag)),
            re.DOTALL,
        )

        def note(match: "re.Match") -> str:
            value = (match.group(1) or "").strip()
            removed.append("%s=%r" % (tag, value) if value else tag)
            return ""

        xml = pattern.sub(note, xml)
    return xml, removed


def _set_elements(xml: str, tags: List[str], value: str) -> Tuple[str, List[str]]:
    """Overwrite element text in place, preserving attributes and schema shape.

    Used for dates, where a missing element upsets some readers but a real
    timestamp is exactly the fingerprint being removed.
    """
    changed: List[str] = []
    for tag in tags:
        pattern = re.compile(
            r"(<%s(?:\s[^>]*)?>)(.*?)(</%s>)" % (re.escape(tag), re.escape(tag)),
            re.DOTALL,
        )

        def note(match: "re.Match") -> str:
            old = match.group(2).strip()
            if old and old != value:
                changed.append("%s: %r -> %r" % (tag, old, value))
            return match.group(1) + value + match.group(3)

        xml = pattern.sub(note, xml)
    return xml, changed


def _remove_attributes(xml: str, attrs: List[str]) -> Tuple[str, int]:
    """Delete the named XML attributes wherever they appear."""
    count = 0
    for attr in attrs:
        pattern = re.compile(r'\s%s="[^"]*"' % re.escape(attr))
        xml, n = pattern.subn("", xml)
        count += n
    return xml, count


def _blank_attributes(xml: str, attrs: List[str], value: str) -> Tuple[str, int]:
    """Replace attribute values in place, keeping the attribute present."""
    count = 0
    for attr in attrs:
        pattern = re.compile(r'(\s%s=")[^"]*(")' % re.escape(attr))
        xml, n = pattern.subn(r"\g<1>%s\g<2>" % value, xml)
        count += n
    return xml, count


# Run text in OOXML lives in <w:t> (Word) and <a:t> (charts, SmartArt,
# PowerPoint shapes). Everything else in the part is markup.
_OOXML_RUN_RE = re.compile(r"(<(?:w|a):t(?:\s[^>]*)?>)([^<]*)(</(?:w|a):t>)")
# ODF spreads text across many elements, so target text nodes generically.
_TEXT_NODE_RE = re.compile(r"(>)([^<>]+)(<)")


def _clean_part_text(
    xml: str,
    profile: str,
    dash_style: str,
    generic: bool = False,
) -> Tuple[str, int]:
    """Clean the text nodes of an XML part, leaving all markup untouched.

    Safe against XML corruption because none of the substitutions can emit
    `&`, `<`, or `>` -- they only delete codepoints or fold them to ASCII
    punctuation, so existing entity references pass through unchanged.
    """
    changes = 0

    def repl(match: "re.Match") -> str:
        nonlocal changes
        original = match.group(2)
        cleaned, report = clean_text(original, profile=profile,
                                     dash_style=dash_style)
        if cleaned != original:
            changes += report.removed + report.replaced
        return match.group(1) + cleaned + match.group(3)

    pattern = _TEXT_NODE_RE if generic else _OOXML_RUN_RE
    return pattern.sub(repl, xml), changes


def _extract_ooxml_text(xml: str) -> str:
    """Pull visible run text out of a WordprocessingML/DrawingML part."""
    parts = re.findall(r"<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>", xml, re.DOTALL)
    return "\n".join(parts)


def _extract_odf_text(xml: str) -> str:
    """Pull visible paragraph text out of an ODF content part.

    The closing tag is a backreference, not a second alternation: without it
    `<text:p>...</text:span>` would match across element boundaries and splice
    unrelated runs together.
    """
    parts = re.findall(r"<text:(p|span|h)(?:\s[^>]*)?>(.*?)</text:\1>",
                       xml, re.DOTALL)
    return "\n".join(re.sub(r"<[^>]+>", "", body) for _tag, body in parts)


# =========================================================================
# Zip container handling
# =========================================================================

def _read_zip(path: str) -> Tuple[List[zipfile.ZipInfo], Dict[str, bytes]]:
    with zipfile.ZipFile(path, "r") as zf:
        infos = zf.infolist()
        data = {info.filename: zf.read(info.filename) for info in infos}
    return infos, data


def _write_zip(
    path: str,
    infos: List[zipfile.ZipInfo],
    data: Dict[str, bytes],
    drop: Optional[set] = None,
) -> None:
    """Rebuild a zip with normalised timestamps and host-OS bytes.

    `mimetype` must stay first and uncompressed in ODF and EPUB containers,
    so entry order from the original file is preserved exactly.
    """
    drop = drop or set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in infos:
            if info.filename in drop or info.filename not in data:
                continue
            new_info = zipfile.ZipInfo(info.filename, date_time=EPOCH_ZIP)
            new_info.compress_type = info.compress_type
            new_info.external_attr = info.external_attr
            new_info.internal_attr = info.internal_attr
            # Host-OS byte identifies the writing platform; pin it to MS-DOS,
            # which is what Office itself emits.
            new_info.create_system = 0
            zf.writestr(new_info, data[info.filename])


# =========================================================================
# Format handlers
# =========================================================================

def _clean_ooxml(
    data: Dict[str, bytes],
    strip_all: bool,
    keep_dates: bool,
    text_profile: Optional[str] = None,
    dash_style: str = "hyphen",
) -> Tuple[Dict[str, bytes], List[str], set]:
    notes: List[str] = []
    drop: set = set()

    for name in list(data):
        if THUMBNAIL_RE.match(name):
            drop.add(name)
            notes.append("removed embedded thumbnail preview: %s" % name)

    if "docProps/custom.xml" in data:
        drop.add("docProps/custom.xml")
        notes.append("removed docProps/custom.xml (custom properties)")

    for name, raw in list(data.items()):
        if not name.endswith(".xml") and not name.endswith(".rels"):
            continue
        try:
            xml = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        original = xml

        if name == "docProps/core.xml":
            fields = list(CORE_IDENTITY)
            if strip_all:
                fields += CORE_DESCRIPTIVE
            xml, removed = _remove_elements(xml, fields)
            for item in removed:
                notes.append("core.xml: removed %s" % item)
            if not keep_dates:
                xml, changed = _set_elements(xml, CORE_DATES, EPOCH_ISO)
                for item in changed:
                    notes.append("core.xml: %s" % item)

        elif name == "docProps/app.xml":
            xml, removed = _remove_elements(xml, APP_FIELDS)
            for item in removed:
                notes.append("app.xml: removed %s" % item)

        elif name.endswith("settings.xml"):
            xml, removed = _remove_elements(xml, ["w:rsids", "w:proofState"])
            if removed:
                notes.append("%s: removed rsid table" % name)
            xml, doc_ids = _remove_elements(xml, ["w15:docId", "w14:docId"])
            if doc_ids:
                notes.append("%s: removed %d document GUID(s)"
                             % (name, len(doc_ids)))

        if name.endswith(".xml"):
            xml, n_rsid = _remove_attributes(xml, RSID_ATTRS)
            if n_rsid:
                notes.append("%s: removed %d rsid attribute(s)" % (name, n_rsid))
            xml, n_para = _remove_attributes(xml, PARA_ID_ATTRS)
            if n_para:
                notes.append("%s: removed %d paragraph GUID(s)" % (name, n_para))
            xml, n_auth = _blank_attributes(xml, ["w:author", "w15:author"], "Author")
            if n_auth:
                notes.append("%s: anonymised %d authorship attribute(s)"
                             % (name, n_auth))
            xml, n_date = _blank_attributes(xml, ["w:date"], EPOCH_ISO)
            if n_date:
                notes.append("%s: normalised %d revision date(s)" % (name, n_date))

        if text_profile and ("/document.xml" in name or "/slides/" in name
                             or name.endswith("sharedStrings.xml")
                             or "/notesSlides/" in name):
            xml, n_text = _clean_part_text(xml, text_profile, dash_style)
            if n_text:
                notes.append("%s: cleaned %d text-layer artefact(s)"
                             % (name, n_text))

        if xml != original:
            data[name] = xml.encode("utf-8")

    if "word/people.xml" in data:
        drop.add("word/people.xml")
        notes.append("removed word/people.xml (comment author registry)")

    return data, notes, drop


def _clean_odf(
    data: Dict[str, bytes],
    keep_dates: bool,
    text_profile: Optional[str] = None,
    dash_style: str = "hyphen",
) -> Tuple[Dict[str, bytes], List[str], set]:
    notes: List[str] = []
    if text_profile and "content.xml" in data:
        xml = data["content.xml"].decode("utf-8", errors="replace")
        xml, n_text = _clean_part_text(xml, text_profile, dash_style, generic=True)
        if n_text:
            notes.append("content.xml: cleaned %d text-layer artefact(s)" % n_text)
        data["content.xml"] = xml.encode("utf-8")

    if "meta.xml" not in data:
        return data, notes + ["no meta.xml found"], set()

    xml = data["meta.xml"].decode("utf-8", errors="replace")
    xml, removed = _remove_elements(xml, ODF_META_FIELDS)
    for item in removed:
        notes.append("meta.xml: removed %s" % item)
    if not keep_dates:
        xml, changed = _set_elements(xml, ODF_DATE_FIELDS, EPOCH_ISO)
        for item in changed:
            notes.append("meta.xml: %s" % item)
    data["meta.xml"] = xml.encode("utf-8")

    for name in list(data):
        if name.endswith(".xml"):
            raw = data[name].decode("utf-8", errors="replace")
            new, n = _blank_attributes(raw, ["office:name", "dc:creator"], "Author")
            if n:
                notes.append("%s: anonymised %d author attribute(s)" % (name, n))
                data[name] = new.encode("utf-8")
    return data, notes, set()


def _clean_epub(data: Dict[str, bytes], strip_all: bool) -> Tuple[Dict[str, bytes], List[str], set]:
    notes: List[str] = []
    for name in list(data):
        if not name.endswith(".opf"):
            continue
        xml = data[name].decode("utf-8", errors="replace")
        fields = list(EPUB_FIELDS)
        xml, removed = _remove_elements(xml, fields)
        for item in removed:
            notes.append("%s: removed %s" % (name, item))
        xml, n = re.subn(r'<meta[^>]*name="generator"[^>]*/?>', "", xml)
        if n:
            notes.append("%s: removed %d generator tag(s)" % (name, n))
        data[name] = xml.encode("utf-8")
    return data, notes, set()


# =========================================================================
# HTML
# =========================================================================

# Identity-bearing <meta> names. Content-descriptive ones (description,
# keywords, viewport) are left alone -- they are the page, not its author.
HTML_META_NAMES = [
    "generator", "author", "copyright", "owner", "creator", "publisher",
    "progid", "originator", "template", "company", "last-modified",
    "date", "created", "revision", "dc.creator", "dc.date", "citation_author",
]
HTML_META_PROPS = ["article:author", "article:published_time", "og:author"]

# Word's "Save as Web Page" wraps document properties, the author's name, and
# an absolute file:/// path to the local sidecar folder in MSO conditional
# comments. That path routinely contains the Windows username.
_MSO_CONDITIONAL_RE = re.compile(
    r"<!--\[if\s+[^\]]*mso[^\]]*\]>.*?<!\[endif\]-->",
    re.DOTALL | re.IGNORECASE,
)
_FILE_LIST_RE = re.compile(
    r"<link[^>]*rel=[\"']?File-List[\"']?[^>]*>", re.IGNORECASE)
_LOCAL_PATH_RE = re.compile(
    r"file:///[A-Za-z]:/[^\"'\s>]*|file:///[^\"'\s>]*", re.IGNORECASE)
_GENERATOR_COMMENT_RE = re.compile(
    r"<!--\s*(?:generated|created|produced|exported)\b.*?-->",
    re.DOTALL | re.IGNORECASE,
)


def _html_meta_re(attr: str, value: str) -> "re.Pattern":
    """Match a <meta> tag whose `attr` equals `value`, quoted or bare."""
    return re.compile(
        r"<meta\b[^>]*\b%s\s*=\s*[\"']?%s[\"']?[^>]*>" % (attr, re.escape(value)),
        re.IGNORECASE,
    )


def _inspect_html(path: str) -> Tuple[Report, List[str]]:
    notes: List[str] = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    for name in HTML_META_NAMES:
        for match in _html_meta_re("name", name).finditer(text):
            notes.append("meta %s: %s" % (name, match.group(0)[:140]))
    for prop in HTML_META_PROPS:
        for match in _html_meta_re("property", prop).finditer(text):
            notes.append("meta %s: %s" % (prop, match.group(0)[:140]))

    mso = len(_MSO_CONDITIONAL_RE.findall(text))
    if mso:
        notes.append("%d Word conditional comment block(s) carrying document "
                     "properties" % mso)
    for match in _LOCAL_PATH_RE.finditer(text):
        notes.append("local filesystem path leaked: %r" % match.group(0)[:140])
    if _FILE_LIST_RE.search(text):
        notes.append("File-List link to the Word sidecar folder")
    for match in _GENERATOR_COMMENT_RE.finditer(text):
        notes.append("generator comment: %r" % match.group(0)[:140])

    return scan_text(text), notes


def _clean_html(text: str) -> Tuple[str, List[str]]:
    notes: List[str] = []

    for name in HTML_META_NAMES:
        text, n = _html_meta_re("name", name).subn("", text)
        if n:
            notes.append("removed %d <meta name=%s> tag(s)" % (n, name))
    for prop in HTML_META_PROPS:
        text, n = _html_meta_re("property", prop).subn("", text)
        if n:
            notes.append("removed %d <meta property=%s> tag(s)" % (n, prop))

    text, n = _MSO_CONDITIONAL_RE.subn("", text)
    if n:
        notes.append("removed %d Word conditional comment block(s)" % n)
    text, n = _FILE_LIST_RE.subn("", text)
    if n:
        notes.append("removed %d File-List link(s)" % n)
    text, n = _GENERATOR_COMMENT_RE.subn("", text)
    if n:
        notes.append("removed %d generator comment(s)" % n)
    text, n = _LOCAL_PATH_RE.subn("", text)
    if n:
        notes.append("removed %d leaked local path(s)" % n)

    # Office namespace elements survive the conditional-comment sweep because
    # they also appear in the body of exported documents.
    text, n = re.subn(r"</?o:[\w-]+(?:\s[^>]*)?/?>", "", text)
    if n:
        notes.append("removed %d Office namespace tag(s)" % n)

    return text, notes


# =========================================================================
# PDF
# =========================================================================

def _inspect_pdf(path: str) -> Tuple[Report, List[str]]:
    notes: List[str] = []
    report = Report()
    with open(path, "rb") as fh:
        raw = fh.read()

    for key in PDF_INFO_KEYS:
        for match in re.finditer(
            rb"/%s\s*\((.*?)(?<!\\)\)" % key.encode("ascii"), raw, re.DOTALL
        ):
            value = match.group(1).decode("latin-1", errors="replace")
            if value.strip():
                notes.append("Info /%s = %r" % (key, value[:120]))

    if re.search(rb"<\?xpacket", raw):
        notes.append("XMP metadata packet present (may hold tool and history)")
        for tag in (b"xmp:CreatorTool", b"xmpMM:DocumentID", b"xmpMM:InstanceID",
                    b"pdf:Producer", b"dc:creator"):
            for match in re.finditer(
                rb"<%s[^>]*>(.*?)</%s>" % (tag, tag), raw, re.DOTALL
            ):
                value = re.sub(rb"<[^>]+>", b"", match.group(1))
                text = value.decode("utf-8", errors="replace").strip()
                if text:
                    notes.append("XMP %s = %r"
                                 % (tag.decode("ascii"), text[:120]))

    if re.search(rb"/ID\s*\[", raw):
        notes.append("/ID trailer present (per-file identifier pair)")

    return report, notes


def _clean_pdf(src: str, dst: str, keep_dates: bool) -> List[str]:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise RuntimeError(
            "PDF rewriting needs pypdf. Install it with:  pip install pypdf\n"
            "  (inspection with --inspect works without it)"
        )

    reader = PdfReader(src)
    writer = PdfWriter()
    notes: List[str] = []

    for page in reader.pages:
        writer.add_page(page)

    if reader.metadata:
        for key, value in reader.metadata.items():
            if str(value).strip():
                notes.append("removed Info %s = %r" % (key, str(value)[:120]))

    # An empty dict replaces the Info entries rather than carrying them over.
    writer.add_metadata({})

    # Drop the XMP packet, which mirrors the Info dictionary and additionally
    # carries xmpMM:DocumentID and an edit history. Stripping Info alone leaves
    # every one of those values intact, so this step is not optional.
    #
    # pypdf has moved this between public and private attributes across
    # versions, so try the documented route first and fall back rather than
    # depending on one release's internals.
    removed_xmp = False
    try:
        if getattr(reader, "xmp_metadata", None) is not None:
            writer.xmp_metadata = None
            removed_xmp = True
    except Exception:
        pass
    if not removed_xmp:
        root = getattr(writer, "root_object", None) or getattr(
            writer, "_root_object", None)
        try:
            if root is not None and "/Metadata" in root:
                del root["/Metadata"]
                removed_xmp = True
        except Exception as exc:
            notes.append("could not remove XMP stream: %s" % exc)
    notes.append("removed XMP metadata stream" if removed_xmp
                 else "no XMP metadata stream found")

    with open(dst, "wb") as fh:
        writer.write(fh)
    notes.append("rewrote PDF without Info dictionary")
    if not keep_dates:
        notes.append("creation and modification dates dropped with Info dict")
    return notes


# =========================================================================
# Public API
# =========================================================================

def inspect(path: str) -> Tuple[Report, List[str]]:
    """Report metadata and embedded-text findings without modifying `path`."""
    ext = os.path.splitext(path)[1].lower()

    if ext in PDF_EXTS:
        return _inspect_pdf(path)

    if ext in HTML_EXTS:
        return _inspect_html(path)

    if ext not in ZIP_EXTS:
        return Report(), ["unsupported document type: %s" % ext]

    report = Report()
    notes: List[str] = []
    _, data = _read_zip(path)

    stamps = set()
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            stamps.add(info.date_time)
            if info.create_system == 3:
                notes.append("zip entries written on a Unix-like host "
                             "(create_system=3)")
                break
    if len(stamps) > 1 or (stamps and EPOCH_ZIP not in stamps):
        notes.append("%d distinct zip entry timestamp(s) reveal authoring times"
                     % len(stamps))

    for name, raw in data.items():
        if name in ("docProps/core.xml", "docProps/app.xml",
                    "docProps/custom.xml", "meta.xml") or name.endswith(".opf"):
            xml = raw.decode("utf-8", errors="replace")
            for match in re.finditer(r"<([\w:.-]+)(?:\s[^>]*)?>([^<]+)</\1>", xml):
                tag, value = match.group(1), match.group(2).strip()
                if value and tag not in ("Pages", "Words", "Characters", "Lines",
                                         "Paragraphs", "ScaleCrop", "LinksUpToDate",
                                         "SharedDoc", "HyperlinksChanged"):
                    notes.append("%s: %s = %r" % (name, tag, value[:120]))

        if name.endswith("settings.xml") and b"rsid" in raw:
            count = len(re.findall(rb"<w:rsid ", raw))
            notes.append("%s: %d rsid revision fingerprint(s)" % (name, count))
        if name.endswith("document.xml"):
            count = len(re.findall(rb'w14:paraId="', raw))
            if count:
                notes.append("%s: %d durable paragraph GUID(s)" % (name, count))
        if name == "word/people.xml":
            notes.append("word/people.xml present (comment author registry)")
        if THUMBNAIL_RE.match(name):
            notes.append("%s: embedded thumbnail preview of the document" % name)

        # Scan the visible text for the same artefacts as a plain text file.
        if name.endswith(("document.xml", "content.xml")) or "/slides/" in name:
            xml = raw.decode("utf-8", errors="replace")
            text = _extract_ooxml_text(xml) or _extract_odf_text(xml)
            if text:
                report.extend(scan_text(text))

    return report, notes


def clean(
    src: str,
    dst: str,
    strip_all: bool = False,
    keep_dates: bool = False,
    text_profile: Optional[str] = None,
    dash_style: str = "hyphen",
) -> List[str]:
    """Write a metadata-stripped copy of `src` to `dst`. Returns change notes.

    With `text_profile` set, the visible text inside the document is cleaned
    too, so a single pass covers both the metadata and the text layers.
    """
    ext = os.path.splitext(src)[1].lower()

    if ext in PDF_EXTS:
        return _clean_pdf(src, dst, keep_dates)

    if ext in HTML_EXTS:
        with open(src, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        text, notes = _clean_html(text)
        if text_profile:
            text, report = clean_text(text, profile=text_profile,
                                      dash_style=dash_style)
            if report.removed or report.replaced:
                notes.append("cleaned %d text-layer artefact(s)"
                             % (report.removed + report.replaced))
        with open(dst, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        return notes or ["no HTML metadata found"]

    if ext not in ZIP_EXTS:
        raise RuntimeError("unsupported document type: %s" % ext)

    infos, data = _read_zip(src)

    if ext in OOXML_EXTS:
        data, notes, drop = _clean_ooxml(data, strip_all, keep_dates,
                                         text_profile, dash_style)
    elif ext in ODF_EXTS:
        data, notes, drop = _clean_odf(data, keep_dates,
                                       text_profile, dash_style)
    else:
        data, notes, drop = _clean_epub(data, strip_all)

    _write_zip(dst, infos, data, drop)
    notes.append("rebuilt container with normalised timestamps and host OS")
    return notes


# =========================================================================
# CLI
# =========================================================================

def main(argv: Optional[List[str]] = None) -> int:
    enable_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="nomark clean-docs",
        description="Strip identifying metadata from documents.",
    )
    parser.add_argument("paths", nargs="+", help="document files or directories")
    parser.add_argument("--inspect", action="store_true",
                        help="report metadata without changing anything")
    parser.add_argument("-o", "--output", default=None,
                        help="write the cleaned copy here (single input only)")
    parser.add_argument("--in-place", action="store_true",
                        help="overwrite the input file")
    parser.add_argument("--backup", action="store_true",
                        help="with --in-place, keep the original as FILE.bak")
    parser.add_argument("--strip-all", action="store_true",
                        help="also remove title and subject, not just identity")
    parser.add_argument("--keep-dates", action="store_true",
                        help="preserve creation and modification timestamps")
    parser.add_argument("--clean-text", nargs="?", const="standard",
                        choices=PROFILES, default=None, metavar="PROFILE",
                        help="also clean the visible text inside the document "
                             "(default profile: standard)")
    parser.add_argument("--dash-style", choices=sorted(DASH_STYLES),
                        default="hyphen",
                        help="with --clean-text, what replaces em dashes")
    parser.add_argument("--show-low", action="store_true",
                        help="include low-severity text findings")
    args = parser.parse_args(argv)

    if args.output and args.in_place:
        parser.error("--output and --in-place are mutually exclusive")

    files: List[str] = []
    for path in args.paths:
        if os.path.isdir(path):
            for root, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for name in sorted(names):
                    if os.path.splitext(name)[1].lower() in (
                            ZIP_EXTS | PDF_EXTS | HTML_EXTS):
                        files.append(os.path.join(root, name))
        elif os.path.isfile(path):
            files.append(path)
        else:
            print("  ! no such path: %s" % path, file=sys.stderr)

    if not files:
        print("no documents found", file=sys.stderr)
        return 0
    if args.output and len(files) > 1:
        parser.error("--output takes a single input file")
    if not args.inspect and not args.in_place and not args.output:
        parser.error("choose one of --inspect, --in-place, or --output")

    failures = 0
    for path in files:
        print(path)
        try:
            if args.inspect:
                report, notes = inspect(path)
                for note in notes:
                    print("  [M] %s" % note)
                body = format_report(report, "", args.show_low)
                if body.strip() and "clean -" not in body:
                    print("  text layer:")
                    print(body)
                elif not notes:
                    print("  clean - no metadata found")
            else:
                dst = args.output or (path + ".nomark.tmp")
                notes = clean(path, dst, args.strip_all, args.keep_dates,
                              args.clean_text, args.dash_style)
                if args.in_place:
                    if args.backup:
                        shutil.copy2(path, path + ".bak")
                    shutil.move(dst, path)
                for note in notes:
                    print("  - %s" % note)
                print("  wrote %s" % (path if args.in_place else dst))
        except Exception as exc:
            failures += 1
            print("  ! %s" % exc, file=sys.stderr)
            stale = path + ".nomark.tmp"
            if os.path.exists(stale):
                os.remove(stale)
        print()

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
