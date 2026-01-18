"""
Seed script for Brief Template marketplace.
Creates the 12 template archetypes for individuals and organizations.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import BriefTemplate

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
