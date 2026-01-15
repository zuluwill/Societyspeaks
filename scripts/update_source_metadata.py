"""
Update Source Metadata Script

Populates website_url, logo_url, source_category, and description for all sources.
Also adds podcast-specific platform links.

Run with: flask shell < scripts/update_source_metadata.py
Or: python -c "from scripts.update_source_metadata import update_all_sources; update_all_sources()"
"""

from datetime import datetime
from app import db, create_app
from app.models import NewsSource
import logging

logger = logging.getLogger(__name__)

SOURCE_METADATA = {
    'Acquired Podcast': {
        'source_category': 'podcast',
        'website_url': 'https://www.acquired.fm/',
        'logo_url': 'https://logo.clearbit.com/acquired.fm',
        'description': 'Deep dives into the playbooks of the greatest companies and investors. Hosted by Ben Gilbert and David Rosenthal.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/acquired/id1050462261',
            'spotify': 'https://open.spotify.com/show/7Fj0XEuUQLUqoMZbNKwdbL',
            'youtube': 'https://www.youtube.com/@AcquiredFM'
        }
    },
    'Al Jazeera English': {
        'source_category': 'broadcaster',
        'website_url': 'https://www.aljazeera.com/',
        'logo_url': 'https://logo.clearbit.com/aljazeera.com',
        'description': 'International English-language news channel providing comprehensive news coverage with a global perspective from Doha, Qatar.'
    },
    'All-In Podcast': {
        'source_category': 'podcast',
        'website_url': 'https://www.allin.com/',
        'logo_url': 'https://logo.clearbit.com/allin.com',
        'description': 'Industry veterans break down the biggest stories in tech, investing, and politics. Hosted by Chamath Palihapitiya, Jason Calacanis, David Sacks, and David Friedberg.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/all-in-with-chamath-jason-sacks-friedberg/id1502871393',
            'spotify': 'https://open.spotify.com/show/2IqXAVFR4e0Bmyjsdc8QzF',
            'youtube': 'https://www.youtube.com/@alaboratory'
        }
    },
    'Andrew Sullivan': {
        'source_category': 'newsletter',
        'website_url': 'https://andrewsullivan.substack.com/',
        'logo_url': 'https://substackcdn.com/image/fetch/w_256,c_limit,f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fbucketeer-e05bbc84-baa3-437e-9518-adb32be77984.s3.amazonaws.com%2Fpublic%2Fimages%2F0e5a7f67-1c3c-4c69-8ed6-cd7b1f8c4e3e_1280x1280.png',
        'description': 'The Weekly Dish - political commentary from veteran journalist and author Andrew Sullivan.'
    },
    'Ars Technica': {
        'source_category': 'newspaper',
        'website_url': 'https://arstechnica.com/',
        'logo_url': 'https://logo.clearbit.com/arstechnica.com',
        'description': 'Technology news and analysis covering IT, science, gaming, and tech policy with in-depth reporting.'
    },
    'Axios': {
        'source_category': 'newspaper',
        'website_url': 'https://www.axios.com/',
        'logo_url': 'https://logo.clearbit.com/axios.com',
        'description': 'Smart brevity news covering politics, business, technology, and more. Get essential news efficiently.'
    },
    'BBC News': {
        'source_category': 'broadcaster',
        'website_url': 'https://www.bbc.co.uk/news',
        'logo_url': 'https://logo.clearbit.com/bbc.com',
        'description': 'The British Broadcasting Corporation - the world\'s leading public service broadcaster providing impartial news coverage.'
    },
    'Bloomberg': {
        'source_category': 'newspaper',
        'website_url': 'https://www.bloomberg.com/',
        'logo_url': 'https://logo.clearbit.com/bloomberg.com',
        'description': 'Global business and financial news, stock quotes, and market data. Breaking news on world markets, economics, politics, and business.'
    },
    'Brookings Institution': {
        'source_category': 'think_tank',
        'website_url': 'https://www.brookings.edu/',
        'logo_url': 'https://logo.clearbit.com/brookings.edu',
        'description': 'Non-profit public policy research organization providing in-depth analysis and policy recommendations.'
    },
    'Carbon Brief': {
        'source_category': 'newspaper',
        'website_url': 'https://www.carbonbrief.org/',
        'logo_url': 'https://logo.clearbit.com/carbonbrief.org',
        'description': 'UK-based website covering the latest developments in climate science, climate policy and energy policy.'
    },
    'Cato Institute': {
        'source_category': 'think_tank',
        'website_url': 'https://www.cato.org/',
        'logo_url': 'https://logo.clearbit.com/cato.org',
        'description': 'Libertarian think tank dedicated to individual liberty, limited government, free markets and peace.'
    },
    'Christianity Today': {
        'source_category': 'magazine',
        'website_url': 'https://www.christianitytoday.com/',
        'logo_url': 'https://logo.clearbit.com/christianitytoday.com',
        'description': 'Evangelical Christian magazine covering faith, church life, culture, and global Christianity.'
    },
    'City Journal': {
        'source_category': 'magazine',
        'website_url': 'https://www.city-journal.org/',
        'logo_url': 'https://logo.clearbit.com/city-journal.org',
        'description': 'Publication of the Manhattan Institute focusing on urban policy, culture, and economics.'
    },
    'Commonweal': {
        'source_category': 'magazine',
        'website_url': 'https://www.commonwealmagazine.org/',
        'logo_url': 'https://logo.clearbit.com/commonwealmagazine.org',
        'description': 'Liberal Catholic magazine offering independent commentary on religion, politics, and culture.'
    },
    'Diary of a CEO': {
        'source_category': 'podcast',
        'website_url': 'https://www.youtube.com/@TheDiaryOfACEO',
        'logo_url': 'https://yt3.googleusercontent.com/vIVWR6xG3VZkQj-HYXZ1WJfAVLj4vLvMAJgQYv4YW2q5QqE_4-Mv9Z9bK7jxL_mBqG5M=s176-c-k-c0x00ffffff-no-rj',
        'description': 'Conversations with the world\'s most influential people. Hosted by Steven Bartlett.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/the-diary-of-a-ceo-with-steven-bartlett/id1291423644',
            'spotify': 'https://open.spotify.com/show/7iQXmUT7XGuZSzAMjoNWlX',
            'youtube': 'https://www.youtube.com/@TheDiaryOfACEO'
        }
    },
    'Farnam Street': {
        'source_category': 'newsletter',
        'website_url': 'https://fs.blog/',
        'logo_url': 'https://logo.clearbit.com/fs.blog',
        'description': 'Mastering the best of what other people have already figured out. Mental models and timeless wisdom.'
    },
    'Financial Times': {
        'source_category': 'newspaper',
        'website_url': 'https://www.ft.com/',
        'logo_url': 'https://logo.clearbit.com/ft.com',
        'description': 'International daily newspaper with emphasis on business, economic and financial news and analysis.'
    },
    'First Things': {
        'source_category': 'magazine',
        'website_url': 'https://www.firstthings.com/',
        'logo_url': 'https://logo.clearbit.com/firstthings.com',
        'description': 'Journal of religion and public life featuring leading scholars on faith, culture, and public policy.'
    },
    'Foreign Affairs': {
        'source_category': 'magazine',
        'website_url': 'https://www.foreignaffairs.com/',
        'logo_url': 'https://logo.clearbit.com/foreignaffairs.com',
        'description': 'Leading publication on international relations and U.S. foreign policy, published by the Council on Foreign Relations.'
    },
    'Foreign Policy': {
        'source_category': 'magazine',
        'website_url': 'https://foreignpolicy.com/',
        'logo_url': 'https://logo.clearbit.com/foreignpolicy.com',
        'description': 'Global magazine of news and ideas covering foreign affairs, politics, economics, and culture.'
    },
    'Freddie deBoer': {
        'source_category': 'newsletter',
        'website_url': 'https://freddiedeboer.substack.com/',
        'logo_url': 'https://substackcdn.com/image/fetch/w_256,c_limit,f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fbucketeer-e05bbc84-baa3-437e-9518-adb32be77984.s3.amazonaws.com%2Fpublic%2Fimages%2F7d24e5c4-2e36-4a36-8e4e-c28bfa7a7bd6_1280x1280.png',
        'description': 'Writing on education, mental health, politics, and culture from a socialist perspective.'
    },
    'Huberman Lab': {
        'source_category': 'podcast',
        'website_url': 'https://www.hubermanlab.com/',
        'logo_url': 'https://logo.clearbit.com/hubermanlab.com',
        'description': 'Neuroscience and science-based tools for everyday life. Hosted by Stanford professor Andrew Huberman.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/huberman-lab/id1545953110',
            'spotify': 'https://open.spotify.com/show/79CkJF3UJTHFV8Dse3Oy0P',
            'youtube': 'https://www.youtube.com/@hubaboratory'
        }
    },
    'Lawfare': {
        'source_category': 'newspaper',
        'website_url': 'https://www.lawfaremedia.org/',
        'logo_url': 'https://logo.clearbit.com/lawfaremedia.org',
        'description': 'Blog on national security law, covering the hard national security choices and expert legal analysis.'
    },
    'Lex Fridman Podcast': {
        'source_category': 'podcast',
        'website_url': 'https://lexfridman.com/',
        'logo_url': 'https://logo.clearbit.com/lexfridman.com',
        'description': 'Conversations about AI, science, technology, history, philosophy, and the nature of intelligence and consciousness.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/lex-fridman-podcast/id1434243584',
            'spotify': 'https://open.spotify.com/show/2MAi0BvDc6GTFvKFPXnkCL',
            'youtube': 'https://www.youtube.com/@lexfridman'
        }
    },
    'Manhattan Institute': {
        'source_category': 'think_tank',
        'website_url': 'https://www.manhattan-institute.org/',
        'logo_url': 'https://logo.clearbit.com/manhattan-institute.org',
        'description': 'Conservative think tank focused on urban policy, economics, and public policy research.'
    },
    'Marginal Revolution': {
        'source_category': 'newsletter',
        'website_url': 'https://marginalrevolution.com/',
        'logo_url': 'https://logo.clearbit.com/marginalrevolution.com',
        'description': 'Economics blog by Tyler Cowen and Alex Tabarrok covering economics, culture, and ideas.'
    },
    'Matt Taibbi': {
        'source_category': 'newsletter',
        'website_url': 'https://www.racket.news/',
        'logo_url': 'https://logo.clearbit.com/racket.news',
        'description': 'Investigative journalism and media criticism from former Rolling Stone writer Matt Taibbi.'
    },
    'MIT Technology Review': {
        'source_category': 'magazine',
        'website_url': 'https://www.technologyreview.com/',
        'logo_url': 'https://logo.clearbit.com/technologyreview.com',
        'description': 'Oldest technology magazine, covering emerging technologies and their commercial and social impact.'
    },
    'Modern Wisdom': {
        'source_category': 'podcast',
        'website_url': 'https://modernwisdom.com/',
        'logo_url': 'https://logo.clearbit.com/modernwisdom.com',
        'description': 'Conversations on life, philosophy, psychology, and self-improvement. Hosted by Chris Williamson.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/modern-wisdom/id1347973549',
            'spotify': 'https://open.spotify.com/show/6gI0W9EJeuIcMfYlcUUw2X',
            'youtube': 'https://www.youtube.com/@ChrisWillx'
        }
    },
    'National Review': {
        'source_category': 'magazine',
        'website_url': 'https://www.nationalreview.com/',
        'logo_url': 'https://logo.clearbit.com/nationalreview.com',
        'description': 'Leading American conservative editorial magazine founded by William F. Buckley Jr.'
    },
    'New Statesman': {
        'source_category': 'magazine',
        'website_url': 'https://www.newstatesman.com/',
        'logo_url': 'https://logo.clearbit.com/newstatesman.com',
        'description': 'British political and cultural magazine with progressive editorial perspective.'
    },
    'Noahpinion': {
        'source_category': 'newsletter',
        'website_url': 'https://www.noahpinion.blog/',
        'logo_url': 'https://substackcdn.com/image/fetch/w_256,c_limit,f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fbucketeer-e05bbc84-baa3-437e-9518-adb32be77984.s3.amazonaws.com%2Fpublic%2Fimages%2F2cb92c64-89f6-4ed3-8f62-4b0d54bc2ee1_256x256.png',
        'description': 'Economics and policy analysis from Bloomberg Opinion columnist Noah Smith.'
    },
    'Politico EU': {
        'source_category': 'newspaper',
        'website_url': 'https://www.politico.eu/',
        'logo_url': 'https://logo.clearbit.com/politico.eu',
        'description': 'European political journalism covering EU policy, elections, and politics.'
    },
    'ProPublica': {
        'source_category': 'newspaper',
        'website_url': 'https://www.propublica.org/',
        'logo_url': 'https://logo.clearbit.com/propublica.org',
        'description': 'Non-profit investigative journalism organization producing stories in the public interest.'
    },
    'Reason': {
        'source_category': 'magazine',
        'website_url': 'https://reason.com/',
        'logo_url': 'https://logo.clearbit.com/reason.com',
        'description': 'Libertarian magazine covering politics, culture, and ideas with a focus on free markets and individual liberty.'
    },
    'Rest of World': {
        'source_category': 'newspaper',
        'website_url': 'https://restofworld.org/',
        'logo_url': 'https://logo.clearbit.com/restofworld.org',
        'description': 'International journalism covering technology\'s impact outside the Western bubble.'
    },
    'Semafor': {
        'source_category': 'newspaper',
        'website_url': 'https://www.semafor.com/',
        'logo_url': 'https://logo.clearbit.com/semafor.com',
        'description': 'Global news platform with transparent journalism separating facts from analysis and opinion.'
    },
    'Slow Boring': {
        'source_category': 'newsletter',
        'website_url': 'https://www.slowboring.com/',
        'logo_url': 'https://substackcdn.com/image/fetch/w_256,c_limit,f_auto,q_auto:good,fl_progressive:steep/https%3A%2F%2Fbucketeer-e05bbc84-baa3-437e-9518-adb32be77984.s3.amazonaws.com%2Fpublic%2Fimages%2F9ccd8db1-b5af-4bb7-9a34-5e85b4e5bb27_256x256.png',
        'description': 'Policy analysis and political commentary from Matt Yglesias.'
    },
    'South China Morning Post': {
        'source_category': 'newspaper',
        'website_url': 'https://www.scmp.com/',
        'logo_url': 'https://logo.clearbit.com/scmp.com',
        'description': 'Hong Kong-based English-language newspaper covering China, Asia, and international news.'
    },
    'Stratechery': {
        'source_category': 'newsletter',
        'website_url': 'https://stratechery.com/',
        'logo_url': 'https://logo.clearbit.com/stratechery.com',
        'description': 'Analysis of technology and media strategy from Ben Thompson.'
    },
    'TechCrunch': {
        'source_category': 'newspaper',
        'website_url': 'https://techcrunch.com/',
        'logo_url': 'https://logo.clearbit.com/techcrunch.com',
        'description': 'Leading technology media property covering startups, venture capital, and tech innovation.'
    },
    'The American Conservative': {
        'source_category': 'magazine',
        'website_url': 'https://www.theamericanconservative.com/',
        'logo_url': 'https://logo.clearbit.com/theamericanconservative.com',
        'description': 'Conservative magazine focused on traditional values, realist foreign policy, and Main Street economics.'
    },
    'The Atlantic': {
        'source_category': 'magazine',
        'website_url': 'https://www.theatlantic.com/',
        'logo_url': 'https://logo.clearbit.com/theatlantic.com',
        'description': 'American magazine covering news, politics, culture, technology, and more with in-depth features.'
    },
    'The Commentary Magazine': {
        'source_category': 'magazine',
        'website_url': 'https://www.commentary.org/',
        'logo_url': 'https://logo.clearbit.com/commentary.org',
        'description': 'Neoconservative magazine covering politics, culture, and ideas.'
    },
    'The Conversation': {
        'source_category': 'newspaper',
        'website_url': 'https://theconversation.com/',
        'logo_url': 'https://logo.clearbit.com/theconversation.com',
        'description': 'Independent source of news and views from the academic and research community.'
    },
    'The Critic': {
        'source_category': 'magazine',
        'website_url': 'https://thecritic.co.uk/',
        'logo_url': 'https://logo.clearbit.com/thecritic.co.uk',
        'description': 'British intellectual magazine featuring essays on politics, culture, and ideas.'
    },
    'The Dispatch': {
        'source_category': 'newspaper',
        'website_url': 'https://thedispatch.com/',
        'logo_url': 'https://logo.clearbit.com/thedispatch.com',
        'description': 'Fact-based conservative news and commentary focused on policy and politics.'
    },
    'The Economist': {
        'source_category': 'magazine',
        'website_url': 'https://www.economist.com/',
        'logo_url': 'https://logo.clearbit.com/economist.com',
        'description': 'International weekly newspaper focused on current affairs, business, and world politics.'
    },
    'The Ezra Klein Show': {
        'source_category': 'podcast',
        'website_url': 'https://www.nytimes.com/column/ezra-klein-podcast',
        'logo_url': 'https://static01.nyt.com/images/2021/01/12/podcasts/ezra-klein-show-album-art/ezra-klein-show-album-art-square320.jpg',
        'description': 'Political and policy conversations exploring ideas that shape our world. Hosted by Ezra Klein for The New York Times.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/the-ezra-klein-show/id1548604447',
            'spotify': 'https://open.spotify.com/show/3oB5noYIwEB2dMAREj2F7S',
        }
    },
    'The Free Press': {
        'source_category': 'newspaper',
        'website_url': 'https://www.thefp.com/',
        'logo_url': 'https://logo.clearbit.com/thefp.com',
        'description': 'Independent journalism committed to covering stories others won\'t. Founded by Bari Weiss.'
    },
    'The Guardian': {
        'source_category': 'newspaper',
        'website_url': 'https://www.theguardian.com/',
        'logo_url': 'https://logo.clearbit.com/theguardian.com',
        'description': 'British daily newspaper with progressive editorial perspective and global coverage.'
    },
    'The Independent': {
        'source_category': 'newspaper',
        'website_url': 'https://www.independent.co.uk/',
        'logo_url': 'https://logo.clearbit.com/independent.co.uk',
        'description': 'British online newspaper offering news, views, and analysis on UK and world events.'
    },
    'The Intercept': {
        'source_category': 'newspaper',
        'website_url': 'https://theintercept.com/',
        'logo_url': 'https://logo.clearbit.com/theintercept.com',
        'description': 'Investigative journalism with a focus on national security, politics, and civil liberties.'
    },
    'The New Yorker': {
        'source_category': 'magazine',
        'website_url': 'https://www.newyorker.com/',
        'logo_url': 'https://logo.clearbit.com/newyorker.com',
        'description': 'American magazine featuring journalism, commentary, criticism, essays, fiction, and cartoons.'
    },
    'The News Agents': {
        'source_category': 'podcast',
        'website_url': 'https://www.globalplayer.com/podcasts/42KuWz/',
        'logo_url': 'https://images.globalplayer.com/images/551315?width=300',
        'description': 'UK political news podcast with Emily Maitlis, Jon Sopel, and Lewis Goodall. Making sense of the news.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/the-news-agents/id1640722469',
            'spotify': 'https://open.spotify.com/show/5yNr9AjGBvqPtv9VG8dcSC',
        }
    },
    'The Rest Is Politics': {
        'source_category': 'podcast',
        'website_url': 'https://www.therestispolitics.com/',
        'logo_url': 'https://logo.clearbit.com/therestispolitics.com',
        'description': 'Political commentary from both sides of the aisle with Alastair Campbell (left) and Rory Stewart (right).',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/the-rest-is-politics/id1614231270',
            'spotify': 'https://open.spotify.com/show/1qJ0JH3RzHRMZyEz4g6N1r',
            'youtube': 'https://www.youtube.com/@TheRestIsPolitics'
        }
    },
    'The Spectator': {
        'source_category': 'magazine',
        'website_url': 'https://www.spectator.co.uk/',
        'logo_url': 'https://logo.clearbit.com/spectator.co.uk',
        'description': 'British conservative weekly magazine covering politics, culture, and current affairs.'
    },
    'The Telegraph': {
        'source_category': 'newspaper',
        'website_url': 'https://www.telegraph.co.uk/',
        'logo_url': 'https://logo.clearbit.com/telegraph.co.uk',
        'description': 'British broadsheet newspaper with conservative editorial perspective.'
    },
    'The Tim Ferriss Show': {
        'source_category': 'podcast',
        'website_url': 'https://tim.blog/podcast/',
        'logo_url': 'https://logo.clearbit.com/tim.blog',
        'description': 'World-class performers share tactics, tools, and routines. Hosted by Tim Ferriss.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/the-tim-ferriss-show/id863897795',
            'spotify': 'https://open.spotify.com/show/5qSUyCrk9KR69lEiXbjwXM',
            'youtube': 'https://www.youtube.com/@timferriss'
        }
    },
    'Triggernometry': {
        'source_category': 'podcast',
        'website_url': 'https://www.triggernometry.com/',
        'logo_url': 'https://logo.clearbit.com/triggernometry.com',
        'description': 'Long-form conversations on politics, culture, and free speech with Konstantin Kisin and Francis Foster.',
        'podcast_urls': {
            'apple': 'https://podcasts.apple.com/podcast/triggernometry/id1375568988',
            'spotify': 'https://open.spotify.com/show/1A3tRBQmz3VNhBCNIJ0YpI',
            'youtube': 'https://www.youtube.com/@triggerpod'
        }
    },
    'UnHerd': {
        'source_category': 'newspaper',
        'website_url': 'https://unherd.com/',
        'logo_url': 'https://logo.clearbit.com/unherd.com',
        'description': 'Independent British online magazine challenging mainstream thinking with diverse viewpoints.'
    },
    'War on the Rocks': {
        'source_category': 'newspaper',
        'website_url': 'https://warontherocks.com/',
        'logo_url': 'https://logo.clearbit.com/warontherocks.com',
        'description': 'Platform for analysis, commentary, and debate on foreign policy and national security.'
    }
}


def update_all_sources():
    """Update all sources with metadata from SOURCE_METADATA."""
    updated = 0
    not_found = []
    
    for source_name, metadata in SOURCE_METADATA.items():
        source = NewsSource.query.filter_by(name=source_name).first()
        
        if not source:
            not_found.append(source_name)
            continue
        
        if metadata.get('source_category'):
            source.source_category = metadata['source_category']
        if metadata.get('website_url'):
            source.website_url = metadata['website_url']
        if metadata.get('logo_url'):
            source.logo_url = metadata['logo_url']
        if metadata.get('description'):
            source.description = metadata['description']
        
        source.updated_at = datetime.utcnow()
        updated += 1
        print(f"Updated: {source_name}")
    
    db.session.commit()
    
    print(f"\n=== Summary ===")
    print(f"Updated: {updated} sources")
    print(f"Not found: {len(not_found)} sources")
    if not_found:
        print(f"Missing sources: {', '.join(not_found)}")
    
    return {'updated': updated, 'not_found': not_found}


def get_podcast_urls(source_name):
    """Get podcast platform URLs for a source."""
    metadata = SOURCE_METADATA.get(source_name, {})
    return metadata.get('podcast_urls', {})


if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        update_all_sources()
