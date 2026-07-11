#!/usr/bin/env python3
"""
Sync segment metadata (chapter/function/geography) onto daily_brief_subscriber
rows from a CSV export — without ever touching an existing subscriber's
status, tier, or preferences.

Source file: CSV with columns Member, Email, Linkedin, Chapter, Job Title,
Company, Function, Address (Numbers export; a leading "Table 1" line is
tolerated).

Rules (in order of importance):
  1. NEVER changes status/tier/preferences of an existing row — a subscriber
     who unsubscribed, bounced, or paused stays that way. Existing rows only
     receive metadata (source, chapter, function, job_title, company,
     country, city, imported_at).
  2. Addresses not already present are inserted with status='imported' —
     segmented but excluded from every send path (all gate on
     status == 'active') until activated in batches by
     scripts/activate_imported_subscribers.py.
  3. Dry-run by default: the whole transaction runs and reports, then rolls
     back. Pass --commit to apply.

Usage:
    DATABASE_URL=postgres://... python3 scripts/import_subscriber_segments.py \
        export.csv --source <label> [--commit]
"""
import argparse
import csv
import os
import re
import secrets
import subprocess
import sys
import tempfile

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-']+@[a-z0-9.-]+\.[a-z]{2,}$")

US_STATES = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA',
    'ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK',
    'OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC',
}

COUNTRY_ALIASES = {
    'usa': 'United States', 'us': 'United States', 'united states': 'United States',
    'united states of america': 'United States',
    'uk': 'United Kingdom', 'united kingdom': 'United Kingdom', 'england': 'United Kingdom',
    'scotland': 'United Kingdom', 'wales': 'United Kingdom', 'northern ireland': 'United Kingdom',
    'the netherlands': 'Netherlands', 'holland': 'Netherlands',
    'hong kong sar': 'Hong Kong', 'españa': 'Spain', 'czechia': 'Czech Republic',
    'belgiu': 'Belgium',  # source-file typo
}

KNOWN_COUNTRIES = {
    'united states', 'united kingdom', 'canada', 'australia', 'netherlands', 'germany',
    'singapore', 'india', 'ireland', 'spain', 'israel', 'france', 'brazil', 'new zealand',
    'denmark', 'norway', 'sweden', 'switzerland', 'austria', 'belgium', 'portugal', 'italy',
    'poland', 'hungary', 'romania', 'bulgaria', 'serbia', 'finland', 'estonia', 'czech republic',
    'greece', 'mexico', 'argentina', 'chile', 'colombia', 'venezuela', 'thailand', 'malaysia',
    'philippines', 'japan', 'south africa', 'kenya', 'nigeria', 'united arab emirates',
    'luxembourg', 'ukraine', 'belarus', 'russia', 'hong kong', 'macedonia',
    'bosnia and herzegovina', 'turkey', 'egypt', 'saudi arabia',
}

# 'City - CODE' chapters → country
CHAPTER_CODE_COUNTRY = {
    'LDN': 'United Kingdom', 'MAN': 'United Kingdom',
    'TOR': 'Canada', 'MTL': 'Canada', 'VAN': 'Canada',
    'SGP': 'Singapore', 'AMS': 'Netherlands',
    'BER': 'Germany', 'MUC': 'Germany',
    'IRE': 'Ireland', 'BCN': 'Spain', 'CPH': 'Denmark', 'OSL': 'Norway',
    'STO': 'Sweden', 'SYD': 'Australia', 'NZ': 'New Zealand',
    'BRA': 'Brazil', 'ZRH': 'Switzerland',
}
# Everything else in 'City - CODE' format is a US chapter

CITY_ONLY_COUNTRY = {
    'atlanta': 'United States', 'los angeles': 'United States',
    'new york city': 'United States', 'san francisco': 'United States',
    'washington dc': 'United States', 'sfo': 'United States', 'munich': 'Germany',
}
CITY_ONLY_CITY = {'sfo': 'San Francisco', 'washington dc': 'Washington, DC'}


def normalize_country(raw):
    key = raw.strip().lower().rstrip('.')
    if key in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[key]
    if key in KNOWN_COUNTRIES:
        return raw.strip().title() if raw.strip().islower() else raw.strip()
    return None


def geo_from_address(address):
    """'San Francisco, California, United States' → (city, country)."""
    if not address or address.strip() in ('-', ''):
        return None, None
    parts = [p.strip() for p in address.split(',') if p.strip()]
    if not parts:
        return None, None
    country = normalize_country(parts[-1])
    if country is None and parts[-1].upper() in US_STATES:
        country = 'United States'
    city = parts[0] if len(parts) >= 3 else None
    return city, country


def geo_from_chapter(chapter):
    """Best-effort (city, country) from the many chapter formats."""
    ch = chapter.strip().strip('"').strip()
    if not ch or ch.lower() in ('chapter', 'rem') or '@' in ch:
        return None, None, None  # junk value — drop the chapter too
    low = ch.lower()
    if low.startswith('remote -') or low.startswith('remote  -'):
        rest = ch.split('-', 1)[1].strip()
        parts = [p.strip() for p in rest.split(',') if p.strip()]
        if not parts:
            return ch, None, None
        last = parts[-1]
        if last.upper() in US_STATES:
            return ch, parts[0] if len(parts) > 1 else None, 'United States'
        country = normalize_country(last)
        city = parts[0] if len(parts) > 1 else None
        return ch, city, country  # region-only entries (Europe/APAC) → country None
    if ' - ' in ch or ch.endswith('- SFO'):
        left, _, code = ch.rpartition('-')
        left, code = left.strip(), code.strip()
        # '(Georgia, USA)' style never uses ' - '; this branch is 'City - CODE'
        country = CHAPTER_CODE_COUNTRY.get(code, 'United States')
        if code == 'MIA/SoFL':
            country = 'United States'
        return ch, left or None, country
    if '(' in ch:
        city = ch.split('(')[0].strip()
        inner = ch[ch.index('(') + 1:].rstrip(')')
        parts = [p.strip() for p in inner.split(',') if p.strip()]
        country = normalize_country(parts[-1]) if parts else None
        return ch, city or None, country
    country = CITY_ONLY_COUNTRY.get(low)
    city = CITY_ONLY_CITY.get(low, ch if country else None)
    return ch, city, country


def load_rows(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        first = next(reader)
        header = first if 'Email' in first else next(reader)
        idx = {h.strip(): i for i, h in enumerate(header)}

        def get(r, k):
            i = idx.get(k)
            return r[i].strip() if i is not None and i < len(r) else ''

        for r in reader:
            email = get(r, 'Email').lower()
            if not EMAIL_RE.match(email):
                continue
            chapter_raw = get(r, 'Chapter')
            chapter, ch_city, ch_country = geo_from_chapter(chapter_raw) if chapter_raw else (None, None, None)
            addr_city, addr_country = geo_from_address(get(r, 'Address'))
            function = get(r, 'Function')
            rows.append({
                'email': email,
                'chapter': (chapter or '')[:120],
                'function': '' if function in ('N/A', '') else function[:100],
                'job_title': get(r, 'Job Title')[:255],
                'company': get(r, 'Company')[:255],
                'country': (addr_country or ch_country or '')[:100],
                'city': (addr_city or ch_city or '')[:100],
            })
    # Dedupe: keep the most complete row per email
    best = {}
    meta_cols = ('chapter', 'function', 'job_title', 'company', 'country', 'city')
    for r in rows:
        score = sum(1 for c in meta_cols if r[c])
        if r['email'] not in best or score > best[r['email']][0]:
            best[r['email']] = (score, r)
    return [r for _, r in best.values()], len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument('csv_path')
    ap.add_argument('--source', required=True,
                    help="provenance label written to the source column")
    ap.add_argument('--commit', action='store_true',
                    help='apply changes (default: dry-run, transaction rolled back)')
    args = ap.parse_args()

    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        sys.exit('DATABASE_URL is not set')
    if not re.fullmatch(r'[a-z0-9_]+', args.source):
        sys.exit('--source must be a lowercase slug (a-z, 0-9, _)')

    rows, raw_count = load_rows(args.csv_path)
    print(f'source file: {raw_count} valid rows, {len(rows)} unique emails '
          f'({raw_count - len(rows)} in-file duplicates collapsed)')
    with_geo = sum(1 for r in rows if r['country'])
    print(f'country resolved for {with_geo} ({with_geo * 100 // len(rows)}%)')

    with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='') as staged:
        writer = csv.writer(staged)
        for r in rows:
            writer.writerow([r['email'], r['chapter'], r['function'], r['job_title'],
                             r['company'], r['country'], r['city'],
                             secrets.token_urlsafe(32)])
        staged_path = staged.name

    final = 'COMMIT' if args.commit else 'ROLLBACK'
    sql = f"""
\\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE staging_import (
    email text PRIMARY KEY,
    chapter text, func text, job_title text, company text,
    country text, city text, unsubscribe_token text
);
\\copy staging_import FROM '{staged_path}' WITH (FORMAT csv)

\\echo '--- existing rows receiving metadata backfill, by status (status itself untouched):'
WITH upd AS (
    UPDATE daily_brief_subscriber s
    SET source = '{args.source}',
        chapter = nullif(t.chapter, ''),
        "function" = nullif(t.func, ''),
        job_title = nullif(t.job_title, ''),
        company = nullif(t.company, ''),
        country = nullif(t.country, ''),
        city = nullif(t.city, ''),
        imported_at = now()
    FROM staging_import t
    WHERE lower(s.email) = t.email
    RETURNING s.status
)
SELECT status, count(*) FROM upd GROUP BY 1 ORDER BY 2 DESC;

\\echo '--- new rows inserted as dormant (status=imported, excluded from sends):'
WITH ins AS (
    INSERT INTO daily_brief_subscriber
        (email, tier, status, timezone, preferred_send_hour, cadence,
         preferred_weekly_day, created_at, total_briefs_received, total_opens,
         total_clicks, unsubscribe_token, source, chapter, "function",
         job_title, company, country, city, imported_at)
    SELECT t.email, 'free', 'imported', 'UTC', 18, 'daily',
           6, now(), 0, 0,
           0, t.unsubscribe_token, '{args.source}', nullif(t.chapter, ''),
           nullif(t.func, ''), nullif(t.job_title, ''), nullif(t.company, ''),
           nullif(t.country, ''), nullif(t.city, ''), now()
    FROM staging_import t
    LEFT JOIN daily_brief_subscriber s ON lower(s.email) = t.email
    WHERE s.id IS NULL
    RETURNING 1
)
SELECT count(*) AS inserted FROM ins;

\\echo '--- post-run subscriber totals by status:'
SELECT status, count(*) FROM daily_brief_subscriber GROUP BY 1 ORDER BY 2 DESC;
{final};
"""
    print(f"\nmode: {'COMMIT' if args.commit else 'DRY-RUN (rolled back)'}\n")
    result = subprocess.run(['psql', db_url, '-v', 'ON_ERROR_STOP=1'],
                            input=sql, text=True)
    os.unlink(staged_path)
    sys.exit(result.returncode)


if __name__ == '__main__':
    main()
