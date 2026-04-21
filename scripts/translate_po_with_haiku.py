"""Batch-translate empty msgstr entries in translations/*/LC_MESSAGES/messages.po
using Claude Haiku.

Usage:
    ANTHROPIC_API_KEY=sk-ant-... python3 scripts/translate_po_with_haiku.py
    # Optional flags:
    #   --locales fr es ar          Only these locales (default: all non-English)
    #   --batch-size 40             msgids per API call (default 40)
    #   --limit 500                 Max msgids to translate per locale (for testing)
    #   --dry-run                   Show what would translate, don't call the API
    #   --model claude-haiku-4-5    Override the model
    #   --only-new                  Skip fuzzy entries (only translate empty msgstr)
    #   --fail-fast                 Stop on first API error

Strategy:
    1. Loop every `translations/<lang>/LC_MESSAGES/messages.po`.
    2. Collect empty (and by default, fuzzy) msgstr entries.
    3. Batch them (JSON array) into Haiku with a strict system prompt that
       tells it: preserve %(name)s placeholders, %%, inline HTML tags, and
       newlines. Ask for JSON array response with identical length.
    4. Validate each returned translation has the same set of placeholders
       as the source; skip + log any that don't match.
    5. Write translations back to the .po file in-place, stripping the
       fuzzy flag.
    6. After every locale, run `pybabel compile -d translations` for that
       locale so failures surface immediately.

Idempotent: safe to rerun. Only touches empty / fuzzy entries.
Cost: with ~5,600 msgids × 10 locales in batches of 40 ≈ 1,400 Haiku calls
total (first run only — reruns skip already-translated entries).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Tuple

try:
    import polib
except ImportError:
    sys.stderr.write("pip install polib\n"); sys.exit(2)


LANG_NAMES = {
    "es": "Spanish",
    "nl": "Dutch",
    "zh": "Chinese (Simplified)",
    "de": "German",
    "fr": "French",
    "ja": "Japanese",
    "pt": "Portuguese",
    "ar": "Arabic",
    "hi": "Hindi",
    "ko": "Korean",
}


PLACE_RE = re.compile(r"%\([A-Za-z_][A-Za-z0-9_]*\)[a-zA-Z]|%%|%[sdrifxX]")


def placeholders_of(s: str) -> List[str]:
    return PLACE_RE.findall(s or "")


SYSTEM_PROMPT = """You are a senior localization expert translating UI strings for Society Speaks,
a civic-tech platform for structured public deliberation.

Rules — follow exactly:
1. Translate from English into {lang_name} with natural, contemporary phrasing
   appropriate for a civic / news / democracy product.
2. NEVER translate, remove, or reorder printf-style placeholders. These MUST appear
   verbatim in the translation:
     - %(name)s, %(name)d, %(num)d, %(count)s, %(email)s, %(date)s, etc.
     - %s, %d, %%
   If the source has `%(num)d statements`, the translation must include
   `%(num)d` intact.
3. NEVER translate HTML tags. Keep `<strong>`, `<em>`, `<a href="...">`, `<br>`,
   `<code>` etc. intact. Only translate the visible text between tags.
4. NEVER translate brand names: "Society Speaks", "Pol.is", "Claude", "ChatGPT",
   "Perplexity", "LinkedIn", "X", "BlueSky", "WhatsApp", "Telegram", "Meta",
   "Stripe", "GitHub", "Replit", "Google", "Anthropic", "OpenAI", "Resend",
   "AllSides", "BBC", "Reuters", "The Guardian", "Financial Times",
   "The Economist", "The Times", "New York Times", "Washington Post",
   "Wall Street Journal", "ProPublica", "Bloomberg", "National Review",
   "Cato Institute", "vTaiwan", "SocietySpeaks.io".
5. NEVER translate technical identifiers: URLs, email addresses, HTTP verbs
   (GET/POST), JSON keys, CSS class names, code snippets in backticks.
6. Keep the same tone: direct, warm, respectful. Match sentence length
   approximately; avoid over-expansion or padding.
7. Return the translations as a JSON array of strings in the same order as the
   input. No prose, no explanation, no markdown. Only the JSON array.

Example:
  Input:  ["Vote", "Welcome %(name)s!", "Read our <a href=\\"/terms\\">terms</a>"]
  Output: ["Voter", "Bienvenue %(name)s\u00a0!", "Lisez nos <a href=\\"/terms\\">conditions</a>"]
"""


def build_request_payload(lang_name: str, msgids: List[str]) -> Tuple[str, str]:
    system = SYSTEM_PROMPT.format(lang_name=lang_name)
    user = json.dumps(msgids, ensure_ascii=False)
    return system, user


def call_haiku(client, model: str, system: str, user: str) -> List[str]:
    resp = client.messages.create(
        model=model,
        max_tokens=8192,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    # Strip ```json fences if the model adds them
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        arr = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Haiku returned non-JSON: {e}\n{text[:500]}")
    if not isinstance(arr, list):
        raise RuntimeError(f"Haiku returned non-list: {type(arr).__name__}")
    return [str(x) for x in arr]


def validate_translation(src: str, tr: str) -> bool:
    """Return True iff tr preserves the same multiset of placeholders as src."""
    src_ph = sorted(placeholders_of(src))
    tr_ph = sorted(placeholders_of(tr))
    return src_ph == tr_ph


def plural_entries(entry) -> List[Tuple[str, int]]:
    """For a plural entry, return (text, index) pairs for each msgstr_plural slot."""
    if not entry.msgid_plural:
        return [(entry.msgid, -1)]
    # Single + plural msgid mapped to multiple msgstr_plural[i] slots.
    # Most target languages only need 2 forms; some (ar, ru) need more.
    return [(entry.msgid, 0), (entry.msgid_plural, 1)]


def collect_pending(pofile: polib.POFile, only_new: bool) -> List[Tuple[polib.POEntry, str, int]]:
    """Return (entry, msgid_text, plural_index) for each empty/fuzzy msgstr slot."""
    pending = []
    for entry in pofile:
        if entry.obsolete:
            continue
        is_fuzzy = "fuzzy" in entry.flags
        if entry.msgid_plural:
            # plural: multiple msgstr_plural slots
            for i, ms in sorted(entry.msgstr_plural.items()):
                if ms.strip() and (only_new or not is_fuzzy):
                    continue
                src = entry.msgid if i == 0 else entry.msgid_plural
                pending.append((entry, src, i))
        else:
            if entry.msgstr.strip() and (only_new or not is_fuzzy):
                continue
            pending.append((entry, entry.msgid, -1))
    return pending


def apply_translation(entry: polib.POEntry, translation: str, plural_idx: int):
    if plural_idx == -1:
        entry.msgstr = translation
    else:
        entry.msgstr_plural[plural_idx] = translation
    if "fuzzy" in entry.flags:
        entry.flags.remove("fuzzy")


def translate_locale(
    client,
    model: str,
    pofile_path: Path,
    lang_code: str,
    batch_size: int,
    limit: int | None,
    only_new: bool,
    dry_run: bool,
    fail_fast: bool,
) -> dict:
    pofile = polib.pofile(str(pofile_path))
    lang_name = LANG_NAMES.get(lang_code, lang_code)
    pending = collect_pending(pofile, only_new=only_new)
    if limit:
        pending = pending[:limit]
    if not pending:
        return {"translated": 0, "skipped": 0, "total_pending": 0}
    print(f"  [{lang_code}] {len(pending)} pending msgids (of {len(pofile)} entries)")

    translated = 0
    skipped = 0
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        msgids = [item[1] for item in batch]
        if dry_run:
            print(f"  [{lang_code}] would translate batch {start // batch_size + 1} "
                  f"({len(msgids)} msgids)")
            continue
        system, user = build_request_payload(lang_name, msgids)
        for attempt in range(3):
            try:
                translations = call_haiku(client, model, system, user)
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"    attempt {attempt + 1}/3 failed ({e}); sleeping {wait}s")
                time.sleep(wait)
        else:
            if fail_fast:
                raise RuntimeError(f"Gave up on batch {start} in {lang_code}")
            print(f"    [{lang_code}] batch {start} permanently failed, skipping")
            skipped += len(batch)
            continue
        if len(translations) != len(msgids):
            msg = (f"    [{lang_code}] batch size mismatch: "
                   f"{len(translations)} back vs {len(msgids)} out; skipping batch")
            if fail_fast:
                raise RuntimeError(msg)
            print(msg)
            skipped += len(batch)
            continue
        for (entry, src, plural_idx), tr in zip(batch, translations):
            if not validate_translation(src, tr):
                print(f"    [{lang_code}] placeholder mismatch, skipping: "
                      f"{src[:60]!r} → {tr[:60]!r}")
                skipped += 1
                continue
            apply_translation(entry, tr, plural_idx)
            translated += 1
        # Save progress after every batch (robust against Ctrl-C / rate limits)
        pofile.save(str(pofile_path))
        # Tiny pause to be gentle on rate limits
        time.sleep(0.3)

    print(f"  [{lang_code}] translated={translated} skipped={skipped}")
    return {"translated": translated, "skipped": skipped, "total_pending": len(pending)}


def run_pybabel_compile() -> int:
    try:
        r = subprocess.run(
            ["pybabel", "compile", "-d", "translations"],
            check=False, capture_output=True, text=True,
        )
        if r.returncode != 0 or "error" in r.stderr.lower():
            print(r.stderr)
            return r.returncode or 1
        print(r.stderr.strip())
        return 0
    except FileNotFoundError:
        print("pybabel not on PATH — skipping compile")
        return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--locales", nargs="*", default=None,
                   help="Locales to translate (default: all non-English)")
    p.add_argument("--batch-size", type=int, default=40)
    p.add_argument("--limit", type=int, default=None,
                   help="Max msgids to translate per locale (useful for testing)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--model", default="claude-haiku-4-5-20251001",
                   help="Anthropic model id")
    p.add_argument("--only-new", action="store_true",
                   help="Only translate empty msgstr; skip fuzzy entries")
    p.add_argument("--fail-fast", action="store_true")
    p.add_argument("--skip-compile", action="store_true",
                   help="Do not run pybabel compile at the end")
    args = p.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        sys.stderr.write("Set ANTHROPIC_API_KEY or use --dry-run\n")
        return 2

    client = None
    if not args.dry_run:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

    trans_dir = Path("translations")
    if not trans_dir.is_dir():
        sys.stderr.write("translations/ not found; run from repo root\n"); return 2
    locales = args.locales or sorted(
        d.name for d in trans_dir.iterdir() if d.is_dir() and d.name != "en"
    )

    total = {"translated": 0, "skipped": 0, "total_pending": 0}
    for lang in locales:
        po = trans_dir / lang / "LC_MESSAGES" / "messages.po"
        if not po.exists():
            print(f"skipping {lang} (no .po)"); continue
        print(f"\n== {lang} ==")
        stats = translate_locale(
            client, args.model, po, lang,
            batch_size=args.batch_size, limit=args.limit,
            only_new=args.only_new, dry_run=args.dry_run,
            fail_fast=args.fail_fast,
        )
        for k in total: total[k] += stats[k]

    print(f"\n=== totals: translated={total['translated']} "
          f"skipped={total['skipped']} total_pending={total['total_pending']}")

    if not args.dry_run and not args.skip_compile:
        print("\nCompiling .mo catalogs...")
        rc = run_pybabel_compile()
        if rc != 0:
            sys.stderr.write("pybabel compile reported errors above\n")
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
