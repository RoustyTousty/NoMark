#!/usr/bin/env python3
"""
nomark scan -- report watermark artefacts without changing anything.

Reads files, directories, or stdin and prints what it finds. Detection only;
nothing is written. Use clean_text.py or clean_docs.py to act on the results.

Examples:
    python scripts/scan.py essay.md
    python scripts/scan.py src/ --ext .py,.md --show-low
    cat clipboard.txt | python scripts/scan.py -
    python scripts/scan.py report.docx          # inspects metadata too
    python scripts/scan.py notes/ --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nomark_lib import (  # noqa: E402
    Report,
    enable_utf8_stdio,
    format_report,
    scan_text,
)

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".html", ".htm", ".xml", ".json",
    ".yaml", ".yml", ".toml", ".csv", ".tsv", ".py", ".js", ".mjs", ".ts",
    ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp", ".cs",
    ".rb", ".php", ".sh", ".bash", ".zsh", ".ps1", ".sql", ".css", ".scss",
    ".tex", ".bib", ".srt", ".vtt", ".ini", ".cfg", ".conf", ".env",
}

DOC_EXTS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp", ".epub", ".pdf"}
# HTML is scanned as text *and* inspected for metadata, so it is routed to the
# document inspector even though it is a plain-text format.
HTML_EXTS = {".html", ".htm", ".xhtml"}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".cache", "target", ".mypy_cache", ".pytest_cache",
}


def read_text(path: str) -> Optional[str]:
    """Read a file as UTF-8, returning None if it is binary or unreadable."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        print("  ! cannot read %s: %s" % (path, exc), file=sys.stderr)
        return None
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return None


def _excluded(path: str, patterns: List[str]) -> bool:
    """True if `path` matches any exclude glob.

    Each pattern is tested against every trailing sub-path, not just the whole
    string, so `--exclude 'tests/*'` behaves the same whether the scan was
    rooted at the repo (`tests/x.py`) or handed an absolute path
    (`/home/me/proj/tests/x.py`). A bare name like `fixtures` therefore
    excludes any directory of that name at any depth, matching how .gitignore
    behaves and how people expect it to.

    Separators are normalised to `/` first so one pattern works on Windows and
    POSIX alike.
    """
    if not patterns:
        return False
    norm = path.replace(os.sep, "/").lstrip("./")
    parts = norm.split("/")
    for pattern in patterns:
        pat = pattern.replace(os.sep, "/").rstrip("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            if fnmatch.fnmatch(suffix, pat) or fnmatch.fnmatch(suffix, pat + "/*"):
                return True
    return False


def collect(
    paths: List[str],
    exts: Optional[set],
    recurse: bool,
    exclude: Optional[List[str]] = None,
) -> List[str]:
    """Expand the given paths into a concrete list of files to inspect."""
    found: List[str] = []
    for path in paths:
        if os.path.isfile(path):
            found.append(path)
        elif os.path.isdir(path):
            if not recurse:
                for entry in sorted(os.listdir(path)):
                    full = os.path.join(path, entry)
                    if os.path.isfile(full):
                        found.append(full)
                continue
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for name in sorted(files):
                    found.append(os.path.join(root, name))
        else:
            print("  ! no such path: %s" % path, file=sys.stderr)

    if exts is not None:
        found = [f for f in found if os.path.splitext(f)[1].lower() in exts]
    else:
        allowed = TEXT_EXTS | DOC_EXTS
        found = [f for f in found if os.path.splitext(f)[1].lower() in allowed
                 or os.path.splitext(f)[1] == ""]

    if exclude:
        found = [f for f in found if not _excluded(f, exclude)]
    return found


def scan_document(path: str) -> Tuple[Report, List[str]]:
    """Delegate container formats to clean_docs for metadata inspection."""
    notes: List[str] = []
    try:
        import clean_docs
    except ImportError:
        return Report(), ["metadata scan unavailable (clean_docs.py not found)"]
    try:
        report, extra = clean_docs.inspect(path)
        return report, extra + notes
    except Exception as exc:  # a malformed document should not abort a sweep
        return Report(), ["metadata scan failed: %s" % exc]


def to_json(path: str, report: Report, notes: List[str]) -> dict:
    return {
        "path": path,
        "clean": report.clean and not notes,
        "counts": report.counts_by_kind(),
        "findings": [
            {
                "kind": f.kind,
                "name": f.name,
                "codepoint": ("U+%04X" % f.codepoint) if f.codepoint else None,
                "line": f.line,
                "column": f.col,
                "severity": f.severity,
                "detail": f.detail,
            }
            for f in report.findings
        ],
        "decoded_payloads": report.decoded_payloads,
        "metadata_notes": notes,
    }


def main(argv: Optional[List[str]] = None) -> int:
    enable_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="nomark scan",
        description="Report watermark artefacts in text and documents.",
    )
    parser.add_argument("paths", nargs="+",
                        help="files, directories, or - for stdin")
    parser.add_argument("--ext", default=None,
                        help="comma-separated extensions to include, e.g. .md,.txt")
    parser.add_argument("--no-recurse", action="store_true",
                        help="do not descend into subdirectories")
    parser.add_argument("--exclude", action="append", default=None,
                        metavar="GLOB",
                        help="skip paths matching this glob; repeatable. "
                             "Needed to gate a repo that keeps deliberately "
                             "watermarked fixtures, e.g. --exclude 'tests/*'")
    parser.add_argument("--show-low", action="store_true",
                        help="include low-severity findings (typography, etc.)")
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON")
    parser.add_argument("--quiet", action="store_true",
                        help="only print files that have findings")
    args = parser.parse_args(argv)

    exts = None
    if args.ext:
        exts = {e if e.startswith(".") else "." + e
                for e in (x.strip().lower() for x in args.ext.split(",")) if e}

    results = []
    total_findings = 0

    if args.paths == ["-"]:
        text = sys.stdin.read()
        report = scan_text(text)
        total_findings += len([f for f in report.findings
                               if args.show_low or f.severity != "low"])
        if args.json:
            results.append(to_json("<stdin>", report, []))
        else:
            print(format_report(report, "<stdin>", args.show_low))
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        return 1 if total_findings else 0

    files = collect(args.paths, exts, not args.no_recurse, args.exclude)
    if not files:
        print("no matching files", file=sys.stderr)
        return 0

    for path in files:
        ext = os.path.splitext(path)[1].lower()
        notes: List[str] = []

        if ext in DOC_EXTS or ext in HTML_EXTS:
            report, notes = scan_document(path)
        else:
            text = read_text(path)
            if text is None:
                continue
            report = scan_text(text)

        visible = [f for f in report.findings
                   if args.show_low or f.severity != "low"]
        total_findings += len(visible)
        has_output = bool(visible or report.decoded_payloads or notes)

        if args.json:
            results.append(to_json(path, report, notes))
            continue
        if args.quiet and not has_output:
            continue

        print(format_report(report, path, args.show_low))
        for note in notes:
            print("  [M] %s" % note)
        print()

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    elif not args.quiet:
        print("scanned %d file(s), %d finding(s)" % (len(files), total_findings))

    return 1 if total_findings else 0


if __name__ == "__main__":
    sys.exit(main())
