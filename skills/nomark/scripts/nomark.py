#!/usr/bin/env python3
"""
nomark -- one entry point for all three tools.

    python nomark.py scan   FILE      report watermarks, change nothing
    python nomark.py text   FILE      clean invisible/confusable characters
    python nomark.py docs   FILE      strip document metadata
    python nomark.py check  PATH      CI gate: exit 1 if anything is found

Each subcommand forwards every remaining argument to the underlying tool, so
`nomark.py text FILE --profile safe --in-place` behaves exactly like calling
clean_text.py directly. The individual scripts remain usable on their own.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

USAGE = __doc__.strip()

COMMANDS = {
    "scan": ("scan", "report watermark artefacts without changing anything"),
    "text": ("clean_text", "clean text files or stdin"),
    "docs": ("clean_docs", "strip metadata from documents"),
}
ALIASES = {
    "clean-text": "text",
    "clean_text": "text",
    "clean-docs": "docs",
    "clean_docs": "docs",
    "meta": "docs",
}


def _run_check(argv):
    """Scan quietly and exit non-zero if anything turns up. For CI hooks."""
    import scan as scan_mod

    args = list(argv)
    if "--quiet" not in args:
        args.append("--quiet")
    found = scan_mod.main(args)
    if found:
        print("nomark: watermark artefacts found", file=sys.stderr)
    return found


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if argv[0] in ("-V", "--version", "version"):
        from nomark_lib import __version__
        print("nomark %s" % __version__)
        return 0

    command = ALIASES.get(argv[0], argv[0])
    rest = argv[1:]

    if command == "check":
        return _run_check(rest)

    if command not in COMMANDS:
        print("nomark: unknown command %r\n" % argv[0], file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2

    module_name = COMMANDS[command][0]
    module = __import__(module_name)
    return module.main(rest)


if __name__ == "__main__":
    sys.exit(main())
