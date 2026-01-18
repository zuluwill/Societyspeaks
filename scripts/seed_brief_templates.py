"""
Seed script for Brief Template marketplace.
Creates the 12 template archetypes for individuals and organizations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import BriefTemplate

# Sample email outputs for each template - realistic examples showing email quality
SAMPLE_OUTPUTS = {
    'politics-public-policy': """<h2 style="margin: 0 0 16px 0; font-size: 20px; color: #1e3a5f;">What Changed This Week</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">EU AI Act Implementation Timeline Announced</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">The European Commission published detailed implementation guidelines for the AI Act, setting compliance deadlines for high-risk AI systems. Companies operating in the EU will need to complete risk assessments by August 2025, with full compliance required by 2026.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>What it means:</strong> Organizations using AI for hiring, credit scoring, or public services should begin compliance audits now.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: European Commission, Reuters</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">US Infrastructure Funding Allocations Released</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">The Department of Transportation announced $12B in new allocations for broadband expansion in rural areas. Grants will be distributed through state agencies, with applications opening in Q2 2026.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Next steps:</strong> State agencies have 60 days to submit implementation plans.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: Department of Transportation, AP</p>
</div>

<div style="margin-bottom: 24px;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">UK Data Protection Bill Advances</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">The Data Protection and Digital Information Bill passed its third reading in the House of Lords. Key changes include simplified consent mechanisms for research purposes and new rules for international data transfers post-Brexit.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Timeline:</strong> Royal Assent expected within 6 weeks.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: UK Parliament, Financial Times</p>
</div>""",

    'technology-ai-regulation': """<h2 style="margin: 0 0 16px 0; font-size: 20px; color: #1e3a5f;">Tech & AI Update</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">OpenAI Releases GPT-5 API with Enhanced Safety Controls</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">OpenAI launched GPT-5 with new capabilities for code generation and reasoning tasks. The release includes mandatory content filtering for enterprise customers and improved rate limiting. Pricing starts at $0.03 per 1K tokens for input.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Key detail:</strong> Context window expanded to 256K tokens. API documentation updated with new function calling patterns.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: OpenAI Blog, The Verge</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">NIST Publishes AI Risk Management Framework Update</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">The National Institute of Standards and Technology released version 2.0 of its AI Risk Management Framework, adding specific guidance for generative AI systems. New sections cover prompt injection prevention and output validation.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Action item:</strong> Review updated governance profiles if operating AI systems in regulated industries.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: NIST, Ars Technica</p>
</div>

<div style="margin-bottom: 24px;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">GitHub Copilot Adds Enterprise Compliance Features</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">GitHub announced new enterprise features for Copilot including code provenance tracking, license compliance checks, and audit logs. The update also includes organization-wide policy controls for code suggestions.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: GitHub Blog, TechCrunch</p>
</div>""",

    'economy-markets': """<h2 style="margin: 0 0 16px 0; font-size: 20px; color: #1e3a5f;">Economic Trends This Week</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">US Inflation Continues Gradual Decline</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">CPI data showed headline inflation at 2.4% year-over-year, down from 2.6% last month. Core inflation (excluding food and energy) remains elevated at 3.1%. Shelter costs continue to be the primary driver of stickiness.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Trend direction:</strong> Gradual easing, but pace slower than Fed projections. Markets pricing in one more rate cut this year.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: Bureau of Labor Statistics, Bloomberg</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Eurozone Manufacturing Shows Signs of Stabilization</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">PMI data for the Eurozone rose to 48.2, still in contraction territory but the highest reading in 8 months. Germany and France showed modest improvement, while Southern Europe remained stronger.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Context:</strong> Readings below 50 indicate contraction. Current trajectory suggests potential return to expansion by Q2.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: S&P Global, Financial Times</p>
</div>

<div style="margin-bottom: 24px;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Labour Market Update</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">US jobless claims remained steady at 215K. UK unemployment ticked up to 4.3%, while wage growth moderated to 5.2% annually. Labour market conditions remain tight by historical standards but are gradually normalizing.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: BLS, ONS, Reuters</p>
</div>""",

    'climate-energy-planet': """<h2 style="margin: 0 0 16px 0; font-size: 20px; color: #1e3a5f;">Climate & Energy Update</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">EU Carbon Border Adjustment Mechanism Enters Full Implementation</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">CBAM requirements for importers of steel, cement, aluminum, and fertilizers now require full carbon content declarations. Companies must purchase certificates matching embedded emissions by April 2026.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Implications:</strong> Impacts supply chains with significant non-EU manufacturing. Many companies restructuring procurement.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: European Commission, Carbon Brief</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Global Renewable Capacity Additions Set New Record</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">IEA data shows 2025 on track for 560GW of new renewable capacity, up 25% from 2024. Solar accounts for 75% of additions. China, US, and India lead deployment, with grid integration becoming the primary constraint.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Challenge:</strong> Grid infrastructure investment lagging generation growth by 40%.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: International Energy Agency, Bloomberg NEF</p>
</div>

<div style="margin-bottom: 24px;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Battery Storage Costs Continue Decline</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">Lithium-ion battery pack prices fell to $115/kWh, down 12% year-over-year. Sodium-ion alternatives gaining traction for stationary storage, with several utility-scale projects announced in Australia and Germany.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: BloombergNEF, Clean Energy Wire</p>
</div>""",

    'sport-state-of-play': """<h2 style="margin: 0 0 16px 0; font-size: 20px; color: #1e3a5f;">Sport - What Matters</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Premier League Title Race Tightens</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">Arsenal moved within two points of Liverpool after a 3-1 win against Manchester United. City's draw at Newcastle keeps them in contention, four points behind with a game in hand. Key fixture: Arsenal vs Liverpool at Emirates Stadium next Saturday.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Standings:</strong> Liverpool 58pts | Arsenal 56pts | Man City 54pts (1 game in hand)</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: BBC Sport, The Athletic</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Australian Open Finals Preview</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">Jannik Sinner faces Carlos Alcaraz in the men's final after both navigated tough semi-final matches. Women's final features Iga Swiatek against Aryna Sabalenka in a rematch of last year's final.</p>
<p style="margin: 0; font-size: 14px; color: #6b7280;"><strong>Head-to-head:</strong> Alcaraz leads 5-4 overall, but Sinner won their last hard court meeting.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: ATP Tour, WTA</p>
</div>

<div style="margin-bottom: 24px;">
<h3 style="margin: 0 0 8px 0; font-size: 17px; color: #1f2937;">Six Nations Round 2 Results</h3>
<p style="margin: 0 0 12px 0; color: #4b5563;">Ireland maintained their title defense with a 28-17 win over England in Dublin. France defeated Scotland in Paris, while Wales secured their first win against Italy. Ireland and France remain unbeaten after two rounds.</p>
<p style="margin: 8px 0 0 0; font-size: 13px; color: #9ca3af;">Source: World Rugby, The Guardian</p>
</div>""",
}

# Recommended sources for each template category
RECOMMENDED_SOURCES = {
    'politics-public-policy': [
        {'name': 'Reuters Politics', 'url': 'https://www.reuters.com/world/', 'type': 'rss'},
        {'name': 'AP News Government', 'url': 'https://apnews.com/hub/government-and-politics', 'type': 'rss'},
        {'name': 'The Guardian Politics', 'url': 'https://www.theguardian.com/politics', 'type': 'rss'},
        {'name': 'Politico', 'url': 'https://www.politico.com', 'type': 'rss'},
    ],
    'technology-ai-regulation': [
        {'name': 'Ars Technica', 'url': 'https://arstechnica.com', 'type': 'rss'},
        {'name': 'TechCrunch', 'url': 'https://techcrunch.com', 'type': 'rss'},
        {'name': 'The Verge', 'url': 'https://www.theverge.com', 'type': 'rss'},
        {'name': 'Wired', 'url': 'https://www.wired.com', 'type': 'rss'},
    ],
    'economy-markets': [
        {'name': 'Financial Times', 'url': 'https://www.ft.com', 'type': 'rss'},
        {'name': 'Bloomberg', 'url': 'https://www.bloomberg.com', 'type': 'rss'},
        {'name': 'The Economist', 'url': 'https://www.economist.com', 'type': 'rss'},
        {'name': 'Reuters Business', 'url': 'https://www.reuters.com/business/', 'type': 'rss'},
    ],
    'climate-energy-planet': [
        {'name': 'Carbon Brief', 'url': 'https://www.carbonbrief.org', 'type': 'rss'},
        {'name': 'Clean Energy Wire', 'url': 'https://www.cleanenergywire.org', 'type': 'rss'},
        {'name': 'Bloomberg Green', 'url': 'https://www.bloomberg.com/green', 'type': 'rss'},
        {'name': 'The Guardian Environment', 'url': 'https://www.theguardian.com/environment', 'type': 'rss'},
    ],
    'sport-state-of-play': [
        {'name': 'BBC Sport', 'url': 'https://www.bbc.com/sport', 'type': 'rss'},
        {'name': 'The Athletic', 'url': 'https://theathletic.com', 'type': 'rss'},
        {'name': 'ESPN', 'url': 'https://www.espn.com', 'type': 'rss'},
        {'name': 'Sky Sports', 'url': 'https://www.skysports.com', 'type': 'rss'},
    ],
}

TEMPLATES = [
    # CATEGORY A - Core Insight Templates
    {
        'name': 'Politics & Public Policy',
        'slug': 'politics-public-policy',
        'description': 'Track policy movement, legislative changes, and regulatory updates without the political drama.',
        'tagline': 'What Changed',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'landmark',
        'is_featured': True,
        'sort_order': 1,
        'default_cadence': 'daily',
        'default_tone': 'calm_neutral',
        'sample_output': SAMPLE_OUTPUTS.get('politics-public-policy', ''),
        'default_sources': RECOMMENDED_SOURCES.get('politics-public-policy', []),
        'default_filters': {
            'topics': ['Politics', 'Policy', 'Government', 'Legislation'],
            'geography': 'configurable',
            'level': ['national', 'regional', 'supranational'],
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 10,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'what_changed',
        },
        'custom_prompt_prefix': 'Focus on what actually changed in policy, legislation, or regulation. Avoid horse-race politics, personality drama, or outrage framing. Emphasize implications and next steps.',
        'focus_keywords': ['legislation', 'policy', 'regulation', 'bill', 'law', 'government', 'parliament', 'congress'],
        'exclude_keywords': ['scandal', 'outrage', 'slams', 'destroys', 'blasts'],
    },
    {
        'name': 'Technology, AI & Regulation',
        'slug': 'technology-ai-regulation',
        'description': 'Replace multiple tech newsletters with one calm, signal-focused brief on technical developments and regulation.',
        'tagline': 'Signal over Hype',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'cpu',
        'is_featured': True,
        'sort_order': 2,
        'default_cadence': 'daily',
        'default_tone': 'calm_neutral',
        'sample_output': SAMPLE_OUTPUTS.get('technology-ai-regulation', ''),
        'default_sources': RECOMMENDED_SOURCES.get('technology-ai-regulation', []),
        'default_filters': {
            'topics': ['Technology', 'AI', 'Cybersecurity', 'Regulation'],
            'sub_domains': ['AI', 'cyber', 'SaaS', 'hardware'],
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 10,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'standard',
        },
        'custom_prompt_prefix': 'Focus on technical developments, regulation, standards, and major releases. Separate signal from marketing hype. Avoid influencer commentary and speculation.',
        'focus_keywords': ['AI', 'regulation', 'standard', 'release', 'update', 'security', 'protocol'],
        'exclude_keywords': ['hype', 'game-changer', 'revolutionary', 'disruptive'],
    },
    {
        'name': 'Economy & Markets',
        'slug': 'economy-markets',
        'description': 'Macro understanding without anxiety. Focus on trends and implications, not daily price movements.',
        'tagline': 'Trends, Not Ticks',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'trending-up',
        'is_featured': True,
        'sort_order': 3,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'sample_output': SAMPLE_OUTPUTS.get('economy-markets', ''),
        'default_sources': RECOMMENDED_SOURCES.get('economy-markets', []),
        'default_filters': {
            'topics': ['Economy', 'Markets', 'Finance'],
            'focus': ['inflation', 'growth', 'labour', 'rates'],
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['weekly'],
        },
        'guardrails': {
            'max_items': 8,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'trends',
        },
        'custom_prompt_prefix': 'Synthesize macro trends: inflation, growth, labour markets, rates. Focus on direction and implications, not daily price moves. Avoid trading language.',
        'focus_keywords': ['inflation', 'GDP', 'employment', 'rates', 'growth', 'trend'],
        'exclude_keywords': ['crash', 'soar', 'plunge', 'moon', 'prediction'],
    },
    {
        'name': 'Climate, Energy & the Planet',
        'slug': 'climate-energy-planet',
        'description': 'High-importance, low-noise clarity on climate policy, energy systems, and environmental science.',
        'tagline': "What's Actually Moving",
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'globe',
        'is_featured': True,
        'sort_order': 4,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'sample_output': SAMPLE_OUTPUTS.get('climate-energy-planet', ''),
        'default_sources': RECOMMENDED_SOURCES.get('climate-energy-planet', []),
        'default_filters': {
            'topics': ['Climate', 'Environment', 'Energy'],
            'focus': ['policy', 'energy transition', 'science'],
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 8,
            'require_attribution': True,
            'no_predictions': False,
            'no_outrage_framing': True,
            'structure_template': 'standard',
        },
        'custom_prompt_prefix': 'Track policy, energy systems, and climate science. Emphasize realism over alarmism. Avoid activist outrage framing or apocalyptic headlines.',
        'focus_keywords': ['climate', 'energy', 'renewable', 'emissions', 'transition', 'policy'],
        'exclude_keywords': ['catastrophe', 'doom', 'apocalypse', 'crisis'],
    },
    
    # CATEGORY B - Organizational Templates
    {
        'name': 'Policy Monitoring Brief',
        'slug': 'policy-monitoring',
        'description': 'Monitor legislation, regulatory updates, and consultations for your organization. Replaces analyst time.',
        'tagline': 'What Changed, Why It Matters, What to Watch',
        'category': 'organizational',
        'audience_type': 'organization',
        'icon': 'file-text',
        'is_featured': True,
        'sort_order': 1,
        'default_cadence': 'daily',
        'default_tone': 'formal',
        'default_filters': {
            'topics': ['Policy', 'Regulation', 'Legislation'],
            'domains': 'configurable',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': True,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 15,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'policy_monitoring',
        },
        'custom_prompt_prefix': 'Structure as: What Changed, Why It Matters, What to Watch. Focus on actionable policy intelligence for organizational decision-making.',
        'focus_keywords': ['legislation', 'regulation', 'consultation', 'amendment', 'directive'],
        'exclude_keywords': [],
    },
    {
        'name': 'Sector Intelligence Brief',
        'slug': 'sector-intelligence',
        'description': 'Keep your team or members informed about sector news, regulation, competitors, and research.',
        'tagline': 'Industry Intelligence',
        'category': 'organizational',
        'audience_type': 'organization',
        'icon': 'briefcase',
        'is_featured': False,
        'sort_order': 2,
        'default_cadence': 'weekly',
        'default_tone': 'formal',
        'default_filters': {
            'sector': 'configurable',
            'topics': ['Industry', 'Business', 'Competition'],
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': True,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 12,
            'require_attribution': True,
            'no_predictions': False,
            'no_outrage_framing': True,
            'structure_template': 'sector',
        },
        'custom_prompt_prefix': 'Track sector news, regulation, competitors, and research. Structure for consistent organizational consumption.',
        'focus_keywords': ['industry', 'market', 'competitor', 'research', 'trend'],
        'exclude_keywords': [],
    },
    {
        'name': 'Internal Research Brief',
        'slug': 'internal-research',
        'description': 'Synthesize uploaded PDFs, internal documents, and research papers. Surface themes, gaps, and questions.',
        'tagline': 'Knowledge Synthesis',
        'category': 'organizational',
        'audience_type': 'organization',
        'icon': 'book-open',
        'is_featured': False,
        'sort_order': 3,
        'default_cadence': 'weekly',
        'default_tone': 'formal',
        'default_filters': {
            'source_type': 'uploaded_documents',
            'topics': [],
        },
        'configurable_options': {
            'geography': False,
            'sources': True,
            'cadence': True,
            'visibility': False,
            'auto_send': True,
            'tone': True,
            'cadence_options': ['weekly', 'monthly'],
        },
        'guardrails': {
            'max_items': 10,
            'require_attribution': True,
            'no_predictions': False,
            'no_outrage_framing': False,
            'structure_template': 'research',
            'visibility_locked': 'private',
        },
        'custom_prompt_prefix': 'Synthesize internal documents and research. Surface themes, gaps, and unresolved questions. Never use news-driven framing.',
        'focus_keywords': ['research', 'finding', 'conclusion', 'recommendation', 'analysis'],
        'exclude_keywords': [],
    },
    {
        'name': 'Thought Leadership Brief',
        'slug': 'thought-leadership',
        'description': 'Produce calm, cited summaries for external publication. Build authority safely without marketing language.',
        'tagline': 'External Authority',
        'category': 'organizational',
        'audience_type': 'organization',
        'icon': 'award',
        'is_featured': False,
        'sort_order': 4,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'default_filters': {
            'topics': 'configurable',
            'visibility': 'public',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': False,
            'tone': True,
            'cadence_options': ['weekly'],
        },
        'guardrails': {
            'max_items': 5,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'thought_leadership',
        },
        'custom_prompt_prefix': 'Produce calm, well-cited summaries suitable for external publication. Build organizational authority safely. Avoid marketing language or growth hacking.',
        'focus_keywords': ['insight', 'analysis', 'perspective', 'trend'],
        'exclude_keywords': ['growth hack', 'viral', 'engagement'],
    },
    
    # CATEGORY C - Personal Interest Templates
    {
        'name': 'Sport - State of Play',
        'slug': 'sport-state-of-play',
        'description': 'Results, key changes, and what matters going forward. No gossip or transfer rumour churn.',
        'tagline': 'What Matters in Sport',
        'category': 'personal_interest',
        'audience_type': 'individual',
        'icon': 'activity',
        'is_featured': True,
        'sort_order': 1,
        'default_cadence': 'daily',
        'default_tone': 'conversational',
        'sample_output': SAMPLE_OUTPUTS.get('sport-state-of-play', ''),
        'default_sources': RECOMMENDED_SOURCES.get('sport-state-of-play', []),
        'default_filters': {
            'topics': ['Sport'],
            'sports': 'configurable',
            'leagues': 'configurable',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': True,
            'cadence_options': ['daily', 'matchday'],
        },
        'guardrails': {
            'max_items': 10,
            'require_attribution': True,
            'no_predictions': False,
            'no_outrage_framing': True,
            'structure_template': 'sport',
        },
        'custom_prompt_prefix': 'Summarize results, key changes (injuries, form, tactics), and what matters going forward. Avoid gossip and transfer rumour churn.',
        'focus_keywords': ['result', 'score', 'match', 'game', 'performance', 'standing'],
        'exclude_keywords': ['rumour', 'WAG', 'scandal', 'controversy'],
    },
    {
        'name': 'Crypto & Digital Assets',
        'slug': 'crypto-digital-assets',
        'description': 'Protocol changes, regulation, and ecosystem health. Price mentioned only as context, never as signals.',
        'tagline': 'Signal, Not Speculation',
        'category': 'personal_interest',
        'audience_type': 'individual',
        'icon': 'bitcoin',
        'is_featured': False,
        'sort_order': 2,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'default_filters': {
            'topics': ['Cryptocurrency', 'Blockchain', 'Digital Assets'],
            'assets': 'configurable',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['daily', 'weekly'],
        },
        'guardrails': {
            'max_items': 8,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'standard',
        },
        'custom_prompt_prefix': 'Track protocol changes, regulation, and ecosystem health. Mention price only as context, never as trading signals. Avoid hype language and predictions.',
        'focus_keywords': ['protocol', 'regulation', 'update', 'governance', 'security'],
        'exclude_keywords': ['moon', 'pump', 'dump', 'prediction', 'signal', '100x'],
    },
    {
        'name': 'Trending Topics',
        'slug': 'trending-topics',
        'description': 'What people are talking about and why. Focus on themes, not viral posts or outrage.',
        'tagline': "What's Resonating",
        'category': 'personal_interest',
        'audience_type': 'individual',
        'icon': 'hash',
        'is_featured': False,
        'sort_order': 3,
        'default_cadence': 'daily',
        'default_tone': 'conversational',
        'default_filters': {
            'source_mix': ['news', 'social', 'blogs'],
            'sensitivity': 'moderate',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': True,
            'cadence_options': ['daily'],
        },
        'guardrails': {
            'max_items': 8,
            'require_attribution': True,
            'no_predictions': False,
            'no_outrage_framing': True,
            'structure_template': 'trending',
        },
        'custom_prompt_prefix': 'Identify emerging themes and why they resonate. Focus on themes, not viral posts. Avoid ranking people or amplifying outrage.',
        'focus_keywords': ['trend', 'theme', 'discussion', 'conversation'],
        'exclude_keywords': ['viral', 'outrage', 'cancelled', 'slammed'],
    },
    
    # CATEGORY D - Lifestyle
    {
        'name': 'Health, Science & Medicine',
        'slug': 'health-science-medicine',
        'description': 'Research updates and guideline changes presented with appropriate uncertainty and consensus context.',
        'tagline': 'Non-Sensational',
        'category': 'lifestyle',
        'audience_type': 'all',
        'icon': 'heart',
        'is_featured': False,
        'sort_order': 1,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'default_filters': {
            'topics': ['Health', 'Science', 'Medicine'],
            'domains': 'configurable',
        },
        'configurable_options': {
            'geography': True,
            'sources': True,
            'cadence': True,
            'visibility': True,
            'auto_send': True,
            'tone': False,
            'cadence_options': ['weekly'],
        },
        'guardrails': {
            'max_items': 8,
            'require_attribution': True,
            'no_predictions': True,
            'no_outrage_framing': True,
            'structure_template': 'standard',
        },
        'custom_prompt_prefix': 'Summarize research updates and guideline changes. Emphasize uncertainty where appropriate and consensus context. Never sensationalize health claims.',
        'focus_keywords': ['research', 'study', 'guideline', 'evidence', 'trial'],
        'exclude_keywords': ['miracle', 'cure', 'breakthrough', 'shocking'],
    },
]


def seed_templates():
    """Insert or update all template definitions."""
    app = create_app()
    
    with app.app_context():
        created = 0
        updated = 0
        
        for template_data in TEMPLATES:
            existing = BriefTemplate.query.filter_by(slug=template_data['slug']).first()
            
            if existing:
                # Update existing template
                for key, value in template_data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                updated += 1
                print(f"Updated: {template_data['name']}")
            else:
                # Create new template
                template = BriefTemplate(**template_data)
                db.session.add(template)
                created += 1
                print(f"Created: {template_data['name']}")
        
        db.session.commit()
        print(f"\nDone! Created: {created}, Updated: {updated}")


if __name__ == '__main__':
    seed_templates()
