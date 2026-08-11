#!/usr/bin/env python3
"""
Generate a deliberately watermarked sample file for trying NoMark out.

The sample carries every artefact class the tool handles, so that
`scan.py` produces a full report on a fresh clone:

    python examples/make_sample.py
    python skills/nomark/scripts/scan.py examples/watermarked_sample.md --show-low
    python skills/nomark/scripts/clean_text.py examples/watermarked_sample.md --diff
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "watermarked_sample.md")


def tag_encode(payload: str) -> str:
    """Encode ASCII into the invisible Unicode tag block (U+E0000..U+E007F)."""
    return "".join(chr(0xE0000 + ord(c)) for c in payload)


def varsel_encode(payload: str) -> str:
    """Encode bytes into variation selectors, which hide behind any glyph."""
    out = []
    for byte in payload.encode("utf-8"):
        out.append(chr(0xFE00 + byte) if byte < 16 else chr(0xE0100 + byte - 16))
    return "".join(out)


def build() -> str:
    zwsp = "​"       # zero width space
    nbsp = " "       # no-break space
    nnbsp = " "      # narrow no-break space
    shy = "­"        # soft hyphen
    bom = "﻿"        # zero width no-break space
    rlo = "‮"        # right-to-left override
    cyr_o = "о"      # Cyrillic o, identical to Latin o
    cyr_a = "а"      # Cyrillic a
    grk_p = "ρ"      # Greek rho, identical to Latin p

    return (
        "# Quarterly Rep" + shy + "ort\n"
        "\n"
        "It" + "’" + "s worth noting that this document" + zwsp +
        " represents a comprehensive" + nbsp + "overview of our findings"
        + tag_encode("recipient=4471;copy=b") + ".\n"
        "\n"
        "The p" + cyr_a + "ssw" + cyr_o + "rd policy" + zwsp +
        " was u" + grk_p + "dated in March" + nnbsp + "2026, and the "
        "results" + "—" + "crucially" + "—" + " exceeded "
        "expectations" + "…" + "\n"
        "\n"
        + bom + "Three themes emerged: clarity, consistency, and rigour.\n"
        "\n"
        "Contact the team" + rlo + " for details." +
        "\U0001f600" + varsel_encode("trace-id:88f2") + "\n"
        "\n"
        "> " + "“" + "A testament to the team" + "’" + "s "
        "dedication." + "”" + "\n"
    )


def main() -> None:
    text = build()
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print("wrote %s (%d characters, %d bytes)"
          % (OUT, len(text), len(text.encode("utf-8"))))
    print("the file looks ordinary; run scan.py to see what is in it")


if __name__ == "__main__":
    main()
