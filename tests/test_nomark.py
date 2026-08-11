#!/usr/bin/env python3
"""Test suite for NoMark. Run with: python -m unittest discover -s tests"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "skills", "nomark", "scripts"))

import clean_docs  # noqa: E402
import nomark  # noqa: E402
from nomark_lib import (  # noqa: E402
    clean_text,
    decode_tag_payload,
    decode_variation_payload,
    fold_homoglyphs,
    scan_text,
)


class TestInvisibleCharacters(unittest.TestCase):
    def test_zero_width_space_removed(self):
        text = "hello​world"
        cleaned, report = clean_text(text, profile="safe")
        self.assertEqual(cleaned, "helloworld")
        self.assertEqual(report.removed, 1)

    def test_all_always_strip_removed(self):
        text = "a­​⁠﻿᠎͏b"
        cleaned, _ = clean_text(text, profile="safe")
        self.assertEqual(cleaned, "ab")

    def test_bom_removed(self):
        cleaned, _ = clean_text("﻿heading", profile="safe")
        self.assertEqual(cleaned, "heading")

    def test_scan_reports_without_mutating(self):
        text = "hi​there"
        report = scan_text(text)
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].kind, "invisible")
        self.assertEqual(report.findings[0].severity, "high")


class TestJoinerContext(unittest.TestCase):
    def test_zwj_between_latin_is_removed(self):
        cleaned, _ = clean_text("wo‍rd", profile="safe")
        self.assertEqual(cleaned, "word")

    def test_zwj_in_emoji_sequence_is_kept(self):
        # Family emoji depends on ZWJ; deleting it changes the rendered glyph.
        family = "\U0001f468‍\U0001f469‍\U0001f466"
        cleaned, _ = clean_text(family, profile="safe")
        self.assertEqual(cleaned, family)

    def test_zwnj_in_persian_is_kept(self):
        text = "می‌رود"
        cleaned, _ = clean_text(text, profile="safe")
        self.assertIn("‌", cleaned)


class TestTagSmuggling(unittest.TestCase):
    def test_tag_characters_removed(self):
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "SECRET")
        text = "Innocent sentence." + hidden
        cleaned, _ = clean_text(text, profile="safe")
        self.assertEqual(cleaned, "Innocent sentence.")

    def test_tag_payload_decoded(self):
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "id=4471")
        payloads = decode_tag_payload("visible" + hidden)
        self.assertEqual(payloads, ["id=4471"])

    def test_scan_surfaces_payload(self):
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "trace-me")
        report = scan_text("Text" + hidden)
        self.assertIn("trace-me", report.decoded_payloads)


class TestVariationSelectorSmuggling(unittest.TestCase):
    def _encode(self, payload: str) -> str:
        out = []
        for byte in payload.encode("utf-8"):
            if byte < 16:
                out.append(chr(0xFE00 + byte))
            else:
                out.append(chr(0xE0100 + byte - 16))
        return "".join(out)

    def test_variation_payload_decoded(self):
        text = "\U0001f600" + self._encode("hi there")
        self.assertIn("hi there", decode_variation_payload(text))

    def test_variation_selectors_removed(self):
        text = "A" + self._encode("tag")
        cleaned, _ = clean_text(text, profile="safe")
        self.assertEqual(cleaned, "A")

    def test_lone_selector_not_reported_as_payload(self):
        # A single VS after an emoji is ordinary presentation markup.
        self.assertEqual(decode_variation_payload("❤️"), [])


class TestBidi(unittest.TestCase):
    def test_bidi_stripped_when_no_rtl(self):
        cleaned, _ = clean_text("plain‮text", profile="safe")
        self.assertEqual(cleaned, "plaintext")

    def test_bidi_kept_when_document_has_rtl(self):
        text = "שלום ‎(hello)"
        cleaned, _ = clean_text(text, profile="safe")
        self.assertIn("‎", cleaned)

    def test_bom_does_not_count_as_rtl(self):
        # U+FEFF sits next to the Arabic presentation forms. Treating it as RTL
        # would make any file with a BOM suppress its own bidi findings.
        text = "﻿plain‮text"
        cleaned, report = clean_text(text, profile="safe")
        self.assertEqual(cleaned, "plaintext")
        bidi = [f for f in report.findings if f.kind == "bidi"]
        self.assertEqual(len(bidi), 1)
        self.assertEqual(bidi[0].severity, "high")

    def test_rlo_trojan_source_flagged(self):
        report = scan_text("if (x) { /* ‮ */ }")
        self.assertTrue(any(f.codepoint == 0x202E and f.severity == "high"
                            for f in report.findings))


class TestSpaces(unittest.TestCase):
    def test_nbsp_normalised_in_standard(self):
        cleaned, _ = clean_text("a b", profile="standard")
        self.assertEqual(cleaned, "a b")

    def test_spaces_untouched_in_safe(self):
        cleaned, _ = clean_text("a b", profile="safe")
        self.assertEqual(cleaned, "a b")

    def test_narrow_nbsp_and_thin_space(self):
        cleaned, _ = clean_text("a b c", profile="standard")
        self.assertEqual(cleaned, "a b c")

    def test_line_separator_becomes_newline(self):
        cleaned, _ = clean_text("a b", profile="safe")
        self.assertEqual(cleaned, "a\nb")


class TestHomoglyphs(unittest.TestCase):
    def test_mixed_script_word_folded(self):
        # Cyrillic 'о' hiding inside a Latin word.
        text = "the passwоrd is set"
        cleaned, _ = clean_text(text, profile="standard")
        self.assertEqual(cleaned, "the password is set")

    def test_genuine_cyrillic_preserved(self):
        text = "Привет мир"
        cleaned, _ = clean_text(text, profile="standard")
        self.assertEqual(cleaned, text)

    def test_genuine_greek_preserved(self):
        text = "αλφα βήτα"
        cleaned, _ = clean_text(text, profile="standard")
        self.assertEqual(cleaned, text)

    def test_aggressive_folds_everything(self):
        text = "ок"
        cleaned, _ = fold_homoglyphs(text, mixed_script_only=False)
        self.assertEqual(cleaned, "ok")

    def test_scan_flags_mixed_script(self):
        report = scan_text("passwоrd")
        kinds = [f.kind for f in report.findings]
        self.assertIn("homoglyph", kinds)


class TestTypography(unittest.TestCase):
    def test_em_dash_default_hyphen(self):
        cleaned, _ = clean_text("a — b", profile="standard")
        self.assertEqual(cleaned, "a - b")

    def test_em_dash_comma_style(self):
        cleaned, _ = clean_text("a—b", profile="standard", dash_style="comma")
        self.assertEqual(cleaned, "a, b")

    def test_em_dash_absorbs_flanking_spaces(self):
        # Spaced and unspaced dashes must converge on the same output.
        spaced, _ = clean_text("a — b", profile="standard", dash_style="comma")
        tight, _ = clean_text("a—b", profile="standard", dash_style="comma")
        self.assertEqual(spaced, tight)
        self.assertEqual(spaced, "a, b")

    def test_em_dash_absorbs_exotic_flanking_space(self):
        cleaned, _ = clean_text("a — b", profile="standard")
        self.assertEqual(cleaned, "a - b")

    def test_paired_em_dashes(self):
        cleaned, _ = clean_text("the results — crucially — exceeded",
                                profile="standard", dash_style="comma")
        self.assertEqual(cleaned, "the results, crucially, exceeded")

    def test_em_dash_kept(self):
        cleaned, _ = clean_text("a—b", profile="standard", dash_style="keep")
        self.assertEqual(cleaned, "a—b")

    def test_curly_quotes_straightened(self):
        cleaned, _ = clean_text("“quoted” and ‘single’",
                                profile="standard")
        self.assertEqual(cleaned, '"quoted" and \'single\'')

    def test_ellipsis_expanded(self):
        cleaned, _ = clean_text("wait…", profile="standard")
        self.assertEqual(cleaned, "wait...")

    def test_safe_profile_leaves_typography(self):
        text = "a — “b”…"
        cleaned, _ = clean_text(text, profile="safe")
        self.assertEqual(cleaned, text)


class TestProfiles(unittest.TestCase):
    def test_safe_preserves_code_semantics(self):
        code = 'x = "a b"  # — note\n'
        cleaned, _ = clean_text(code, profile="safe")
        self.assertEqual(cleaned, code)

    def test_aggressive_collapses_whitespace(self):
        cleaned, _ = clean_text("a    b   \n\n\n\nc", profile="aggressive")
        self.assertEqual(cleaned, "a b\n\nc")

    def test_unknown_profile_rejected(self):
        with self.assertRaises(ValueError):
            clean_text("x", profile="nope")

    def test_unknown_dash_style_rejected(self):
        with self.assertRaises(ValueError):
            clean_text("x", dash_style="nope")

    def test_clean_text_is_idempotent(self):
        text = "He said “hi”​ — then left."
        once, _ = clean_text(text, profile="standard")
        twice, _ = clean_text(once, profile="standard")
        self.assertEqual(once, twice)


class TestCombined(unittest.TestCase):
    def test_realistic_watermarked_paragraph(self):
        hidden = "".join(chr(0xE0000 + ord(c)) for c in "u=91")
        text = ("It’s worth noting​ that the passwоrd "
                "— crucially — matters." + hidden)
        cleaned, report = clean_text(text, profile="standard")
        for bad in ("’", " ", "​", "о", "—"):
            self.assertNotIn(bad, cleaned)
        self.assertNotIn(chr(0xE0000 + ord("u")), cleaned)
        self.assertIn("u=91", report.decoded_payloads)
        self.assertIn("password", cleaned)

    def test_clean_text_reports_clean_input(self):
        report = scan_text("Perfectly ordinary ASCII text.")
        self.assertTrue(report.clean)


def _minimal_docx(path: str) -> None:
    """Build a small but realistic .docx carrying every fingerprint we strip."""
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/'
        'package/2006/metadata/core-properties" xmlns:dc="http://purl.org/'
        'dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
        "<dc:title>Quarterly Report</dc:title>"
        "<dc:creator>Jane Doe</dc:creator>"
        "<cp:lastModifiedBy>Jane Doe</cp:lastModifiedBy>"
        "<cp:revision>7</cp:revision>"
        "<dcterms:created>2026-03-04T10:11:12Z</dcterms:created>"
        "<dcterms:modified>2026-03-05T18:00:00Z</dcterms:modified>"
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/'
        '2006/extended-properties">'
        "<Application>Microsoft Office Word</Application>"
        "<AppVersion>16.0000</AppVersion>"
        "<Company>Acme Corp</Company>"
        "<Template>Normal.dotm</Template>"
        "<TotalTime>412</TotalTime>"
        "<Pages>3</Pages>"
        "</Properties>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main" xmlns:w15="http://schemas.microsoft.com/office/word/2012/'
        'wordml">'
        '<w15:docId w15:val="{2B4C1F0A-1111-2222-3333-444455556666}"/>'
        '<w:rsids><w:rsidRoot w:val="00A12B34"/>'
        '<w:rsid w:val="00A12B34"/><w:rsid w:val="00B56C78"/>'
        '<w:rsid w:val="00C9AD01"/></w:rsids>'
        "</w:settings>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main" xmlns:w14="http://schemas.microsoft.com/office/word/2010/'
        'wordml"><w:body>'
        '<w:p w14:paraId="1A2B3C4D" w14:textId="5E6F7A8B" w:rsidR="00A12B34" '
        'w:rsidRDefault="00A12B34" w:rsidP="00B56C78">'
        '<w:r w:rsidRPr="00C9AD01"><w:t>Revenue grew​ sharply '
        'this quarter.</w:t></w:r></w:p>'
        '<w:ins w:id="1" w:author="Jane Doe" w:date="2026-03-05T09:00:00Z">'
        "<w:r><w:t>Added later.</w:t></w:r></w:ins>"
        "</w:body></w:document>"
    )
    people = (
        '<?xml version="1.0"?><w15:people xmlns:w15="http://schemas.microsoft.com/'
        'office/word/2012/wordml"><w15:person w15:author="Jane Doe"/>'
        "</w15:people>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
        'content-types"><Default Extension="xml" ContentType="application/xml"/>'
        "</Types>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in [
            ("[Content_Types].xml", content_types),
            ("docProps/core.xml", core),
            ("docProps/app.xml", app),
            ("docProps/custom.xml", "<Properties><p>x</p></Properties>"),
            ("docProps/thumbnail.jpeg", "fake-jpeg-bytes"),
            ("word/settings.xml", settings),
            ("word/document.xml", document),
            ("word/people.xml", people),
        ]:
            info = zipfile.ZipInfo(name, date_time=(2026, 3, 5, 18, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            zf.writestr(info, body)


class TestDocxCleaning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "report.docx")
        self.dst = os.path.join(self.tmp, "clean.docx")
        _minimal_docx(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _entries(self, path):
        with zipfile.ZipFile(path) as zf:
            return {n: zf.read(n).decode("utf-8", "replace")
                    for n in zf.namelist()}

    def test_inspect_finds_metadata(self):
        report, notes = clean_docs.inspect(self.src)
        joined = "\n".join(notes)
        self.assertIn("Jane Doe", joined)
        self.assertIn("Acme Corp", joined)
        self.assertIn("rsid", joined)
        self.assertIn("paragraph GUID", joined)
        self.assertIn("thumbnail", joined)

    def test_inspect_scans_embedded_text(self):
        report, _ = clean_docs.inspect(self.src)
        kinds = {f.kind for f in report.findings}
        self.assertIn("invisible", kinds)
        self.assertIn("space", kinds)

    def test_clean_removes_author(self):
        clean_docs.clean(self.src, self.dst)
        entries = self._entries(self.dst)
        self.assertNotIn("Jane Doe", entries["docProps/core.xml"])
        self.assertNotIn("Acme Corp", entries["docProps/app.xml"])

    def test_clean_keeps_title_by_default(self):
        clean_docs.clean(self.src, self.dst)
        entries = self._entries(self.dst)
        self.assertIn("Quarterly Report", entries["docProps/core.xml"])

    def test_strip_all_removes_title(self):
        clean_docs.clean(self.src, self.dst, strip_all=True)
        entries = self._entries(self.dst)
        self.assertNotIn("Quarterly Report", entries["docProps/core.xml"])

    def test_clean_removes_rsids_and_para_ids(self):
        clean_docs.clean(self.src, self.dst)
        entries = self._entries(self.dst)
        self.assertNotIn("rsid", entries["word/settings.xml"])
        self.assertNotIn("w:rsidR=", entries["word/document.xml"])
        self.assertNotIn("w14:paraId", entries["word/document.xml"])
        self.assertNotIn("docId", entries["word/settings.xml"])

    def test_clean_anonymises_tracked_changes(self):
        clean_docs.clean(self.src, self.dst)
        doc = self._entries(self.dst)["word/document.xml"]
        self.assertNotIn("Jane Doe", doc)
        self.assertIn('w:author="Author"', doc)

    def test_clean_drops_side_files(self):
        clean_docs.clean(self.src, self.dst)
        with zipfile.ZipFile(self.dst) as zf:
            names = zf.namelist()
        self.assertNotIn("word/people.xml", names)
        self.assertNotIn("docProps/custom.xml", names)
        self.assertNotIn("docProps/thumbnail.jpeg", names)

    def test_clean_preserves_visible_content(self):
        clean_docs.clean(self.src, self.dst)
        doc = self._entries(self.dst)["word/document.xml"]
        self.assertIn("Revenue grew", doc)
        self.assertIn("Added later.", doc)

    def test_clean_normalises_timestamps_and_host(self):
        clean_docs.clean(self.src, self.dst)
        with zipfile.ZipFile(self.dst) as zf:
            for info in zf.infolist():
                self.assertEqual(info.date_time, clean_docs.EPOCH_ZIP)
                self.assertEqual(info.create_system, 0)

    def test_clean_normalises_dates(self):
        clean_docs.clean(self.src, self.dst)
        core = self._entries(self.dst)["docProps/core.xml"]
        self.assertNotIn("2026-03-04", core)
        self.assertIn(clean_docs.EPOCH_ISO, core)

    def test_keep_dates_preserves_them(self):
        clean_docs.clean(self.src, self.dst, keep_dates=True)
        core = self._entries(self.dst)["docProps/core.xml"]
        self.assertIn("2026-03-04", core)

    def test_output_is_a_valid_zip(self):
        clean_docs.clean(self.src, self.dst)
        with zipfile.ZipFile(self.dst) as zf:
            self.assertIsNone(zf.testzip())

    def test_text_layer_untouched_by_default(self):
        clean_docs.clean(self.src, self.dst)
        doc = self._entries(self.dst)["word/document.xml"]
        self.assertIn("​", doc)

    def test_clean_text_option_cleans_run_text(self):
        clean_docs.clean(self.src, self.dst, text_profile="standard")
        doc = self._entries(self.dst)["word/document.xml"]
        self.assertNotIn("​", doc)   # zero width space
        self.assertNotIn(" ", doc)   # no-break space
        self.assertIn("Revenue grew sharply", doc)

    def test_clean_text_leaves_markup_valid(self):
        clean_docs.clean(self.src, self.dst, text_profile="aggressive")
        doc = self._entries(self.dst)["word/document.xml"]
        self.assertEqual(doc.count("<w:t>"), doc.count("</w:t>"))
        self.assertIn("<w:body>", doc)
        self.assertIn("</w:document>", doc)

    def test_clean_text_leaves_metadata_scan_clean(self):
        clean_docs.clean(self.src, self.dst, text_profile="standard")
        report, _ = clean_docs.inspect(self.dst)
        self.assertTrue(report.clean, report.counts_by_kind())

    def test_cleaning_is_idempotent(self):
        clean_docs.clean(self.src, self.dst)
        second = os.path.join(self.tmp, "clean2.docx")
        clean_docs.clean(self.dst, second)
        self.assertEqual(self._entries(self.dst), self._entries(second))


WORD_HTML = """<html xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta name=Generator content="Microsoft Word 15 (filtered)">
<meta name=ProgId content=Word.Document>
<meta name=Originator content="Microsoft Word 15">
<meta name="author" content="Jane Doe">
<meta name="description" content="A report about revenue">
<link rel=File-List href="file:///C:/Users/jdoe/AppData/Local/Temp/report_files/filelist.xml">
<!--[if gte mso 9]><xml>
 <o:DocumentProperties>
  <o:Author>Jane Doe</o:Author>
  <o:Company>Acme Corp</o:Company>
 </o:DocumentProperties>
</xml><![endif]-->
<!-- Generated by AcmePublisher 4.2 -->
</head>
<body><p>Revenue grew<o:p></o:p> sharply.</p></body>
</html>
"""


class TestHtmlMetadata(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "report.html")
        self.dst = os.path.join(self.tmp, "clean.html")
        with open(self.src, "w", encoding="utf-8") as fh:
            fh.write(WORD_HTML)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _cleaned(self):
        clean_docs.clean(self.src, self.dst)
        with open(self.dst, encoding="utf-8") as fh:
            return fh.read()

    def test_inspect_reports_author_and_generator(self):
        _, notes = clean_docs.inspect(self.src)
        joined = "\n".join(notes)
        self.assertIn("Jane Doe", joined)
        self.assertIn("Microsoft Word", joined)

    def test_inspect_reports_leaked_local_path(self):
        _, notes = clean_docs.inspect(self.src)
        joined = "\n".join(notes)
        # The Word sidecar path exposes the operating-system username.
        self.assertIn("jdoe", joined)

    def test_clean_removes_identity_meta(self):
        out = self._cleaned()
        self.assertNotIn("Jane Doe", out)
        self.assertNotIn("Acme Corp", out)
        self.assertNotIn("Microsoft Word", out)
        self.assertNotIn("AcmePublisher", out)

    def test_clean_removes_leaked_path(self):
        out = self._cleaned()
        self.assertNotIn("jdoe", out)
        self.assertNotIn("file:///", out)

    def test_clean_keeps_content_meta_and_body(self):
        out = self._cleaned()
        # Descriptive metadata is the page, not its author.
        self.assertIn("A report about revenue", out)
        self.assertIn("Revenue grew", out)
        self.assertIn("sharply", out)

    def test_clean_removes_office_namespace_tags(self):
        out = self._cleaned()
        self.assertNotIn("<o:p>", out)
        self.assertNotIn("DocumentProperties", out)

    def test_clean_html_is_idempotent(self):
        once = self._cleaned()
        second = os.path.join(self.tmp, "clean2.html")
        clean_docs.clean(self.dst, second)
        with open(second, encoding="utf-8") as fh:
            self.assertEqual(once, fh.read())


class TestOdfTextExtraction(unittest.TestCase):
    def test_closing_tag_is_backreferenced(self):
        # Without a backreference the regex spans from <text:p> to </text:span>
        # and splices unrelated runs together.
        xml = "<text:p>first</text:p><text:span>second</text:span>"
        out = clean_docs._extract_odf_text(xml)
        self.assertIn("first", out)
        self.assertIn("second", out)
        self.assertNotIn("</text:p>", out)


@contextlib.contextmanager
def quiet():
    """Swallow CLI output so the test report stays readable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


class TestUnifiedCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.clean_file = os.path.join(self.tmp, "clean.txt")
        self.dirty_file = os.path.join(self.tmp, "dirty.txt")
        with open(self.clean_file, "w", encoding="utf-8") as fh:
            fh.write("Perfectly ordinary text.\n")
        with open(self.dirty_file, "w", encoding="utf-8") as fh:
            fh.write("hidden\u200bmarker\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_help_exits_zero(self):
        with quiet() as out:
            self.assertEqual(nomark.main([]), 0)
            self.assertEqual(nomark.main(["--help"]), 0)
        self.assertIn("nomark.py scan", out.getvalue())

    def test_version(self):
        with quiet() as out:
            self.assertEqual(nomark.main(["--version"]), 0)
        self.assertIn("nomark", out.getvalue())

    def test_unknown_command_exits_two(self):
        with quiet() as out:
            self.assertEqual(nomark.main(["frobnicate"]), 2)
        self.assertIn("unknown command", out.getvalue())

    def test_check_passes_on_clean_file(self):
        with quiet():
            self.assertEqual(nomark.main(["check", self.clean_file]), 0)

    def test_check_fails_on_dirty_file(self):
        with quiet():
            self.assertEqual(nomark.main(["check", self.dirty_file]), 1)

    def test_scan_subcommand_dispatches(self):
        with quiet():
            self.assertEqual(nomark.main(["scan", self.clean_file]), 0)

    def test_check_passes_when_dirty_file_is_excluded(self):
        with quiet():
            self.assertEqual(
                nomark.main(["check", self.tmp, "--exclude", "dirty.txt"]), 0)

    def test_exclude_matches_directory_prefix(self):
        sub = os.path.join(self.tmp, "fixtures")
        os.makedirs(sub)
        with open(os.path.join(sub, "marked.txt"), "w", encoding="utf-8") as fh:
            fh.write("bad​marker\n")
        with quiet():
            self.assertEqual(
                nomark.main(["check", sub, "--exclude", "fixtures"]), 0)

    def test_aliases_resolve(self):
        self.assertEqual(nomark.ALIASES["clean-text"], "text")
        self.assertEqual(nomark.ALIASES["meta"], "docs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
