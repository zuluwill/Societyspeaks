#!/usr/bin/env python3
"""
HTTP probe for optional-reading URLs: country packs (journey_reading_enrichment.py)
plus the global curriculum (journey_seed.get_curriculum(\"global\")).

Run from repository root:
  PYTHONPATH=. python3 scripts/verify_journey_reading_links.py

CI / scheduling: see .github/workflows/journey-reading-links.yml

Environment:
  JOURNEY_READING_LINK_STRICT=1 — treat HTTP 401/403 as failures (default: warn only).

TLS uses the certifi CA bundle when installed (see requirements.txt) so checks match CI/Linux.
If DATABASE_URL is unset, a temporary sqlite URL is set so config can import (this script does not use the DB).
"""
from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Importing app.* loads config.Config, which requires DATABASE_URL at import time.
if not (os.environ.get("DATABASE_URL") or "").strip():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.programmes.journey_reading_link_probe import ProbeOutcome, probe_url  # noqa: E402
from app.programmes.journey_reading_url_index import (  # noqa: E402
    ReadingPackUrlRef,
    reading_packs_for_link_audit,
    refs_by_normalized_url,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=25.0, help="Per-request timeout seconds")
    parser.add_argument("--workers", type=int, default=14, help="Parallel probes (default 14)")
    parser.add_argument(
        "--strict-forbidden",
        action="store_true",
        help="Treat HTTP 401/403 as failures (also set JOURNEY_READING_LINK_STRICT=1)",
    )
    parser.add_argument(
        "--max-urls",
        type=int,
        default=0,
        metavar="N",
        help="Probe at most N unique URLs (0 = all). For quick smoke tests only.",
    )
    args = parser.parse_args(argv)

    strict = args.strict_forbidden or os.environ.get("JOURNEY_READING_LINK_STRICT", "").strip() in (
        "1",
        "true",
        "yes",
    )

    grouped = refs_by_normalized_url(reading_packs_for_link_audit())
    all_urls = sorted(grouped.keys(), key=lambda u: u.lower())
    total_unique = len(all_urls)
    urls = all_urls
    if args.max_urls and args.max_urls > 0:
        urls = all_urls[: args.max_urls]
    total_refs = sum(len(v) for v in grouped.values())
    if len(urls) < total_unique:
        print(
            f"Journey reading packs: probing {len(urls)} of {total_unique} unique URLs "
            f"({total_refs} total references)\n"
        )
    else:
        print(f"Journey reading packs: {len(urls)} unique URLs ({total_refs} references)\n")

    failures: List[Tuple[str, ProbeOutcome, List[ReadingPackUrlRef]]] = []
    warnings: List[Tuple[str, ProbeOutcome, List[ReadingPackUrlRef]]] = []

    def work(normalized_url: str) -> Tuple[str, ProbeOutcome]:
        sample = grouped[normalized_url][0].url
        return normalized_url, probe_url(sample, args.timeout)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(work, u): u for u in urls}
        for fut in as_completed(futures):
            normalized_url, outcome = fut.result()
            refs = grouped[normalized_url]
            if outcome.ok:
                print(f"OK  {outcome.status}  {refs[0].url[:90]}{'…' if len(refs[0].url) > 90 else ''}")
                continue
            if outcome.soft_forbidden and not strict:
                warnings.append((normalized_url, outcome, refs))
                print(
                    f"WARN {outcome.message}  {refs[0].url[:90]}{'…' if len(refs[0].url) > 90 else ''} "
                    "(auth/geo wall — set JOURNEY_READING_LINK_STRICT=1 to fail)"
                )
                continue
            failures.append((normalized_url, outcome, refs))
            print(f"FAIL {outcome.message}  {refs[0].url}")

    if warnings:
        print(f"\n{len(warnings)} URL(s) returned 401/403 (not counted as failures unless --strict-forbidden).")

    if failures:
        print(f"\n{len(failures)} URL probe failure(s):\n")
        for _norm, outcome, refs in failures:
            print(f"  {outcome.message} — {refs[0].url}")
            for r in refs[:12]:
                print(f"    - {r.context_line()}")
            if len(refs) > 12:
                print(f"    - … and {len(refs) - 12} more reference(s)")
            print()
        return 1

    print("\nAll probed URLs OK (or only soft 401/403 warnings).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
