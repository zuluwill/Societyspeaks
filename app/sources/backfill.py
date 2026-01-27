# app/sources/backfill.py
"""
Backfill script for source profile fields.
Generates slugs and sets source categories for existing NewsSource records.
"""
from app import db
from app.models import NewsSource, generate_slug
import logging

logger = logging.getLogger(__name__)

# Known podcast sources - these get source_category='podcast'
KNOWN_PODCASTS = {
    'The News Agents',
    'The Rest Is Politics',
    'Triggernometry',
    'All-In Podcast',
    'The Tim Ferriss Show',
    'Modern Wisdom',
    'Acquired Podcast',
    'Ezra Klein',  # Updated from 'The Ezra Klein Show'
    'Honestly with Bari Weiss',
    'The Prof G Pod',
    'Conversations with Tyler',
    'EconTalk',
    'The Remnant with Jonah Goldberg',
    'Lexicon Valley',
    'The Commentary Magazine Podcast',
    'Freakonomics Radio',
    'Hardcore History',
    'Revolutions',
    'The Weeds',
    'FiveThirtyEight Politics',
}

# Known broadcasters - these get source_category='broadcaster'
KNOWN_BROADCASTERS = {
    'BBC News',
    'Sky News',
    'Channel 4 News',
    'ITV News',
    'NPR',
    'PBS',
    'ABC News',
    'CBS News',
    'NBC News',
}

# Known magazines - these get source_category='magazine'
KNOWN_MAGAZINES = {
    'The Economist',
    'The Atlantic',
    'The New Yorker',
    'The Spectator',
    'New Statesman',
    'National Review',
    'The American Conservative',
    'Foreign Affairs',
    'Commonweal',
    'Commentary Magazine',
    'UnHerd',
    'Quillette',
}

# Branding data for key sources (priority podcasts and major outlets)
SOURCE_BRANDING = {
    # Priority podcasts for outbound sales
    'The Rest Is Politics': {
        'website_url': 'https://www.therestispolitics.com/',
        'description': 'Political podcast hosted by Alastair Campbell and Rory Stewart, offering insider perspectives on British and global politics.',
    },
    'All-In Podcast': {
        'website_url': 'https://www.allin.com/',
        'description': 'Weekly podcast featuring tech investors Chamath Palihapitiya, Jason Calacanis, David Sacks, and David Friedberg discussing technology, economics, and politics.',
    },
    'Triggernometry': {
        'website_url': 'https://www.triggernometry.com/',
        'description': 'Free speech podcast hosted by comedians Konstantin Kisin and Francis Foster, featuring long-form interviews on culture and politics.',
    },
    # Other notable podcasts
    'The News Agents': {
        'website_url': 'https://www.globalplayer.com/podcasts/42KuWj/',
        'description': 'Daily news podcast with Emily Maitlis, Jon Sopel, and Lewis Goodall breaking down the biggest stories.',
    },
    'Modern Wisdom': {
        'website_url': 'https://modernwisdom.com/',
        'description': 'Podcast hosted by Chris Williamson exploring ideas on self-improvement, psychology, and culture.',
    },
    'The Ezra Klein Show': {
        'website_url': 'https://www.nytimes.com/column/ezra-klein-podcast',
        'description': 'New York Times podcast featuring in-depth conversations about politics, policy, and ideas.',
    },
    # Major UK newspapers
    'The Guardian': {
        'website_url': 'https://www.theguardian.com/',
        'description': 'British daily newspaper known for its liberal and progressive editorial stance.',
    },
    'The Times': {
        'website_url': 'https://www.thetimes.co.uk/',
        'description': 'British national newspaper founded in 1785, known for quality journalism and centre-right perspective.',
    },
    'The Telegraph': {
        'website_url': 'https://www.telegraph.co.uk/',
        'description': 'British national broadsheet with conservative editorial stance.',
    },
    'Financial Times': {
        'website_url': 'https://www.ft.com/',
        'description': 'International business newspaper with distinctive salmon-pink paper, focused on business and economic news.',
    },
    # Major US newspapers
    'The New York Times': {
        'website_url': 'https://www.nytimes.com/',
        'description': 'American newspaper of record, known for comprehensive national and international news coverage.',
    },
    'The Washington Post': {
        'website_url': 'https://www.washingtonpost.com/',
        'description': 'Major American newspaper focused on national politics and investigative journalism.',
    },
    'The Wall Street Journal': {
        'website_url': 'https://www.wsj.com/',
        'description': 'American business-focused newspaper with conservative editorial page.',
    },
    # Broadcasters
    'BBC News': {
        'website_url': 'https://www.bbc.co.uk/news',
        'description': 'British public service broadcaster providing impartial news coverage worldwide.',
    },
    'Sky News': {
        'website_url': 'https://news.sky.com/',
        'description': 'British 24-hour news channel and digital news service.',
    },
    # Magazines
    'The Economist': {
        'website_url': 'https://www.economist.com/',
        'description': 'International weekly newspaper focused on current affairs, business, and politics with a classical liberal perspective.',
    },
    'The Atlantic': {
        'website_url': 'https://www.theatlantic.com/',
        'description': 'American magazine covering news, politics, culture, technology, and more.',
    },
    'The Spectator': {
        'website_url': 'https://www.spectator.co.uk/',
        'description': 'British weekly magazine covering politics and culture from a conservative perspective.',
    },
    'UnHerd': {
        'website_url': 'https://unherd.com/',
        'description': 'British online magazine featuring contrarian perspectives and long-form analysis.',
    },
}


def backfill_source_slugs():
    """Generate slugs for all sources that don't have one."""
    sources = NewsSource.query.filter(
        (NewsSource.slug.is_(None)) | (NewsSource.slug == '')
    ).all()

    updated = 0
    for source in sources:
        try:
            source.slug = generate_slug(source.name)
            updated += 1
            logger.info(f'Generated slug for {source.name}: {source.slug}')
        except Exception as e:
            logger.error(f'Error generating slug for {source.name}: {e}')

    if updated > 0:
        db.session.commit()
        logger.info(f'Updated {updated} source slugs')

    return updated


def backfill_source_categories():
    """Set source_category based on known source types."""
    updated = 0

    # Update podcasts
    for name in KNOWN_PODCASTS:
        source = NewsSource.query.filter_by(name=name).first()
        if source and source.source_category != 'podcast':
            source.source_category = 'podcast'
            updated += 1
            logger.info(f'Set {name} category to podcast')

    # Update broadcasters
    for name in KNOWN_BROADCASTERS:
        source = NewsSource.query.filter_by(name=name).first()
        if source and source.source_category != 'broadcaster':
            source.source_category = 'broadcaster'
            updated += 1
            logger.info(f'Set {name} category to broadcaster')

    # Update magazines
    for name in KNOWN_MAGAZINES:
        source = NewsSource.query.filter_by(name=name).first()
        if source and source.source_category != 'magazine':
            source.source_category = 'magazine'
            updated += 1
            logger.info(f'Set {name} category to magazine')

    # Default remaining to 'newspaper'
    remaining = NewsSource.query.filter(
        (NewsSource.source_category.is_(None)) | (NewsSource.source_category == '')
    ).all()

    for source in remaining:
        source.source_category = 'newspaper'
        updated += 1
        logger.info(f'Set {source.name} category to newspaper (default)')

    if updated > 0:
        db.session.commit()
        logger.info(f'Updated {updated} source categories')

    return updated


def backfill_source_branding():
    """Set website_url and description for known sources."""
    updated = 0

    for name, branding in SOURCE_BRANDING.items():
        source = NewsSource.query.filter_by(name=name).first()
        if source:
            changed = False

            if branding.get('website_url') and not source.website_url:
                source.website_url = branding['website_url']
                changed = True

            if branding.get('description') and not source.description:
                source.description = branding['description']
                changed = True

            if branding.get('logo_url') and not source.logo_url:
                source.logo_url = branding['logo_url']
                changed = True

            if changed:
                updated += 1
                logger.info(f'Updated branding for {name}')

    if updated > 0:
        db.session.commit()
        logger.info(f'Updated {updated} source branding records')

    return updated


def backfill_all():
    """Run all backfill operations."""
    logger.info('Starting source profile backfill...')

    slugs_updated = backfill_source_slugs()
    categories_updated = backfill_source_categories()
    branding_updated = backfill_source_branding()

    logger.info(
        f'Backfill complete: {slugs_updated} slugs, '
        f'{categories_updated} categories, {branding_updated} branding'
    )

    return {
        'slugs_updated': slugs_updated,
        'categories_updated': categories_updated,
        'branding_updated': branding_updated
    }


if __name__ == '__main__':
    # Allow running directly for testing
    from app import create_app
    app = create_app()
    with app.app_context():
        backfill_all()
