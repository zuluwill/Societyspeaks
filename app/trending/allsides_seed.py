"""
Multi-Source Media Bias Ratings Seed Data

This file uses a hierarchy of rating sources for maximum accuracy:
1. AllSides.com - Primary source for US/UK mainstream news (blind survey methodology)
2. Media Bias/Fact Check (MBFC) - Secondary source for broader coverage (8,000+ sources)
3. Ad Fontes Media - Tertiary source when others disagree
4. Manual - Only for sources not rated by any service

Scale: -2 (Left) to +2 (Right), with 0 as Center.
Supports 0.5 increments for nuanced positioning.

Source types:
- 'allsides': Official AllSides.com rating
- 'mbfc': Media Bias/Fact Check rating
- 'adfontesmedia': Ad Fontes Media rating
- 'manual': Team assessment (documented rationale required)

For podcasts/newsletters not rated by any service, ratings are based on:
- Host political positioning
- Guest selection patterns
- Editorial perspectives
- Content focus areas

Note: Sources focused on business/lifestyle without political content are rated Center (0).

Color scheme uses US-style political colors:
- Blue (#0066CC) for Left
- Light Blue (#6699FF) for Lean Left
- Purple (#9933CC) for Center
- Light Red (#FF6B6B) for Lean Right
- Red (#CC0000) for Right

Last updated: January 2026
"""

from datetime import datetime
from app import db
from app.models import NewsSource
import logging

logger = logging.getLogger(__name__)

# Version for tracking when ratings were last updated
# Increment this when making rating changes to force updates
RATINGS_VERSION = '2026.01.27'


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
    # Note: 'The Ezra Klein Show' replaced by 'Ezra Klein' (Substack newsletter)
    # 'The Ezra Klein Show': {
    #     'leaning': -2.0,  # Left
    #     'source': 'manual',
    #     'notes': 'NYT politics and policy podcast, left editorial perspective'
    # },
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
        'leaning': -1.0,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Matt Yglesias policy analysis, centre-left wonk. MBFC: Left-Center, High factual'
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
        'leaning': -1.0,  # Lean Left (AllSides Oct 2022 editorial review, added to chart v10)
        'source': 'allsides',
        'notes': 'Global news with transparent sourcing. AllSides: Lean Left (-1.5)'
    },
    'Rest of World': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'International tech and society coverage'
    },
    'The Conversation': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Academic experts writing for public audience. MBFC: Least Biased, Very High factual'
    },
    'Al Jazeera English': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Qatar-based, non-Western global perspective'
    },
    'Lawfare': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Legal and national security analysis, expert-driven. MBFC: Least Biased, Very High factual'
    },
    'MIT Technology Review': {
        'leaning': 0,  # Center
        'source': 'manual',
        'notes': 'Authoritative on AI, biotech, climate tech'
    },
    'Carbon Brief': {
        'leaning': -0.5,  # Left-Center, Pro-Science per MBFC
        'source': 'mbfc',
        'notes': 'Climate science and policy, factual/data-driven. MBFC: Left-Center/Pro-Science, High factual'
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
    # Note: Lex Fridman Podcast and Huberman Lab removed - not currently in news_fetcher.py seed list
    # If added in future, uncomment these entries
    # 'Lex Fridman Podcast': {
    #     'leaning': 0,  # Center
    #     'source': 'manual',
    #     'notes': 'Long-form conversations on AI, science, philosophy with diverse guests'
    # },
    # 'Huberman Lab': {
    #     'leaning': 0,  # Center
    #     'source': 'manual',
    #     'notes': 'Neuroscience and science-based health, generally apolitical'
    # },
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
    'Politico': {
        'leaning': -1.0,  # Lean Left
        'source': 'allsides',
        'notes': 'Rated Lean Left by AllSides, though blind survey rated Center'
    },
    'Deutsche Welle': {
        'leaning': 0,  # Center
        'source': 'allsides',
        'notes': 'Rated Center by AllSides, German public broadcaster'
    },
    'Haaretz': {
        'leaning': -1.0,  # Lean Left
        'source': 'allsides',
        'notes': 'Rated Lean Left by AllSides, Israeli newspaper'
    },
    'Vox': {
        'leaning': -2.0,  # Left (confirmed by AllSides Aug 2023 blind survey)
        'source': 'allsides',
        'notes': 'Explanatory journalism, progressive perspective. AllSides: Left (-3.49)'
    },
    'The New York Times': {
        'leaning': -1.0,  # Lean Left
        'source': 'allsides',
        'notes': 'Rated Lean Left by AllSides'
    },
    'Wall Street Journal': {
        'leaning': 0.5,  # Centre-Right
        'source': 'allsides',
        'notes': 'Rated Lean Right by AllSides, business-focused'
    },
    'Yascha Mounk': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'Persuasion newsletter, big ideas, center-left perspective'
    },
    'Ezra Klein': {
        'leaning': -1.0,  # Lean Left
        'source': 'manual',
        'notes': 'NYT columnist, policy analysis, left perspective'
    },
    'Anne Applebaum': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'Atlantic staff writer, democracy and foreign affairs'
    },
    'Jonathan Rauch': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'Brookings senior fellow, liberalism and institutions'
    },
    'Zeynep Tufekci': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'NYT columnist, tech and society analysis'
    },
    'Francis Fukuyama': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Stanford fellow, democracy and development, center perspective'
    },
    'Platformer': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Casey Newton, Silicon Valley and democracy, generally apolitical'
    },
    'Not Boring': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Packy McCormick, tech strategy, apolitical'
    },
    'The Pragmatic Engineer': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Gergely Orosz, Big Tech and startups, apolitical'
    },
    'Simon Willison': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Tech, programming, data, apolitical'
    },
    'Paul Graham': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Essays on startups, programming, life, apolitical'
    },
    'Cory Doctorow': {
        'leaning': -1.0,  # Lean Left
        'source': 'manual',
        'notes': 'Tech, politics, culture, progressive perspective'
    },
    'Institute for Government': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UK government effectiveness think tank, non-partisan'
    },
    'Institute for Fiscal Studies': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UK fiscal policy research, non-partisan'
    },
    'Resolution Foundation': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UK living standards think tank, non-partisan'
    },
    'UK Parliament': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Official parliamentary proceedings, non-partisan'
    },
    'RAND Corporation': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Policy research, objective analysis. MBFC: Least Biased/Pro-Science, High factual'
    },
    'Chatham House': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'International affairs think tank. MBFC: Least Biased, High factual'
    },
    'CSIS': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Center for Strategic and International Studies. MBFC: Least Biased, Very High factual'
    },
    'OECD': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Economic policy, international cooperation, non-partisan'
    },
    'World Bank': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Development economics, global poverty, non-partisan'
    },
    'IMF': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Monetary policy, global finance, non-partisan'
    },
    'Office for National Statistics': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Official UK statistics, non-partisan'
    },
    'Office for Budget Responsibility': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UK fiscal forecasts, non-partisan'
    },
    'Pew Research Center': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Nonpartisan fact tank, data-driven research. MBFC: Least Biased, Very High factual'
    },
    'Our World in Data': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Data-driven research on global problems. MBFC: Left-Center, High factual'
    },
    'Eurostat': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Official EU statistics, non-partisan'
    },
    'US Census Bureau': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Official US demographic and economic data, non-partisan'
    },
    'Nieman Lab': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Future of journalism, non-partisan'
    },
    'Columbia Journalism Review': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Media criticism and analysis, non-partisan'
    },
    'Poynter': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Journalism education and ethics, non-partisan'
    },
    'The Times': {
        'leaning': 1.0,  # Lean Right
        'source': 'manual',
        'notes': 'UK broadsheet, conservative perspective'
    },
    'BBC World Service': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Global news service, mandated impartiality'
    },
    'Euractiv': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'EU policy news, generally center'
    },
    'Carnegie Endowment': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'International affairs think tank. MBFC: Left-Center, High factual'
    },
    'International Crisis Group': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Conflict prevention research. MBFC: Left-Center, Very High factual'
    },
    'World Economic Forum': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Global economic analysis. MBFC: Left-Center, High factual'
    },
    'UN News': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UN official news, non-partisan'
    },
    'IEA': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Energy policy, data-driven, non-partisan'
    },
    'WHO': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Global health organization, non-partisan'
    },
    'Chartbook': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'Adam Tooze economics and geopolitics, center-left perspective'
    },
    'Ian Bremmer': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Geopolitical analysis, Eurasia Group, non-partisan'
    },
    'Spiegel International': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'German news, English edition. MBFC: Left-Center, High factual'
    },
    'Le Monde English': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'French newspaper, English edition, left perspective'
    },
    'France24': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'French international news, IFCN fact-checker. MBFC: Least Biased, High factual'
    },
    'El País English': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Spanish newspaper, English edition. MBFC: Left-Center, High factual'
    },
    'Nikkei Asia': {
        'leaning': 0.5,  # Right-Center per MBFC
        'source': 'mbfc',
        'notes': 'Japanese business news, English edition. MBFC: Right-Center, High factual'
    },
    'Caixin Global': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Chinese business news, English edition, generally center'
    },
    'Sixth Tone': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'China-focused news, English by design, generally center'
    },
    'Channel NewsAsia': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'Singapore-based Asian news. MBFC: Least Biased, High factual'
    },
    'Straits Times': {
        'leaning': 0.5,  # Right-Center per MBFC (pro-government)
        'source': 'mbfc',
        'notes': 'Singapore newspaper, state-aligned. MBFC: Right-Center, Mostly Factual'
    },
    'The National': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'UAE newspaper, English by design, generally center'
    },
    'Al Monitor': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Middle East news and analysis. MBFC: Left-Center, High factual'
    },
    'Africa Confidential': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'African political news, generally center'
    },
    'Mail & Guardian': {
        'leaning': -2.0,  # Left per MBFC
        'source': 'mbfc',
        'notes': 'South African newspaper. MBFC: Left, Mixed factual (several failed fact checks)'
    },
    'Daily Maverick': {
        'leaning': 0,  # Least Biased per MBFC
        'source': 'mbfc',
        'notes': 'South African investigative news. MBFC: Least Biased, Mostly Factual'
    },
    'AllAfrica': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'African news aggregation, generally center'
    },
    'Americas Quarterly': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Latin America analysis, generally center'
    },
    'El País América': {
        'leaning': -0.5,  # Lean Left
        'source': 'manual',
        'notes': 'El País, Americas edition, left perspective'
    },
    'Associated Press': {
        'leaning': 0,  # Centre
        'source': 'allsides',
        'notes': 'Wire service, rated Center by AllSides'
    },
    'Reuters': {
        'leaning': 0,  # Centre
        'source': 'allsides',
        'notes': 'Wire service, rated Center by AllSides'
    },
    'BBC Sport': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Sports news, apolitical'
    },
    'ESPN': {
        'leaning': -0.5,  # Left-Center per MBFC (political sports coverage)
        'source': 'mbfc',
        'notes': 'Sports news with some political coverage. MBFC: Left-Center, High factual'
    },
    'The Athletic': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Sports journalism, apolitical'
    },
    'Sky Sports': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Sports news, apolitical'
    },
    'STAT News': {
        'leaning': -0.5,  # Left-Center per MBFC
        'source': 'mbfc',
        'notes': 'Health and medicine journalism. MBFC: Left-Center, High factual'
    },
    'Nature News': {
        'leaning': 0,  # Pro-Science per MBFC
        'source': 'mbfc',
        'notes': 'Scientific journal. MBFC: Pro-Science, Very High factual'
    },
    'Science Magazine': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Scientific journal, apolitical'
    },
    'The Lancet': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Medical journal, apolitical'
    },
    'CoinDesk': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Cryptocurrency news, apolitical'
    },
    'The Block': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Cryptocurrency news, apolitical'
    },
    'Decrypt': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Cryptocurrency news, apolitical'
    },
    'Clean Energy Wire': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Energy policy news, apolitical'
    },
    'E&E News': {
        'leaning': 0,  # Centre
        'source': 'manual',
        'notes': 'Energy and environment news, apolitical'
    },
    'Wired': {
        'leaning': -2.0,  # Left (AllSides Dec 2024 blind survey rated Left)
        'source': 'allsides',
        'notes': 'Tech magazine, progressive perspective. AllSides: Left (-4.07)'
    },
    'The Verge': {
        'leaning': -1.0,  # Lean Left (AllSides independent review)
        'source': 'allsides',
        'notes': 'Tech news, progressive perspective. AllSides: Lean Left (-2.0)'
    },
    
    # ==========================================================================
    # CENTRE-RIGHT SOURCES (+1.0)
    # ==========================================================================
    'UnHerd': {
        'leaning': 0.5,  # Center (slight right lean) per AllSides Oct 2022 blind survey
        'source': 'allsides',
        'notes': 'Features diverse viewpoints, contrarian perspectives. AllSides: Center (0.7)'
    },
    'The Dispatch': {
        'leaning': 1.0,  # Right-Center per MBFC
        'source': 'mbfc',
        'notes': 'Fact-based conservative journalism, Jonah Goldberg. MBFC: Right-Center, High factual'
    },
    'The Free Press': {
        'leaning': 1.0,  # Lean Right (AllSides July 2025 blind survey)
        'source': 'allsides',
        'notes': 'Bari Weiss publication, heterodox/independent journalism. AllSides: Lean Right (1.2)'
    },
    'Reason': {
        'leaning': 1.0,  # Centre-Right (Libertarian)
        'source': 'allsides',
        'notes': 'Libertarian magazine, free minds and free markets'
    },
    'The Critic': {
        'leaning': 1.5,  # Right per MBFC
        'source': 'mbfc',
        'notes': 'British intellectual magazine, skeptical/conservative. MBFC: Right, Mostly Factual'
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
        'leaning': 1.0,  # Right-Center per MBFC
        'source': 'mbfc',
        'notes': 'The Weekly Dish Substack, classical liberal-conservative. MBFC: Right-Center, High factual'
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
        'leaning': 2.0,  # Right per MBFC
        'source': 'mbfc',
        'notes': 'Manhattan Institute, urban policy conservative perspective. MBFC: Right, Mostly Factual'
    },
    'Manhattan Institute': {
        'leaning': 2.0,  # Right per MBFC
        'source': 'mbfc',
        'notes': 'Conservative think tank, pairs with City Journal. MBFC: Right, Mixed factual'
    },
    'The Commentary Magazine': {
        'leaning': 2.0,  # Right per MBFC
        'source': 'mbfc',
        'notes': 'Neoconservative intellectual magazine. MBFC: Right, Mostly Factual'
    },
    'First Things': {
        'leaning': 2.0,  # Right per MBFC
        'source': 'mbfc',
        'notes': 'Religious conservative intellectual journal. MBFC: Right, Mixed factual'
    },
    'Christianity Today': {
        'leaning': 1.0,  # Right-Center per MBFC
        'source': 'mbfc',
        'notes': 'Evangelical perspective, moderate Christian journalism. MBFC: Right-Center, High factual'
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
