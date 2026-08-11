#!/usr/bin/env python3
"""
nomark clean-text -- strip watermark artefacts from text files or stdin.

Writes to stdout by default so nothing is destroyed by accident. Pass
--in-place to rewrite files, optionally keeping a .bak alongside.

Profiles:
    safe        invisible characters only; never alters a visible glyph.
                Correct for source code, JSON, CSV, and anything parsed.
    standard    safe + exotic spaces, mixed-script homoglyphs, and
                typographic punctuation. The default for prose.
    aggressive  standard + NFKC normalisation, whitespace collapsing,
                and every mapped homoglyph folded regardless of context.

Examples:
    python scripts/clean_text.py essay.md
    python scripts/clean_text.py essay.md --in-place --backup
    python scripts/clean_text.py src/ --ext .py --profile safe --in-place
    pbpaste | python scripts/clean_text.py - --profile aggressive
    python scripts/clean_text.py essay.md --dash-style comma --diff
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nomark_lib import (  # noqa: E402
    DASH_STYLES,
    PROFILES,
    clean_text,
    enable_utf8_stdio,
    format_report,
)
from scan import SKIP_DIRS, TEXT_EXTS, collect, read_text  # noqa: E402


def _escape(line: str) -> str:
    """Escape non-ASCII so that removed invisible characters are readable.

    A diff of invisible-character removal is otherwise two identical-looking
    lines, which is worse than no diff at all.
    """
    return line.rstrip("\n").encode("unicode_escape").decode("ascii")


def show_diff(before: str, after: str, path: str) -> None:
    """Print a unified diff with non-ASCII escaped."""
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=path + " (before)",
        tofile=path + " (after)",
        lineterm="",
        n=1,
    )
    for line in diff:
        if line.startswith(("---", "+++", "@@")):
            print(line)
        else:
            print(line[0] + _escape(line[1:]))


def process_one(path: str, args: argparse.Namespace) -> Optional[bool]:
    """Clean one file. Returns True if it changed, None if it was skipped."""
    text = read_text(path)
    if text is None:
        return None

    cleaned, report = clean_text(
        text,
        profile=args.profile,
        dash_style=args.dash_style,
        collapse_whitespace=args.collapse if args.collapse else None,
    )
    changed = cleaned != text

    if args.report or args.in_place:
        print(format_report(report, path, args.show_low), file=sys.stderr)

    if args.diff and changed:
        show_diff(text, cleaned, path)

    if args.in_place:
        if not changed:
            return False
        if args.dry_run:
            print("  would rewrite %s" % path, file=sys.stderr)
            return True
        if args.backup:
            shutil.copy2(path, path + ".bak")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(cleaned)
        return True

    if not args.diff:
        sys.stdout.write(cleaned)
    return changed


def main(argv: Optional[List[str]] = None) -> int:
    enable_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="nomark clean-text",
        description="Remove watermark artefacts from text.",
    )
    parser.add_argument("paths", nargs="+",
                        help="files, directories, or - for stdin")
    parser.add_argument("--profile", choices=PROFILES, default="standard",
                        help="how much to change (default: standard)")
    parser.add_argument("--dash-style", choices=sorted(DASH_STYLES), default="hyphen",
                        help="what to replace em dashes with (default: hyphen)")
    parser.add_argument("--in-place", action="store_true",
                        help="rewrite files instead of printing to stdout")
    parser.add_argument("--backup", action="store_true",
                        help="with --in-place, keep the original as FILE.bak")
    parser.add_argument("--dry-run", action="store_true",
                        help="with --in-place, report what would change only")
    parser.add_argument("--diff", action="store_true",
                        help="show a unified diff with escapes instead of output")
    parser.add_argument("--report", action="store_true",
                        help="print a findings report to stderr")
    parser.add_argument("--show-low", action="store_true",
                        help="include low-severity findings in the report")
    parser.add_argument("--collapse", action="store_true",
                        help="collapse repeated spaces and blank lines")
    parser.add_argument("--ext", default=None,
                        help="comma-separated extensions when given a directory")
    parser.add_argument("--no-recurse", action="store_true",
                        help="do not descend into subdirectories")
    parser.add_argument("--exclude", action="append", default=None,
                        metavar="GLOB",
                        help="skip paths matching this glob; repeatable")
    args = parser.parse_args(argv)

    if args.backup and not args.in_place:
        parser.error("--backup only applies with --in-place")
    if args.dry_run and not args.in_place:
        parser.error("--dry-run only applies with --in-place")

    if args.paths == ["-"]:
        text = sys.stdin.read()
        cleaned, report = clean_text(
            text,
            profile=args.profile,
            dash_style=args.dash_style,
            collapse_whitespace=args.collapse if args.collapse else None,
        )
        if args.report:
            print(format_report(report, "<stdin>", args.show_low), file=sys.stderr)
        sys.stdout.write(cleaned)
        return 0

    exts = None
    if args.ext:
        exts = {e if e.startswith(".") else "." + e
                for e in (x.strip().lower() for x in args.ext.split(",")) if e}
    elif any(os.path.isdir(p) for p in args.paths):
        exts = TEXT_EXTS

    files = collect(args.paths, exts, not args.no_recurse, args.exclude)
    if not files:
        print("no matching files", file=sys.stderr)
        return 0

    if len(files) > 1 and not (args.in_place or args.diff):
        parser.error("refusing to concatenate %d files to stdout; "
                     "use --in-place or --diff" % len(files))

    changed_count = 0
    for path in files:
        result = process_one(path, args)
        if result:
            changed_count += 1

    if args.in_place:
        verb = "would change" if args.dry_run else "changed"
        print("%s %d of %d file(s)" % (verb, changed_count, len(files)),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
