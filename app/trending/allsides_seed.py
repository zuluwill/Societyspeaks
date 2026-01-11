"""
AllSides Media Bias Ratings Seed Data

Ratings based on AllSides.com methodology (as of January 2025).
Scale: -2 (Left) to +2 (Right), with 0 as Center.

For podcasts not rated by AllSides, ratings are based on:
- Host political positioning
- Guest selection patterns
- Editorial perspectives
- Content focus areas

Note: Podcasts that focus on business/lifestyle without political content are rated Center (0).
"""

from datetime import datetime
from app import db
from app.models import NewsSource
import logging

logger = logging.getLogger(__name__)


# AllSides ratings for news outlets and assessed ratings for podcasts
ALLSIDES_RATINGS = {
    # Traditional News Outlets (AllSides rated)
    'The Guardian': {
        'leaning': -1,  # Lean Left
        'source': 'allsides',
        'notes': 'British newspaper with center-left editorial perspective'
    },
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
        'leaning': 0,  # Center (with slight classical liberal lean)
        'source': 'allsides',
        'notes': 'Center with pro-market, socially liberal perspective'
    },
    'Politico EU': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'European politics coverage, generally center'
    },
    'UnHerd': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'Features diverse viewpoints, slight contrarian/right lean'
    },
    'The Atlantic': {
        'leaning': -1,  # Lean Left
        'source': 'allsides',
        'notes': 'US magazine with center-left editorial perspective'
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
    'Axios': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'News delivery focused on brevity and objectivity'
    },
    'The Telegraph': {
        'leaning': 1.5,  # Lean Right to Right
        'source': 'allsides',
        'notes': 'British newspaper with center-right to right editorial stance'
    },
    'The Independent': {
        'leaning': -1,  # Lean Left
        'source': 'allsides',
        'notes': 'British online newspaper with center-left perspective'
    },
    'The New Yorker': {
        'leaning': -2,  # Left
        'source': 'allsides',
        'notes': 'US magazine with left-leaning editorial perspective'
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

    # Podcasts (Assessed based on content and hosts)
    'The News Agents': {
        'leaning': -1,  # Lean Left
        'source': 'manual',
        'notes': 'UK political podcast, hosts have center-left backgrounds (BBC, ITV)'
    },
    'The Rest Is Politics': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Features both left (Alastair Campbell) and right (Rory Stewart) hosts'
    },
    'Triggernometry': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'Long-form interviews, slight libertarian/classical liberal lean'
    },
    'All-In Podcast': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'Tech/business focus, hosts range center to libertarian-right'
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
    'The Ezra Klein Show': {
        'leaning': -1,  # Lean Left
        'source': 'manual',
        'notes': 'NYT politics and policy podcast, center-left editorial perspective'
    },
    # New sources added
    'Farnam Street': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Mental models and decision-making wisdom, apolitical'
    },
    'The Dispatch': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'Fact-based conservative journalism, Jonah Goldberg'
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
    'The Spectator': {
        'leaning': 1,  # Lean Right
        'source': 'allsides',
        'notes': 'British conservative magazine, oldest continuously published'
    },
    'New Statesman': {
        'leaning': -1,  # Lean Left
        'source': 'allsides',
        'notes': 'British progressive magazine'
    },
    'National Review': {
        'leaning': 1.5,  # Right
        'source': 'allsides',
        'notes': 'Leading American conservative magazine, founded by William F. Buckley'
    },
    'The American Conservative': {
        'leaning': 1,  # Lean Right to Right
        'source': 'allsides',
        'notes': 'Paleoconservative and realist foreign policy perspective'
    },
    'Reason': {
        'leaning': 0.5,  # Center to Lean Right (Libertarian)
        'source': 'allsides',
        'notes': 'Libertarian magazine, free minds and free markets'
    },
    'The Free Press': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'Bari Weiss publication, heterodox/independent journalism'
    },
    'City Journal': {
        'leaning': 1,  # Lean Right
        'source': 'manual',
        'notes': 'Manhattan Institute, urban policy conservative perspective'
    },
    'The Critic': {
        'leaning': 0.5,  # Center to Lean Right
        'source': 'manual',
        'notes': 'British intellectual magazine, skeptical/conservative'
    },
    'Acquired Podcast': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Business deep dives, apolitical tech/business focus'
    },
    'The Commentary Magazine': {
        'leaning': 1.5,  # Right
        'source': 'manual',
        'notes': 'Neoconservative intellectual magazine'
    },
}


def update_source_leanings():
    """
    Update NewsSource records with political leaning data.

    Returns:
        dict: Summary of updates (updated, not_found, skipped)
    """
    results = {
        'updated': 0,
        'not_found': [],
        'skipped': 0
    }

    for source_name, rating_data in ALLSIDES_RATINGS.items():
        # Find matching source
        source = NewsSource.query.filter_by(name=source_name).first()

        if not source:
            logger.warning(f"Source not found in database: {source_name}")
            results['not_found'].append(source_name)
            continue

        # Skip if already has more recent rating
        if source.leaning_source == 'allsides' and source.leaning_updated_at:
            # Keep existing AllSides ratings unless manually updated
            results['skipped'] += 1
            continue

        # Update leaning
        source.political_leaning = rating_data['leaning']
        source.leaning_source = rating_data['source']
        source.leaning_updated_at = datetime.utcnow()

        logger.info(f"Updated {source_name}: leaning={rating_data['leaning']} ({rating_data['notes']})")
        results['updated'] += 1

    db.session.commit()

    logger.info(f"AllSides ratings update complete: {results['updated']} updated, "
                f"{results['skipped']} skipped, {len(results['not_found'])} not found")

    return results


def get_leaning_label(leaning_value):
    """
    Convert numeric leaning to text label.

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
        return 'Lean Left'
    elif leaning_value <= 0.5:
        return 'Center'
    elif leaning_value <= 1.5:
        return 'Lean Right'
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
