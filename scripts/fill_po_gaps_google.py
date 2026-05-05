#!/usr/bin/env python3
"""Fill empty gettext slots using Google Translate (via ``deep-translator``).

Purpose: ship complete `.po` catalogs when ``ANTHROPIC_API_KEY`` is not available locally.
Prefer running Haiku afterward for QA::

    python3 -m pip install deep-translator polib
    ANTHROPIC_API_KEY=... python3 scripts/translate_po_with_haiku.py

Run from repository root::

    python3 scripts/fill_po_gaps_google.py

Options::

    python3 scripts/fill_po_gaps_google.py --dry-run
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

import polib
from babel.messages.pofile import read_po
from deep_translator import GoogleTranslator

ROOT = Path(__file__).resolve().parent.parent

PLACE_RE = re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)[a-zA-Z]|%%|%[sdrifxX]")

LOCALE_GOOGLE_TARGET = {
    "ar": "ar",
    "de": "de",
    "es": "es",
    "fr": "fr",
    "hi": "hi",
    "ja": "ja",
    "ko": "ko",
    "nl": "nl",
    "pt": "pt",
    "zh": "chinese (simplified)",
}


def placeholders(s: str) -> list[str]:
    return PLACE_RE.findall(s or "")


def universal_empty_slots() -> list[tuple[int, str]]:
    """(plural_index, english_text) empty in ar,de,es,fr,hi,ja,ko,nl,pt."""
    locales = "ar de es fr hi ja ko nl pt".split()
    key_seen: dict[tuple[int, str], set[str]] = {}
    for loc in locales:
        with (ROOT / f"translations/{loc}/LC_MESSAGES/messages.po").open(encoding="utf-8") as f:
            cat = read_po(f, locale=loc)
        for msg in cat:
            if isinstance(msg.id, tuple):
                ss = list(msg.string) if isinstance(msg.string, (list, tuple)) else []
                for i in range(len(msg.id)):
                    s = ss[i] if i < len(ss) else ""
                    if not (s or "").strip():
                        key_seen.setdefault((i, msg.id[i]), set()).add(loc)
            elif isinstance(msg.id, str) and msg.id.strip():
                s = msg.string if isinstance(msg.string, str) else ""
                if not (s or "").strip():
                    key_seen.setdefault((-1, msg.id), set()).add(loc)
    want = set(locales)
    return sorted([k for k, v in key_seen.items() if v == want], key=lambda x: (x[0], x[1]))


def locale_empty_slots(locale: str) -> list[tuple[int, str]]:
    """Empty msgstr slots for one catalog (babel view; matches polib apply)."""
    po_path = ROOT / f"translations/{locale}/LC_MESSAGES/messages.po"
    with po_path.open(encoding="utf-8") as f:
        cat = read_po(f, locale=locale)
    out: list[tuple[int, str]] = []
    for msg in cat:
        if isinstance(msg.id, tuple):
            ss = list(msg.string) if isinstance(msg.string, (list, tuple)) else []
            for i in range(len(msg.id)):
                s = ss[i] if i < len(ss) else ""
                if not (s or "").strip():
                    out.append((i, msg.id[i]))
        elif isinstance(msg.id, str) and msg.id.strip():
            s = msg.string if isinstance(msg.string, str) else ""
            if not (s or "").strip():
                out.append((-1, msg.id))
    return sorted(set(out), key=lambda x: (x[0], x[1]))


def find_po_entry(po: polib.POFile, plural_idx: int, msgid_eng: str) -> polib.POEntry | None:
    for e in po:
        if e.obsolete:
            continue
        if plural_idx == -1:
            if e.msgid_plural:
                continue
            if e.msgid == msgid_eng:
                return e
            continue
        if not getattr(e, "msgid_plural", None):
            continue
        # Missing msgstr_plural[1] in file omits key in polib; assign applies anyway.
        if plural_idx == 0 and e.msgid == msgid_eng:
            return e
        if plural_idx == 1 and e.msgid_plural == msgid_eng:
            return e
    return None


def clear_fuzzy_when_complete(entry: polib.POEntry) -> None:
    flags = getattr(entry, "flags", [])
    if "fuzzy" not in flags:
        return
    if entry.msgid_plural:
        if not entry.msgstr_plural:
            return
        if any(not (entry.msgstr_plural.get(i) or "").strip() for i in sorted(entry.msgstr_plural.keys())):
            return
    else:
        if not entry.msgstr or not entry.msgstr.strip():
            return
    entry.flags.remove("fuzzy")


def apply_translation(po: polib.POFile, plural_idx: int, msgid_eng: str, tr: str) -> bool:
    entry = find_po_entry(po, plural_idx, msgid_eng)
    if entry is None:
        print(f"  WARN row not found plural_idx={plural_idx}: {msgid_eng[:72]!r}…")
        return False

    if plural_idx >= 0:
        slot = entry.msgstr_plural.get(plural_idx, "")
        if (slot or "").strip():
            return False
        entry.msgstr_plural[plural_idx] = tr
    else:
        if (entry.msgstr or "").strip():
            return False
        entry.msgstr = tr
    clear_fuzzy_when_complete(entry)
    return True


def compile_mo() -> int:
    exe = sys.executable or "python3"
    cmd = [
        exe,
        "-m",
        "babel.messages.frontend",
        "compile",
        "-d",
        str(ROOT / "translations"),
    ]
    env = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    errs = sum(1 for ln in env.stderr.splitlines() if ln.startswith("error"))
    if env.returncode != 0 or errs:
        sys.stderr.write(env.stderr)
        return env.returncode or errs
    return 0


def chunked(seq: list, n: int):
    return [seq[i : i + n] for i in range(0, len(seq), n)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--chunk-size", type=int, default=35)
    ap.add_argument("--sleep", type=float, default=0.35)
    ap.add_argument("--locales", nargs="*", default=None,
                    help="Subset of locales (default: 9 latin-family + zh)")
    ap.add_argument(
        "--only-universal",
        action="store_true",
        help="Only keys empty in all nine of ar,de,es,fr,hi,ja,ko,nl,pt (not per-locale)",
    )
    ap.add_argument("--only-zh", action="store_true", help="Only fill Chinese catalog")
    args = ap.parse_args()

    universal_list = universal_empty_slots()
    print(f"universal-empty (9 locales): {len(universal_list)}", flush=True)

    nine = sorted("ar de es fr hi ja ko nl pt".split())
    if args.only_zh:
        candidates = ["zh"]
    elif args.only_universal:
        candidates = nine[:]
    else:
        candidates = nine + ["zh"]
    locales = [loc for loc in candidates if loc in set(args.locales)] if args.locales else candidates[:]

    total_mismatch = 0
    for loc in locales:
        po_path = ROOT / "translations" / loc / "LC_MESSAGES" / "messages.po"
        if not po_path.exists():
            print(f"skip {loc} — missing .po")
            continue
        tgt = LOCALE_GOOGLE_TARGET[loc]
        items = universal_list if args.only_universal else locale_empty_slots(loc)
        print(f"{loc}-empty: {len(items)}", flush=True)
        if not items:
            continue

        print(f"\n== {loc} → {tgt} ({len(items)} units) ==", flush=True)
        po = polib.pofile(str(po_path))
        src_texts = [t for _, t in items]
        tl = GoogleTranslator(source="en", target=tgt)
        translated: list[str] = []

        if args.dry_run:
            translated = list(src_texts)
        else:
            for batch in chunked(src_texts, args.chunk_size):
                try:
                    translated.extend(tl.translate_batch(batch))
                except Exception as exc:
                    print(f"  batch failed ({exc}); item-by-item", flush=True)
                    for s in batch:
                        try:
                            translated.append(tl.translate(s))
                        except Exception as exc2:
                            print(f"    FAIL {s[:60]!r}… ({exc2})", flush=True)
                            translated.append(s)
                time.sleep(args.sleep)

        if len(translated) != len(items):
            print(f"FATAL len translated={len(translated)} items={len(items)}")
            return 1

        applied = 0
        mm_here = 0
        for (pll, mid), tr in zip(items, translated, strict=True):
            if placeholders(mid) != placeholders(tr):
                print(f"  PLACEHOLDER skip: {mid[:66]!r}…")
                mm_here += 1
                total_mismatch += 1
                continue
            if apply_translation(po, pll, mid, tr):
                applied += 1

        if not args.dry_run:
            po.save(str(po_path))
            print(f"  saved applied={applied} placeholder_skips={mm_here}")

    if not args.dry_run:
        print("\nCompiling .mo …")
        if compile_mo() != 0:
            return 1

    return 1 if total_mismatch > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
