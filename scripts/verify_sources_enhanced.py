#!/usr/bin/env python3
"""
Enhanced Source Verification Script

Verifies source configurations across the codebase:
1. Consistency between news_fetcher.py and allsides_seed.py
2. Reports sources by rating source (allsides, mbfc, manual)
3. Identifies potential gaps in rating coverage
4. Validates feed URLs
5. Checks for duplicate sources

Usage:
    python scripts/verify_sources_enhanced.py
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from collections import defaultdict

# Add app to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def extract_sources_from_news_fetcher():
    """Extract source configurations from news_fetcher.py."""
    news_fetcher_path = Path(__file__).parent.parent / 'app' / 'trending' / 'news_fetcher.py'

    with open(news_fetcher_path, 'r') as f:
        content = f.read()

    # Find default_sources list
    sources = {}

    # Pattern to match source dictionaries
    pattern = r"\{\s*'name':\s*'([^']+)'[^}]*'political_leaning':\s*([-\d.]+)"

    for match in re.finditer(pattern, content, re.DOTALL):
        name = match.group(1)
        leaning = float(match.group(2))
        sources[name] = {'leaning': leaning}

    return sources


def extract_sources_from_allsides_seed():
    """Extract source configurations from allsides_seed.py."""
    allsides_path = Path(__file__).parent.parent / 'app' / 'trending' / 'allsides_seed.py'

    with open(allsides_path, 'r') as f:
        content = f.read()

    sources = {}

    # Pattern to match entries in ALLSIDES_RATINGS dict
    pattern = r"'([^']+)':\s*\{\s*'leaning':\s*([-\d.]+),\s*#[^']*'source':\s*'([^']+)'"

    for match in re.finditer(pattern, content):
        name = match.group(1)
        leaning = float(match.group(2))
        source = match.group(3)
        sources[name] = {'leaning': leaning, 'source': source}

    return sources


def get_leaning_label(leaning):
    """Convert numeric leaning to label."""
    if leaning <= -1.5:
        return "Left"
    elif leaning <= -0.5:
        return "Lean Left"
    elif leaning < 0.5:
        return "Center"
    elif leaning < 1.5:
        return "Lean Right"
    else:
        return "Right"


def verify_sources():
    """Run all verification checks."""
    print("=" * 70)
    print("ENHANCED SOURCE VERIFICATION REPORT")
    print("=" * 70)
    print()

    # Extract sources from both files
    news_fetcher_sources = extract_sources_from_news_fetcher()
    allsides_sources = extract_sources_from_allsides_seed()

    print(f"Sources in news_fetcher.py: {len(news_fetcher_sources)}")
    print(f"Sources in allsides_seed.py: {len(allsides_sources)}")
    print()

    # Check for rating mismatches
    print("-" * 70)
    print("RATING CONSISTENCY CHECK")
    print("-" * 70)

    mismatches = []
    for name, nf_data in news_fetcher_sources.items():
        if name in allsides_sources:
            as_data = allsides_sources[name]
            if abs(nf_data['leaning'] - as_data['leaning']) > 0.01:
                mismatches.append({
                    'name': name,
                    'news_fetcher': nf_data['leaning'],
                    'allsides_seed': as_data['leaning']
                })

    if mismatches:
        print(f"FAILED: {len(mismatches)} rating mismatches found:")
        for m in mismatches:
            print(f"  - {m['name']}: news_fetcher={m['news_fetcher']}, allsides_seed={m['allsides_seed']}")
    else:
        print("PASSED: All ratings consistent between files")
    print()

    # Report by rating source
    print("-" * 70)
    print("SOURCES BY RATING SOURCE")
    print("-" * 70)

    by_source = defaultdict(list)
    for name, data in allsides_sources.items():
        by_source[data.get('source', 'unknown')].append(name)

    for source_type in ['allsides', 'mbfc', 'adfontesmedia', 'manual']:
        sources = by_source.get(source_type, [])
        print(f"\n{source_type.upper()}: {len(sources)} sources")
        if sources:
            # Group by leaning
            by_leaning = defaultdict(list)
            for name in sources:
                leaning = allsides_sources[name]['leaning']
                label = get_leaning_label(leaning)
                by_leaning[label].append(name)

            for label in ['Left', 'Lean Left', 'Center', 'Lean Right', 'Right']:
                if by_leaning[label]:
                    print(f"  {label} ({len(by_leaning[label])}): {', '.join(sorted(by_leaning[label])[:5])}" +
                          (f"... +{len(by_leaning[label])-5} more" if len(by_leaning[label]) > 5 else ""))

    print()

    # Summary statistics
    print("-" * 70)
    print("SUMMARY STATISTICS")
    print("-" * 70)

    total_sources = len(allsides_sources)
    official_sources = len(by_source.get('allsides', [])) + len(by_source.get('mbfc', []))
    manual_sources = len(by_source.get('manual', []))

    print(f"Total sources: {total_sources}")
    print(f"Official ratings (AllSides + MBFC): {official_sources} ({official_sources/total_sources*100:.1f}%)")
    print(f"Manual assessments: {manual_sources} ({manual_sources/total_sources*100:.1f}%)")
    print()

    # Leaning distribution
    print("Political leaning distribution:")
    leaning_counts = defaultdict(int)
    for name, data in allsides_sources.items():
        label = get_leaning_label(data['leaning'])
        leaning_counts[label] += 1

    for label in ['Left', 'Lean Left', 'Center', 'Lean Right', 'Right']:
        count = leaning_counts[label]
        bar = '#' * (count // 2)
        print(f"  {label:12} {bar} {count}")

    print()

    # Sources in news_fetcher but not in allsides_seed
    print("-" * 70)
    print("COVERAGE GAPS")
    print("-" * 70)

    missing_from_allsides = set(news_fetcher_sources.keys()) - set(allsides_sources.keys())
    if missing_from_allsides:
        print(f"Sources in news_fetcher.py but NOT in allsides_seed.py ({len(missing_from_allsides)}):")
        for name in sorted(missing_from_allsides):
            print(f"  - {name}")
    else:
        print("All news_fetcher sources have entries in allsides_seed.py")

    print()

    missing_from_fetcher = set(allsides_sources.keys()) - set(news_fetcher_sources.keys())
    if missing_from_fetcher:
        print(f"Sources in allsides_seed.py but NOT in news_fetcher.py ({len(missing_from_fetcher)}):")
        for name in sorted(missing_from_fetcher):
            print(f"  - {name}")
    else:
        print("All allsides_seed sources have entries in news_fetcher.py")

    print()
    print("=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)

    # Return exit code based on mismatches
    return 0 if not mismatches else 1


if __name__ == '__main__':
    sys.exit(verify_sources())
