# Source Additions Summary

This document summarizes the sources that were added to the `seed_default_sources()` function in `app/trending/news_fetcher.py` based on your requirements.

## ✅ Sources Added

### 1. Tier-1 News & Wires (Non-negotiable)
- ✅ **Wall Street Journal** - Added (World News feed)
- ✅ **The New York Times** - Added (HomePage feed)
- ✅ **Financial Times** - Already present
- ✅ **The Economist** - Already present
- ✅ **Reuters** - Already present
- ✅ **Associated Press** - Already present (renamed from "AP News")
- ✅ **BBC News** - Already present

### 2. Major Opinion & Analysis

**Left/Liberal:**
- ✅ **Vox** - Added
- ✅ **The Guardian** - Already present
- ✅ **The New York Times** - Added (see Tier-1)
- ✅ **The New Yorker** - Already present
- ✅ **The Atlantic** - Already present

**Right/Conservative:**
- ✅ **The Spectator** - Already present
- ✅ **National Review** - Already present
- ⚠️ **The Times UK** - Added (URL may need verification - paywall)
- ✅ **UnHerd** - Already present

### 3. High-signal Substacks & Independent Thinkers

**Politics, society, public discourse:**
- ✅ **Noah Smith (Noahpinion)** - Already present
- ✅ **Yascha Mounk (Persuasion)** - Added
- ✅ **Ezra Klein** - Added
- ✅ **Matthew Yglesias (Slow Boring)** - Already present
- ❌ **Sam Harris** - Cannot add (subscription-only RSS feed)
- ✅ **Freddie deBoer** - Already present

**Media, power, institutions:**
- ✅ **Anne Applebaum** - Added
- ✅ **Jonathan Rauch** - Added
- ✅ **Zeynep Tufekci** - Added (note: now NYT columnist, feed may be inactive)
- ✅ **Francis Fukuyama** - Added

### 4. Tech, systems, and "how the world actually works"

- ✅ **Ben Thompson (Stratechery)** - Already present
- ✅ **Casey Newton (Platformer)** - Added
- ✅ **Packy McCormick (Not Boring)** - Added
- ✅ **Gergely Orosz (The Pragmatic Engineer)** - Added
- ✅ **Simon Willison** - Added
- ✅ **Paul Graham** - Added (using community-maintained feed)
- ✅ **Cory Doctorow** - Added

### 5. Think tanks & policy institutions

**UK:**
- ✅ **Institute for Government** - Added
- ✅ **Institute for Fiscal Studies** - Added (podcast feed)
- ✅ **Resolution Foundation** - Added
- ✅ **UK Parliament** - Added (bills feed)

**International/US:**
- ✅ **Brookings Institution** - Already present
- ✅ **RAND Corporation** - Added
- ✅ **Chatham House** - Added
- ✅ **CSIS** - Added
- ✅ **OECD** - Added
- ⚠️ **World Bank** - Added (URL may need verification)
- ⚠️ **IMF** - Added (URL points to RSS list page, may need specific feed)

### 6. Data & primary evidence

- ⚠️ **Office for National Statistics** - Added (release calendar URL, may need feed verification)
- ⚠️ **Office for Budget Responsibility** - Added (feed URL may need verification)
- ✅ **Pew Research Center** - Added
- ✅ **Our World in Data** - Added
- ✅ **Eurostat** - Added
- ✅ **US Census Bureau** - Added (news releases feed)

### 7. Meta-media & journalism analysis

- ✅ **Nieman Lab** - Added
- ✅ **Columbia Journalism Review** - Added
- ✅ **Poynter** - Added
- ✅ **Axios** - Already present

### 8. X / Social accounts

These are not RSS feeds and would require different integration (API access, scraping, etc.). They are not included in the RSS feed system.

## ⚠️ Sources Requiring Verification

The following sources were added but their RSS feed URLs may need verification:

1. **The Times UK** - `https://www.thetimes.co.uk/rss` (may be behind paywall)
2. **World Bank** - `https://blogs.worldbank.org/en/blogs` (may need specific feed URL)
3. **IMF** - `https://www.imf.org/en/rss-list` (points to list page, may need specific feed)
4. **Office for National Statistics** - `https://ons.gov.uk/releasecalendar` (may need feed URL)
5. **Office for Budget Responsibility** - `https://obr.uk/feed` (may need verification)

## ❌ Sources That Could Not Be Added

1. **Sam Harris (Making Sense)** - Requires paid subscription with personalized RSS feeds. Cannot be added to public feed system.

## Next Steps

1. **Run the seed function** to add these sources to your database:
   ```python
   from app.trending.news_fetcher import seed_default_sources
   seed_default_sources()
   ```

2. **Verify feed health** after seeding:
   ```python
   from app.trending.news_fetcher import check_all_sources_health
   results = check_all_sources_health()
   # Check for any sources with status != 'ok'
   ```

3. **Fix any broken feeds** - If any of the ⚠️ sources fail, you may need to:
   - Find alternative RSS feed URLs
   - Check if the source requires authentication
   - Verify the feed format is compatible

## Summary Statistics

- **Total sources in your list**: ~60 sources
- **Already present**: ~25 sources
- **Newly added**: ~35 sources
- **Could not add**: 1 source (Sam Harris)
- **Needs verification**: 5 sources

The seed function will automatically:
- Add new sources that don't exist
- Update existing sources with new field values (feed_url, country, political_leaning, etc.)
- Skip sources that already match exactly
