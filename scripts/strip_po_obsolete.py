#!/usr/bin/env python3
"""
Remove GNU gettext obsolete entries from .po files (lines prefixed with #~).

Obsolete blocks often duplicate live msgids after pybabel update; GNU gettext
0.26+ rejects those with msgfmt -c. Strip #~ lines first, then msgattrib -c /
msgfmt -c can validate the catalog.

Usage:
  python3 scripts/strip_po_obsolete.py              # strip all translations/*/LC_MESSAGES/messages.po
  python3 scripts/strip_po_obsolete.py --check    # dry-run: print paths that would change
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def strip_obsolete_lines(text: str) -> str:
    out_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("#~"):
            continue
        out_lines.append(line)
    return "".join(out_lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write files; exit 1 if any file would change",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent / "translations"
    pos = sorted(root.glob("*/LC_MESSAGES/messages.po"))
    if not pos:
        print("No translations/*/LC_MESSAGES/messages.po found", file=sys.stderr)
        return 1

    changed = False
    for po in pos:
        text = po.read_text(encoding="utf-8")
        new_text = strip_obsolete_lines(text)
        if new_text != text:
            changed = True
            if args.check:
                print(f"would strip: {po}")
            else:
                po.write_text(new_text, encoding="utf-8")
                print(f"stripped obsolete lines: {po}")
        elif not args.check:
            print(f"unchanged: {po}")

    if args.check:
        if changed:
            print(
                "\nObsolete #~ lines found in .po files. Fix with:\n"
                "  python3 scripts/strip_po_obsolete.py\n"
                "Prefer prevention: pybabel update --ignore-obsolete (see scripts/compile_translations.sh).\n",
                file=sys.stderr,
            )
            return 1
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
