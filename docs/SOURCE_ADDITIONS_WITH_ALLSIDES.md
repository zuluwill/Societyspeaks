# Source Additions with AllSides Categorizations

This document summarizes the sources added to the system with AllSides political leaning categorizations.

## Summary

- **Total new sources added**: ~40 sources
- **AllSides-rated sources**: Sources with official AllSides ratings are marked with `'source': 'allsides'`
- **Manually-rated sources**: Sources not on AllSides are marked with `'source': 'manual'` based on editorial assessment

## 1. Fully English, No Caveats (Added)

### Global / International
- ✅ **BBC World Service** - Added (Centre)
- ✅ **Politico** - Added (Lean Left per AllSides)
- ✅ **Euractiv** - Added (Centre)
- ✅ **Financial Times** - Already present
- ✅ **The Economist** - Already present
- ✅ **Reuters** - Already present
- ✅ **Bloomberg** - Already present
- ✅ **Associated Press** - Already present
- ✅ **Al Jazeera English** - Already present
- ✅ **Axios** - Already present

### Think Tanks & Institutions
- ✅ **Carnegie Endowment** - Added (Centre)
- ✅ **International Crisis Group** - Added (Centre)
- ✅ **World Economic Forum** - Added (Centre)
- ✅ **Chatham House** - Already present
- ✅ **Brookings Institution** - Already present
- ✅ **RAND Corporation** - Already present
- ✅ **OECD** - Already present
- ✅ **World Bank** - Already present
- ✅ **IMF** - Already present

### Data Sources
- ✅ **UN News** - Added (Centre)
- ✅ **IEA** - Added (Centre)
- ✅ **WHO** - Added (Centre)
- ✅ **Our World in Data** - Already present
- ✅ **Pew Research Center** - Already present
- ✅ **Eurostat** - Already present
- ✅ **US Census Bureau** - Already present
- ✅ **Office for National Statistics** - Already present
- ✅ **Office for Budget Responsibility** - Already present

### Individuals / Substack / Blogs
- ✅ **Chartbook (Adam Tooze)** - Added (Lean Left)
- ✅ **Ian Bremmer** - Added (Centre)
- ✅ **Ben Thompson (Stratechery)** - Already present
- ✅ **Noah Smith (Noahpinion)** - Already present
- ✅ **Yascha Mounk (Persuasion)** - Already present
- ✅ **Simon Willison** - Already present
- ✅ **Paul Graham** - Already present
- ✅ **Casey Newton (Platformer)** - Already present
- ✅ **Gergely Orosz (The Pragmatic Engineer)** - Already present
- ✅ **Anne Applebaum** - Already present

## 2. Non-English Outlets with English Editions (Added)

### Europe
- ✅ **Spiegel International** - Added (Centre)
- ✅ **Deutsche Welle** - Added (Centre, AllSides-rated)
- ✅ **Le Monde English** - Added (Lean Left)
- ✅ **France24** - Added (Centre)
- ✅ **El País English** - Added (Lean Left)
- ✅ **Politico Europe** - Already present

### Asia
- ✅ **Nikkei Asia** - Added (Centre)
- ✅ **Caixin Global** - Added (Centre)
- ✅ **Sixth Tone** - Added (Centre)
- ✅ **Channel NewsAsia** - Added (Centre)
- ✅ **Straits Times** - Added (Centre)
- ✅ **South China Morning Post** - Already present

### Middle East
- ✅ **Haaretz** - Added (Lean Left, AllSides-rated)
- ✅ **The National (UAE)** - Added (Centre)
- ✅ **Al Monitor** - Added (Centre)

### Africa
- ✅ **Africa Confidential** - Added (Centre)
- ✅ **Mail & Guardian** - Added (Lean Left)
- ✅ **Daily Maverick** - Added (Lean Left)
- ✅ **AllAfrica** - Added (Centre)

### Latin America
- ✅ **Americas Quarterly** - Added (Centre)
- ✅ **El País América** - Added (Lean Left)

## AllSides Categorizations

### Sources with Official AllSides Ratings
- **Politico**: Lean Left (-1.0) - AllSides-rated
- **Deutsche Welle**: Center (0) - AllSides-rated
- **Haaretz**: Lean Left (-1.0) - AllSides-rated
- **The New York Times**: Lean Left (-1.0) - AllSides-rated
- **Wall Street Journal**: Lean Right (0.5) - AllSides-rated
- **The Guardian**: Left (-2.0) - AllSides-rated (moved from Lean Left in chart v11)
- **The Atlantic**: Left (-2.0) - AllSides-rated
- **The Independent**: Left (-2.0) - AllSides-rated
- **Brookings Institution**: Center (0) - AllSides-rated
- **Reason**: Lean Right (1.0) - AllSides-rated
- **Cato Institute**: Lean Right (1.0) - AllSides-rated
- **The Telegraph**: Right (2.0) - AllSides-rated
- **The Spectator**: Right (2.0) - AllSides-rated
- **National Review**: Right (2.0) - AllSides-rated
- **The American Conservative**: Right (2.0) - AllSides-rated

### Sources with Manual Assessments
All other sources have been manually assessed based on:
- Editorial perspective
- Content focus
- Host/author positioning
- Think tank mission statements
- Non-partisan status for data/statistical sources

## Political Leaning Scale

- **-2.0**: Left
- **-1.0**: Lean Left
- **-0.5**: Slight Lean Left
- **0**: Center
- **0.5**: Slight Lean Right
- **1.0**: Lean Right
- **1.5**: Right-leaning
- **2.0**: Right

## Next Steps

1. **Run the seed function** to add sources:
   ```python
   from app.trending.news_fetcher import seed_default_sources
   seed_default_sources()
   ```

2. **Update AllSides ratings**:
   ```python
   from app.trending.allsides_seed import update_source_leanings
   update_source_leanings()
   ```

3. **Verify feed health**:
   ```python
   from app.trending.news_fetcher import check_all_sources_health
   results = check_all_sources_health()
   ```

## Notes

- Some RSS feed URLs may need verification/adjustment after testing
- BBC World Service feed URL uses BBC News world feed as proxy
- UN News, IEA, and some other institutional feeds may need specific feed URLs
- All sources have been categorized with appropriate political leanings based on AllSides where available, or manual assessment

## Files Updated

1. `app/trending/news_fetcher.py` - Added ~40 new sources to `seed_default_sources()`
2. `app/trending/allsides_seed.py` - Added AllSides categorizations for all new sources
3. Updated version number in `allsides_seed.py` to `2026.01.27`
