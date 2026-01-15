"""
AllSides Media Bias Ratings Seed Data

Ratings based on AllSides.com methodology (as of January 2026).
Scale: -2 (Left) to +2 (Right), with 0 as Center.
Supports 0.5 increments for nuanced positioning.

For podcasts not rated by AllSides, ratings are based on:
- Host political positioning
- Guest selection patterns
- Editorial perspectives
- Content focus areas

Note: Podcasts that focus on business/lifestyle without political content are rated Center (0).

Color scheme uses US-style political colors:
- Blue (#0066CC) for Left
- Light Blue (#6699FF) for Lean Left  
- Purple (#9933CC) for Center
- Light Red (#FF6B6B) for Lean Right
- Red (#CC0000) for Right
"""

from datetime import datetime
from app import db
from app.models import NewsSource
import logging

logger = logging.getLogger(__name__)

# Version for tracking when ratings were last updated
# Increment this when making rating changes to force updates
RATINGS_VERSION = '2026.01.15'


# AllSides ratings for news outlets and assessed ratings for podcasts
# Values must match news_fetcher.py default_sources for consistency
# Updated January 2026 to reflect AllSides chart v11 (The Guardian moved Left)
ALLSIDES_RATINGS = {
    # ==========================================================================
    # LEFT SOURCES (≤ -1.5)
    # ==========================================================================
    'The New Yorker': {
        'leaning': -2.0,  # Left
        'source': 'allsides',
        'notes': 'US magazine with left-leaning editorial perspective'
    },
    'The Guardian': {
        'leaning': -2.0,  # Left (moved from Lean Left in Nov 2024)
        'source': 'allsides',
        'notes': 'British newspaper, rated Left per AllSides chart v10.1'
    },
    'The Atlantic': {
        'leaning': -2.0,  # Left (confirmed July 2025)
        'source': 'allsides',
        'notes': 'US magazine with left editorial perspective'
    },
    'The Independent': {
        'leaning': -2.0,  # Left
        'source': 'allsides',
        'notes': 'British online newspaper with left perspective'
    },
    'The Intercept': {
        'leaning': -2.0,  # Left
        'source': 'allsides',
        'notes': 'Progressive investigative journalism, civil liberties focus'
    },
    'New Statesman': {
        'leaning': -2.0,  # Left
        'source': 'allsides',
        'notes': 'British progressive magazine'
    },
    'The Ezra Klein Show': {
        'leaning': -2.0,  # Left
        'source': 'manual',
        'notes': 'NYT politics and policy podcast, left editorial perspective'
    },
    'The News Agents': {
        'leaning': -2.0,  # Left
        'source': 'manual',
        'notes': 'UK political podcast, hosts have left backgrounds'
    },
    'Matt Taibbi': {
        'leaning': -2.0,  # Left
        'source': 'manual',
        'notes': 'Former Rolling Stone, heterodox anti-establishment left'
    },
    'Freddie deBoer': {
        'leaning': -2.0,  # Left
        'source': 'manual',
        'notes': 'Education, mental health, socialist perspective'
    },
    
    # ==========================================================================
    # CENTRE-LEFT SOURCES (-1.0)
    # ==========================================================================
    'ProPublica': {
        'leaning': -1.0,  # Centre-Left
        'source': 'allsides',
        'notes': 'Non-profit investigative journalism, data-driven'
    },
    'Slow Boring': {
        'leaning': -1.0,  # Centre-Left
        'source': 'manual',
        'notes': 'Matt Yglesias policy analysis, centre-left wonk'
    },
    'Noahpinion': {
        'leaning': -1.0,  # Centre-Left
        'source': 'manual',
        'notes': 'Noah Smith economics Substack, accessible policy analysis'
    },
    'Commonweal': {
        'leaning': -1.0,  # Centre-Left
        'source': 'manual',
        'notes': 'Catholic intellectual tradition, social justice focus'
    },
    
    # ==========================================================================
    # CENTER SOURCES (-0.5 to +0.5)
    # ==========================================================================
    'BBC News': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'UK public broadcaster with mandated impartiality'
    },
    'Financial Times': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Business-focused with balanced economic coverage'
    },
    'The Economist': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Center with pro-market, socially liberal perspective'
    },
    'Politico EU': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'European politics coverage, generally center'
    },
    'Foreign Affairs': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Academic foreign policy journal, non-partisan'
    },
    'Bloomberg': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Business and financial news, center perspective'
    },
    'Axios': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'News delivery focused on brevity and objectivity'
    },
    'TechCrunch': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Technology news, generally apolitical'
    },
    'Stratechery': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Ben Thompson tech/business strategy analysis, apolitical'
    },
    'Foreign Policy': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Leading global affairs publication, non-partisan'
    },
    'War on the Rocks': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'National security and defense analysis, academic/expert focus'
    },
    'Farnam Street': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Mental models and decision-making wisdom, apolitical'
    },
    'Semafor': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Global news with transparent sourcing'
    },
    'Rest of World': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'International tech and society coverage'
    },
    'The Conversation': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Academic experts writing for public audience'
    },
    'Al Jazeera English': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Qatar-based, non-Western global perspective'
    },
    'Lawfare': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Legal and national security analysis, expert-driven'
    },
    'MIT Technology Review': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Authoritative on AI, biotech, climate tech'
    },
    'Carbon Brief': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Climate science and policy, factual/data-driven'
    },
    'South China Morning Post': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Hong Kong-based, Asia/China coverage'
    },
    'Ars Technica': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Deep tech analysis, strong on policy implications'
    },
    'The Rest Is Politics': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Features both left (Alastair Campbell) and right (Rory Stewart) hosts'
    },
    'The Tim Ferriss Show': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Lifestyle/business focused, generally apolitical'
    },
    'Diary of a CEO': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Business/entrepreneurship focused, generally apolitical'
    },
    'Modern Wisdom': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Philosophy/lifestyle focused, generally apolitical'
    },
    'Lex Fridman Podcast': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Long-form conversations on AI, science, philosophy with diverse guests'
    },
    'Huberman Lab': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Neuroscience and science-based health, generally apolitical'
    },
    'Acquired Podcast': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Business deep dives, apolitical tech/business focus'
    },
    'Brookings Institution': {
        'leaning': 0,  # Centre (per help page)
        'source': 'allsides',
        'notes': 'Think tank, research-backed policy analysis'
    },
    
    # ==========================================================================
    # CENTRE-RIGHT SOURCES (+1.0)
    # ==========================================================================
    'UnHerd': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Features diverse viewpoints, contrarian/right lean'
    },
    'The Dispatch': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Fact-based conservative journalism, Jonah Goldberg'
    },
    'The Free Press': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Bari Weiss publication, heterodox/independent journalism'
    },
    'Reason': {
        'leaning': 1.0,  # Centre-Right (Libertarian)
        'source': 'allsides',
        'notes': 'Libertarian magazine, free minds and free markets'
    },
    'The Critic': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'British intellectual magazine, skeptical/conservative'
    },
    'Marginal Revolution': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Tyler Cowen economics blog, libertarian-leaning'
    },
    'Cato Institute': {
        'leaning': 1.0,  # Centre-Right
        'source': 'allsides',
        'notes': 'Libertarian think tank, free markets and civil liberties'
    },
    'Andrew Sullivan': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Former New Republic/Atlantic editor, heterodox conservative'
    },
    'Triggernometry': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Long-form interviews, libertarian/classical liberal lean'
    },
    'All-In Podcast': {
        'leaning': 1.0,  # Centre-Right
        'source': 'manual',
        'notes': 'Tech/business focus, hosts range center to libertarian-right'
    },
    
    # ==========================================================================
    # RIGHT SOURCES (≥ 1.5)
    # ==========================================================================
    'The Telegraph': {
        'leaning': 2.0,  # Right
        'source': 'allsides',
        'notes': 'British newspaper with right editorial stance'
    },
    'The Spectator': {
        'leaning': 2.0,  # Right
        'source': 'allsides',
        'notes': 'British conservative magazine, oldest continuously published'
    },
    'National Review': {
        'leaning': 2.0,  # Right
        'source': 'allsides',
        'notes': 'Leading American conservative magazine, founded by William F. Buckley'
    },
    'The American Conservative': {
        'leaning': 2.0,  # Right
        'source': 'allsides',
        'notes': 'Paleoconservative and realist foreign policy perspective'
    },
    'City Journal': {
        'leaning': 2.0,  # Right
        'source': 'manual',
        'notes': 'Manhattan Institute, urban policy conservative perspective'
    },
    'Manhattan Institute': {
        'leaning': 2.0,  # Right
        'source': 'manual',
        'notes': 'Conservative think tank, pairs with City Journal'
    },
    'The Commentary Magazine': {
        'leaning': 2.0,  # Right
        'source': 'manual',
        'notes': 'Neoconservative intellectual magazine'
    },
    'First Things': {
        'leaning': 2.0,  # Right
        'source': 'manual',
        'notes': 'Religious conservative intellectual journal'
    },
    'Christianity Today': {
        'leaning': 2.0,  # Right
        'source': 'manual',
        'notes': 'Evangelical perspective'
    },
}


def update_source_leanings(force: bool = False):
    """
    Update NewsSource records with political leaning data.
    
    Args:
        force: If True, update all sources even if they already have ratings.
               If False, only update sources where the rating value has changed
               or where no rating exists.

    Returns:
        dict: Summary of updates (updated, not_found, skipped, unchanged)
    """
    results = {
        'updated': 0,
        'not_found': [],
        'skipped': 0,
        'unchanged': 0
    }

    for source_name, rating_data in ALLSIDES_RATINGS.items():
        # Find matching source
        source = NewsSource.query.filter_by(name=source_name).first()

        if not source:
            logger.warning(f"Source not found in database: {source_name}")
            results['not_found'].append(source_name)
            continue

        new_leaning = rating_data['leaning']
        new_source_type = rating_data['source']
        
        # Check if update is needed
        if not force:
            # Update if: no current rating, or rating value differs
            current_leaning = source.political_leaning
            
            if current_leaning is not None and current_leaning == new_leaning:
                # Rating unchanged, no update needed
                results['unchanged'] += 1
                continue
        
        # Update leaning
        source.political_leaning = new_leaning
        source.leaning_source = new_source_type
        source.leaning_updated_at = datetime.utcnow()

        logger.info(f"Updated {source_name}: leaning={new_leaning} ({rating_data['notes']})")
        results['updated'] += 1

    db.session.commit()

    logger.info(f"AllSides ratings update complete: {results['updated']} updated, "
                f"{results['unchanged']} unchanged, {len(results['not_found'])} not found")

    return results


def force_update_all_leanings():
    """
    Force update ALL source leanings from ALLSIDES_RATINGS.
    Use this when you've updated rating values and want to apply them immediately.
    
    Returns:
        dict: Summary of updates
    """
    logger.info("Force updating all source leanings...")
    return update_source_leanings(force=True)


def get_leaning_label(leaning_value):
    """
    Convert numeric leaning to text label based on AllSides ratings.

    Args:
        leaning_value: Float from -3 to +3

    Returns:
        str: Human-readable label
    """
    if leaning_value is None:
        return 'Unknown'
    elif leaning_value <= -1.5:
        return 'Left'
    elif leaning_value <= -0.5:
        return 'Centre-Left'
    elif leaning_value <= 0.5:
        return 'Centre'
    elif leaning_value <= 1.5:
        return 'Centre-Right'
    else:
        return 'Right'


def get_leaning_color(leaning_value):
    """
    Get color code for leaning value (for UI display).

    Args:
        leaning_value: Float from -3 to +3

    Returns:
        str: Hex color code
    """
    if leaning_value is None:
        return '#999999'  # Gray for unknown
    elif leaning_value <= -1:
        return '#0066CC'  # Blue for left
    elif leaning_value < 0:
        return '#6699FF'  # Light blue for lean left
    elif leaning_value == 0:
        return '#9933CC'  # Purple for center
    elif leaning_value < 1:
        return '#FF6B6B'  # Light red for lean right
    else:
        return '#CC0000'  # Red for right
