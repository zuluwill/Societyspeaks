#!/usr/bin/env python3
"""
Comprehensive source verification script.

Checks for:
1. Duplicate source names
2. Rating mismatches between news_fetcher.py and allsides_seed.py
3. Missing sources in either file
4. Invalid feed URLs
5. Name mismatches in templates and seed files
"""

import re
import sys
from urllib.parse import urlparse
from collections import defaultdict

def extract_sources_from_fetcher():
    """Extract all sources from news_fetcher.py"""
    with open('app/trending/news_fetcher.py', 'r') as f:
        content = f.read()
    
    sources = {}
    pattern = r"'name':\s*'([^']+)'.*?'feed_url':\s*'([^']+)'.*?'political_leaning':\s*([-\d.]+)"
    
    for match in re.finditer(r"'name':\s*'([^']+)'.*?'political_leaning':\s*([-\d.]+)", content, re.DOTALL):
        name = match.group(1)
        leaning = float(match.group(2))
        sources[name] = {'leaning': leaning}
    
    # Also extract feed URLs
    for match in re.finditer(r"'name':\s*'([^']+)'.*?'feed_url':\s*'([^']+)'", content, re.DOTALL):
        name = match.group(1)
        feed_url = match.group(2)
        if name in sources:
            sources[name]['feed_url'] = feed_url
    
    return sources

def extract_sources_from_allsides():
    """Extract all sources from allsides_seed.py"""
    with open('app/trending/allsides_seed.py', 'r') as f:
        content = f.read()
    
    sources = {}
    pattern = r"'([^']+)':\s*\{[^}]*'leaning':\s*([-\d.]+)"
    
    for match in re.finditer(pattern, content):
        name = match.group(1)
        leaning = float(match.group(2))
        sources[name] = {'leaning': leaning}
    
    return sources

def check_duplicates(sources):
    """Check for duplicate source names"""
    seen = {}
    duplicates = []
    
    for name in sources.keys():
        if name in seen:
            duplicates.append(name)
        seen[name] = seen.get(name, 0) + 1
    
    return duplicates

def validate_url(url):
    """Validate URL structure"""
    try:
        result = urlparse(url)
        return result.scheme and result.netloc
    except:
        return False

def main():
    print("=" * 70)
    print("SOURCE VERIFICATION REPORT")
    print("=" * 70)
    print()
    
    # Extract sources
    fetcher_sources = extract_sources_from_fetcher()
    allsides_sources = extract_sources_from_allsides()
    
    print(f"📊 Statistics:")
    print(f"   - Sources in news_fetcher.py: {len(fetcher_sources)}")
    print(f"   - Sources in allsides_seed.py: {len(allsides_sources)}")
    print()
    
    # Check for duplicates
    fetcher_dupes = check_duplicates(fetcher_sources)
    allsides_dupes = check_duplicates(allsides_sources)
    
    if fetcher_dupes:
        print(f"❌ DUPLICATES in news_fetcher.py: {fetcher_dupes}")
    else:
        print("✓ No duplicates in news_fetcher.py")
    
    if allsides_dupes:
        print(f"❌ DUPLICATES in allsides_seed.py: {allsides_dupes}")
    else:
        print("✓ No duplicates in allsides_seed.py")
    print()
    
    # Check for missing sources
    missing_in_allsides = set(fetcher_sources.keys()) - set(allsides_sources.keys())
    missing_in_fetcher = set(allsides_sources.keys()) - set(fetcher_sources.keys())
    
    if missing_in_allsides:
        print(f"⚠️  {len(missing_in_allsides)} sources in news_fetcher.py but NOT in allsides_seed.py:")
        for name in sorted(missing_in_allsides):
            print(f"   - {name}")
        print()
    
    if missing_in_fetcher:
        print(f"⚠️  {len(missing_in_fetcher)} sources in allsides_seed.py but NOT in news_fetcher.py:")
        for name in sorted(missing_in_fetcher):
            print(f"   - {name} (may be old entry)")
        print()
    
    # Check for rating mismatches
    mismatches = []
    for name in set(fetcher_sources.keys()) & set(allsides_sources.keys()):
        fetcher_leaning = fetcher_sources[name]['leaning']
        allsides_leaning = allsides_sources[name]['leaning']
        if abs(fetcher_leaning - allsides_leaning) > 0.01:
            mismatches.append((name, fetcher_leaning, allsides_leaning))
    
    if mismatches:
        print(f"❌ {len(mismatches)} RATING MISMATCHES:")
        for name, fetcher_leaning, allsides_leaning in mismatches:
            print(f"   - {name}: news_fetcher={fetcher_leaning}, allsides={allsides_leaning}")
        print()
    else:
        print("✓ All ratings match between files")
        print()
    
    # Validate URLs
    invalid_urls = []
    rsshub_urls = []
    
    for name, data in fetcher_sources.items():
        if 'feed_url' in data:
            url = data['feed_url']
            if not validate_url(url):
                invalid_urls.append((name, url))
            if 'rsshub.app' in url:
                rsshub_urls.append((name, url))
    
    if invalid_urls:
        print(f"❌ {len(invalid_urls)} INVALID URLs:")
        for name, url in invalid_urls[:5]:
            print(f"   - {name}: {url}")
        if len(invalid_urls) > 5:
            print(f"   ... and {len(invalid_urls) - 5} more")
        print()
    else:
        print("✓ All feed URLs are valid")
        print()
    
    if rsshub_urls:
        print(f"⚠️  {len(rsshub_urls)} URLs use RSSHub proxy (may need verification):")
        for name, url in rsshub_urls:
            print(f"   - {name}: {url}")
        print()
    
    # Check brief templates
    with open('scripts/seed_brief_templates.py', 'r') as f:
        template_content = f.read()
    
    template_sources = set(re.findall(r"'name':\s*'([^']+)'", template_content))
    missing_in_templates = template_sources - set(fetcher_sources.keys())
    
    if missing_in_templates:
        print(f"⚠️  {len(missing_in_templates)} sources referenced in brief templates but NOT in news_fetcher.py:")
        for name in sorted(missing_in_templates):
            print(f"   - {name}")
        print()
    
    # Summary
    print("=" * 70)
    if not fetcher_dupes and not allsides_dupes and not mismatches and not invalid_urls:
        if not missing_in_allsides:
            print("✅ ALL CHECKS PASSED")
        else:
            print(f"⚠️  {len(missing_in_allsides)} sources need to be added to allsides_seed.py")
    else:
        print("❌ ISSUES FOUND - See details above")
        sys.exit(1)
    print("=" * 70)

if __name__ == '__main__':
    main()
