"""
Seed data for guided flagship programmes — one per major audience country.

Each variant has GENUINELY DISTINCT statements reflecting that country's specific
institutions, debates, and political context. The global variant covers universal
big questions; country variants anchor each theme in local reality.

Academic standard: every statement is drawn from live, contested debates in
peer-reviewed literature, major institutional reports (IPCC, IEA, ILO, OECD, WHO,
UNHCR, etc.), and leading policy institutes. Optional reading links in the global
edition point to primary institutions, international organisations, and open data
where possible; they are not prerequisites for voting. Statements are designed to be:
  - Clearly normative and falsifiable
  - Genuinely contested by informed, reasonable people
  - Free of rhetorical second clauses or embedded conclusions
  - Accessible to educated non-specialists

Seven statements per discussion ensures the minimum threshold for consensus analysis.

Variant keys and slugs: app/programmes/journey_variants.py
Country editions: optional-reading Markdown and four curated links per theme are merged in
get_curriculum() from app/programmes/journey_reading_enrichment.py (global remains inline here).

Run via:
  flask seed-guided-journey --all-variants
  flask seed-guided-journey --variant global
  flask seed-guided-journey --variant uk

Optional link QA (country reading packs): PYTHONPATH=. python3 scripts/verify_journey_reading_links.py

Editorial standards for statements and optional reading:
  docs/guided-journey-editorial-checklist.md
"""
from __future__ import annotations

from typing import Any, List, Optional

from flask import current_app
from sqlalchemy import or_

from app import db
from app.models import (
    Discussion,
    DiscussionSourceArticle,
    NewsArticle,
    NewsSource,
    Programme,
    Statement,
    StatementVote,
    User,
)
from app.programmes.journey_reading_enrichment import merge_reading_enrichment
from app.programmes.journey_variants import VALID_VARIANTS, VARIANT_METADATA


# Prepended on seed/re-seed so users are not primed to believe they must read
# academic sources before voting. (Existing bodies that already start with this
# marker are left unchanged to avoid doubling on re-run.)
_VOTE_FRAMING_PREAMBLE = (
    "**Your vote records what you think today** — you are **not** expected to read "
    "the optional references below first. They explain how we frame statements. "
    "After you vote, use **Consensus analysis** (when it unlocks) and your journey "
    "**recap** for follow-up reading.\n\n"
)


def _normalize_information_body(raw: Optional[str]) -> Optional[str]:
    t = (raw or "").strip()
    if not t:
        return None
    if t.startswith("**Your vote records what you think today**"):
        return t
    return _VOTE_FRAMING_PREAMBLE + t


# ---------------------------------------------------------------------------
# Country curricula — genuinely distinct content per variant
# ---------------------------------------------------------------------------

def _curriculum_global() -> List[dict[str, Any]]:
    """Universal big-question framing — no country anchor."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions: Climate, energy, and our shared environment",
            "description": "How should humanity respond to the climate crisis while managing energy security and fairness?",
            "information_title": "How to read these statements",
            "information_body": (
                "These statements concern **collective policy choices** — carbon pricing, climate finance, technology — "
                "not personal habits.\n\n"
                "**Optional references:** "
                "[IPCC AR6 synthesis](https://www.ipcc.ch/report/ar6/syr/) · "
                "[IEA — Net Zero by 2050](https://www.iea.org/reports/net-zero-by-2050) · "
                "[UNFCCC — loss & damage](https://unfccc.int/topics/loss-and-damage-work-programme) · "
                "[UN Climate Change — Paris Agreement](https://unfccc.int/process-and-meetings/the-paris-agreement/the-paris-agreement)"
            ),
            "information_links": [
                {"label": "IPCC (UN scientific assessments)", "url": "https://www.ipcc.ch/"},
                {"label": "IEA data & reports", "url": "https://www.iea.org/"},
                {"label": "UNEP — climate science & policy entry", "url": "https://www.unep.org/explore-topics/climate-change"},
                {"label": "Climate Action Tracker (independent policy review)", "url": "https://climateactiontracker.org/"},
            ],
            "article_keywords": ["IPCC report", "carbon pricing", "climate finance developing countries", "net zero policy", "clean energy transition"],
            "seeds": [
                "Developed countries have not met their $100 billion annual climate finance pledge and owe developing nations substantially more in adaptation and loss-and-damage funding.",
                "Nuclear power must be retained and expanded in most countries as part of a credible path to electricity decarbonisation by 2050.",
                "A carbon price set at or near the social cost of carbon is more economically efficient than sector-by-sector emission regulations.",
                "Biodiversity loss is as serious a long-term threat to human welfare as climate change and warrants equivalent policy priority and funding.",
                "Meeting 1.5°C temperature targets requires major demand-side changes in diet, aviation, and consumption — not only clean energy supply.",
                "New licensing of fossil fuel extraction should end immediately in countries that have made legally binding net-zero commitments.",
                "Geoengineering approaches such as solar radiation management should be governed by international treaty before any country deploys them at scale.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions: Artificial intelligence, automation, and governance",
            "description": "Who should control powerful AI systems, and what must be regulated to protect society?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **governance and trade-offs**: safety, innovation, jobs, and democratic oversight.\n\n"
                "**Optional references:** "
                "[EU AI Act (official text via EUR-Lex)](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689) · "
                "[UK AI Safety Institute](https://www.gov.uk/government/organisations/ai-safety-institute) · "
                "[OECD.AI policy observatory](https://oecd.ai/en/) · "
                "[UN AI Advisory Body final report](https://www.un.org/en/ai-advisory-body) · "
                "[Acemoglu — simple macro of AI (NBER working paper)](https://www.nber.org/papers/w32167)"
            ),
            "information_links": [
                {"label": "Council of Europe — AI & human rights", "url": "https://www.coe.int/en/web/artificial-intelligence"},
                {"label": "IEEE Standards Association (AI ethics)", "url": "https://standards.ieee.org/industry-connections/activities/ieee-global-initiative/"},
                {"label": "Partnership on AI", "url": "https://partnershiponai.org/"},
                {"label": "Global Partnership on AI (GPAI)", "url": "https://gpai.ai/"},
            ],
            "article_keywords": ["AI regulation frontier safety", "AI liability law", "AI automation jobs displacement", "AI governance treaty", "data protection AI training"],
            "seeds": [
                "Frontier AI systems capable of causing large-scale harm should be required to pass independent safety evaluations before public deployment.",
                "Open-source release of the most powerful AI model weights creates security risks that outweigh the benefits of public access.",
                "AI developers should bear strict legal liability for foreseeable harms caused by their deployed systems, as manufacturers do for physical products.",
                "AI-driven automation will displace significantly more jobs than it creates this decade, requiring fundamental redesign of social insurance systems.",
                "Global AI safety governance requires a binding multilateral treaty process, not voluntary national commitments.",
                "Training AI systems on personal data without explicit opt-in consent should be prohibited under data protection law.",
                "Generative AI systems capable of producing realistic synthetic media should be required to embed detectable watermarks in their outputs.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions: Prosperity, inequality, and the future of work",
            "description": "Taxation, markets, and who bears the costs of economic change.",
            "information_title": "How to read these statements",
            "information_body": (
                "These questions concern **systemic design**, not individual spending.\n\n"
                "**Optional references:** "
                "[World Bank — poverty & inequality data](https://www.worldbank.org/en/topic/poverty) · "
                "[OECD — income distribution database](https://www.oecd.org/social/income-distribution-database.htm) · "
                "[IMF Fiscal Monitor](https://www.imf.org/en/Publications/FM) · "
                "[Piketty — *Capital* (Harvard University Press)](https://www.hup.harvard.edu/catalog.php?isbn=9780674430006) · "
                "[Hsieh & Moretti — housing constraints (NBER)](https://www.nber.org/papers/w21154)"
            ),
            "information_links": [
                {"label": "ILO — labour standards & wages", "url": "https://www.ilo.org/global/lang--en/index.htm"},
                {"label": "UNCTAD — trade & development", "url": "https://unctad.org/"},
                {"label": "WTO — trade rules overview", "url": "https://www.wto.org/english/thewto_e/whatis_e/whatis_e.htm"},
                {"label": "World Inequality Database", "url": "https://wid.world/"},
            ],
            "article_keywords": ["wealth tax policy", "universal basic income evidence", "housing zoning reform", "trade labour standards", "collective bargaining inequality"],
            "seeds": [
                "A direct annual tax on net wealth above a high threshold is necessary to address asset concentration that income taxation alone cannot reach.",
                "A universal basic income set at the poverty line would reduce poverty more effectively than current means-tested benefit systems.",
                "Restrictive zoning and planning regulations are the primary cause of housing unaffordability in most major cities.",
                "International trade agreements must include binding, independently enforceable labour and environmental standards.",
                "High collective bargaining coverage reduces wage inequality more effectively than minimum wage legislation alone.",
                "Central banks should formally weight full employment as an equal mandate to price stability, not treat inflation control as the sole objective.",
                "The 15% global corporate minimum tax agreed through the OECD is necessary but should be raised further to meaningfully reduce profit shifting to tax havens.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions: Health systems, prevention, and access",
            "description": "How societies should fund, organise, and prioritise healthcare.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **public policy** — access, funding models, prevention — not personal medical choices.\n\n"
                "**Optional references:** "
                "[WHO — health systems governance](https://www.who.int/teams/health-systems-governance-and-financing) · "
                "[The Lancet — universal health coverage collection](https://www.thelancet.com/series/universal-health-coverage) · "
                "[Commonwealth Fund — international health policy comparisons](https://www.commonwealthfund.org/international-health-policy-center) · "
                "[World Bank — health nutrition & population](https://www.worldbank.org/en/topic/health) · "
                "[UN — mental health & well-being strategy](https://www.un.org/en/global-issues/mental-health)"
            ),
            "information_links": [
                {"label": "OECD — health at a glance", "url": "https://www.oecd.org/health/health-at-a-glance.htm"},
                {"label": "PAHO — Americas health data", "url": "https://www.paho.org/en"},
                {"label": "Africa CDC", "url": "https://africacdc.org/"},
                {"label": "Wellbeing economy alliance (beyond-GDP framing)", "url": "https://weall.org/"},
            ],
            "article_keywords": ["universal healthcare outcomes comparison", "drug patent compulsory licensing", "ultra-processed food regulation", "mental health funding gap", "pandemic preparedness fund"],
            "seeds": [
                "Universal healthcare funded through general taxation achieves better population health outcomes than insurance-based systems at comparable total cost.",
                "Compulsory licensing of essential medicine patents is justified when patent protection prevents access in low- and middle-income countries.",
                "The public health burden of ultra-processed food consumption is severe enough to justify mandatory advertising restrictions and reformulation requirements.",
                "Mental health conditions receive a fraction of the clinical and research investment justified by their economic and social burden.",
                "A permanent international pandemic preparedness fund financed by treaty obligation — not discretionary aid — is necessary after the failures of COVID response.",
                "Governments should prioritise healthy life expectancy and wellbeing indicators over GDP growth as the primary measures of national progress.",
                "Antimicrobial resistance is a public health emergency requiring binding international rules on antibiotic use in agriculture and medicine.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions: War, intervention, and international security",
            "description": "When force is justified, how alliances should work, and how to govern new security risks.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **normative** questions about legitimacy and risk; reasonable people disagree sharply.\n\n"
                "**Optional references:** "
                "[UN — Responsibility to Protect (R2P)](https://www.un.org/en/genocide-prevention/responsibility-protect/) · "
                "[SIPRI — military expenditure database](https://www.sipri.org/databases/milex) · "
                "[ICRC — autonomous weapons & IHL](https://www.icrc.org/en/law-and-policy/autonomous-weapons) · "
                "[UN Peacekeeping overview](https://peacekeeping.un.org/en) · "
                "[Reaching Critical Will — civil society monitoring of disarmament](https://reachingcriticalwill.org/)"
            ),
            "information_links": [
                {"label": "UN Digital Library — Charter & Security Council", "url": "https://digitallibrary.un.org/"},
                {"label": "International Crisis Group", "url": "https://www.crisisgroup.org/"},
                {"label": "ACLED — conflict data", "url": "https://acleddata.com/"},
                {"label": "UNODA — Office for Disarmament Affairs", "url": "https://www.un.org/disarmament/"},
            ],
            "article_keywords": ["nuclear deterrence policy", "humanitarian intervention R2P", "NATO defence spending 2 percent", "sanctions effectiveness authoritarian", "autonomous weapons ban treaty"],
            "seeds": [
                "Nuclear deterrence remains the primary guarantor of great-power peace, making significant nuclear disarmament strategically premature in current conditions.",
                "Humanitarian military intervention without UN Security Council authorisation is justified when genocide or mass atrocities are actively ongoing and the Council is deadlocked.",
                "Liberal democracies should collectively increase defence spending given the demonstrated willingness of authoritarian states to use military force.",
                "Multilateral economic sanctions are rarely sufficient on their own to change the strategic behaviour of authoritarian governments.",
                "Climate change is a threat multiplier for armed conflict and insecurity and should be formally integrated into national security strategies.",
                "Autonomous weapons systems that select and engage targets without meaningful human control should be banned by international treaty.",
                "Private military companies operating outside international humanitarian law represent a growing and largely unaddressed threat to civilian protection.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions: Democracy, rights, and political institutions",
            "description": "Representation, limits on power, electoral integrity, and civic trust.",
            "information_title": "How to read these statements",
            "information_body": (
                "Interpret statements as **institutional design choices**, not party loyalty.\n\n"
                "**Optional references:** "
                "[Arend Lijphart — *Patterns of Democracy* (Yale UP)](https://yalebooks.yale.edu/book/9780300172027/patterns-of-democracy/) · "
                "[Levitsky & Ziblatt — *How Democracies Die* (Penguin Random House)](https://www.penguinrandomhouse.com/books/239538/how-democracies-die-by-steven-levitsky-and-daniel-ziblatt/) · "
                "[Electoral Integrity Project](https://www.electoralintegrityproject.com/) · "
                "[V-Dem Institute — democracy reports & data](https://www.v-dem.net/) · "
                "[Gilens & Page (2014) — testing theories of US politics (DOI)](https://doi.org/10.1017/S1537592714001595)"
            ),
            "information_links": [
                {"label": "ACE — Electoral Knowledge Network (comparative systems)", "url": "https://aceproject.org/"},
                {"label": "IDEA — International Institute for Democracy and Electoral Assistance", "url": "https://www.idea.int/"},
                {"label": "OECD — building trust / open government", "url": "https://www.oecd.org/gov/trust-in-government/"},
                {"label": "OHCHR — civil & political rights overview", "url": "https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-on-civil-and-political-rights"},
            ],
            "article_keywords": ["proportional representation evidence", "judicial independence democracy", "election misinformation platform liability", "term limits democratic backsliding", "compulsory voting turnout"],
            "seeds": [
                "Proportional representation produces more representative legislative bodies than first-past-the-post electoral systems.",
                "Independent judicial review is essential for protecting minority rights even when it overrides the preferences of electoral majorities.",
                "Social media platforms that algorithmically amplify demonstrably false election information should bear legal liability for resulting democratic harms.",
                "Term limits for heads of government meaningfully reduce the risk of democratic backsliding and authoritarian consolidation.",
                "Compulsory voting would substantially increase political equality by eliminating the systematic under-representation of lower-income and younger voters.",
                "The scale of corporate and industry lobbying distorts democratic representation far beyond what ordinary citizens can counterbalance.",
                "Ranked-choice preferential voting would produce more representative outcomes than first-past-the-post without requiring full proportional representation.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions: Migration, identity, and social trust",
            "description": "Pluralism, borders, and what we owe each other in diverse societies.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy and ethics**; avoid interpreting statements as judgements on individuals.\n\n"
                "**Optional references:** "
                "[UNHCR — Global Trends reports](https://www.unhcr.org/refugee-statistics) · "
                "[IOM — World Migration Report](https://www.iom.int/wmr) · "
                "[UN DESA — international migration](https://www.un.org/development/desa/pd/content/international-migration) · "
                "[Clemens (2011) — economics of emigration (CGD working paper)](https://www.cgdev.org/publication/economics-and-emigration-trillion-dollar-bill) · "
                "[OECD — migration outlook](https://www.oecd.org/migration/mig/)"
            ),
            "information_links": [
                {"label": "1951 Refugee Convention text (UNHCR)", "url": "https://www.unhcr.org/about-unhcr/who-we-are/1951-refugee-convention"},
                {"label": "UN — hate speech vs free speech (UNESCO)", "url": "https://www.unesco.org/en/hate-speech"},
                {"label": "MPI — Migration Policy Institute", "url": "https://www.migrationpolicy.org/"},
                {"label": "ICMPD — migration dialogue (Europe & beyond)", "url": "https://www.icmpd.org/"},
            ],
            "article_keywords": ["high-skilled migration economic evidence", "refugee convention legal obligations", "multiculturalism cohesion research", "hate speech law minority protection", "inequality social trust"],
            "seeds": [
                "High-income countries should substantially expand legal migration pathways — the fiscal and economic evidence for doing so is strong.",
                "States that signed the 1951 Refugee Convention have binding legal obligations to asylum seekers that domestic political pressure cannot override.",
                "Cultural and ethnic diversity in high-immigration societies produces long-term economic benefits that justify active and well-resourced immigration policy.",
                "Hate speech laws targeting incitement to violence are compatible with free expression and necessary to protect vulnerable communities.",
                "Reducing income inequality through redistribution is more effective at building social trust and cohesion than restricting immigration.",
                "Governments have a duty to actively enforce prohibitions on racial and ethnic discrimination in employment and housing, not merely legislate them.",
                "Statelessness — where individuals hold no nationality — represents a critical human rights gap that requires a strengthened international legal remedy.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions: Education, skills, and opportunity",
            "description": "What every generation should learn, how education systems can reduce inequality, and who pays.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, curriculum, and funding models**.\n\n"
                "**Optional references:** "
                "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/) · "
                "[UNESCO — Global Education Monitoring Report](https://www.unesco.org/gem-report/en) · "
                "[Chetty, Friedman & Rockoff — teacher value-added (*American Economic Review*, DOI)](https://doi.org/10.1093/qje/qjt016) · "
                "[Hoxby & Avery — the missing ‘one-offs’ (NBER)](https://www.nber.org/papers/w18586) · "
                "[Hanushek & Woessmann — knowledge capital & growth (NBER)](https://www.nber.org/papers/w22376)"
            ),
            "information_links": [
                {"label": "World Bank — education global practice", "url": "https://www.worldbank.org/en/topic/education"},
                {"label": "UIS — UNESCO Institute for Statistics (education data)", "url": "https://uis.unesco.org/"},
                {"label": "Education International (global union federation)", "url": "https://www.ei-ie.org/en"},
                {"label": "UNESCO — right to education", "url": "https://www.unesco.org/en/right-education"},
            ],
            "article_keywords": ["university tuition fees access inequality", "standardised testing learning outcomes", "vocational education funding parity", "digital literacy curriculum", "private schools inequality public subsidy"],
            "seeds": [
                "University tuition fees reduce access for students from lower-income households and should be replaced with public funding through progressive taxation.",
                "High-stakes standardised testing narrows curricula and disadvantages students from lower-income backgrounds without improving average learning outcomes.",
                "Vocational and technical education routes are systematically underfunded relative to academic routes in most high-income countries.",
                "Digital and critical information literacy should be mandatory core curriculum requirements from primary school alongside reading and numeracy.",
                "Private schools that select by academic ability or religious faith perpetuate socioeconomic advantage and should not receive public subsidy.",
                "Teacher quality is the single most important within-school determinant of pupil outcomes, and teacher pay should reflect this.",
                "Access to reliable internet and digital devices should be recognised as a prerequisite for meaningful participation in education and civic life.",
            ],
        },
    ]


def _curriculum_uk() -> List[dict[str, Any]]:
    """UK-specific big questions anchored in British institutions, evidence, and current debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for the UK: Net zero, energy security, and environmental policy",
            "description": "Can Britain decarbonise at the pace required by the Climate Change Act while managing energy costs and rural interests?",
            "information_title": "How to read these statements",
            "information_body": (
                "These questions concern **UK policy choices** — North Sea licensing, heat pumps, planning reform, and agricultural policy. "
                "Further reading (optional) — Climate Change Committee Sixth Carbon Budget (2020), NESO Clean Power 2030 Action Plan, "
                "UK North Sea Transition Deal, UK Net Zero Research Programme."
            ),
            "article_keywords": ["UK North Sea oil gas licence", "UK net zero Climate Change Act", "heat pump grant UK", "UK onshore wind planning", "UK Sixth Carbon Budget"],
            "seeds": [
                "Issuing new North Sea oil and gas licences is incompatible with the UK's legally binding 2050 net-zero commitment under the Climate Change Act.",
                "Heat pump grants should be increased substantially so that installation costs are no longer a barrier for median-income households.",
                "Planning rules in England should be reformed to allow onshore wind development — currently one of the cheapest new electricity sources available.",
                "The UK's Sixth Carbon Budget requires emissions reductions significantly faster than existing policy will deliver.",
                "UK farmers should receive direct payments for peatland restoration and habitat recovery, even where this reduces agricultural output.",
                "Britain's net-zero credibility is undermined by expanding Heathrow airport capacity while rail investment is delayed.",
                "North Sea windfall tax revenues should be ring-fenced for clean energy infrastructure investment and a just transition fund for affected workers.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the UK: AI safety, regulation, and digital governance",
            "description": "Can Britain lead on responsible AI without sacrificing its economic ambitions in the sector?",
            "information_title": "How to read these statements",
            "information_body": (
                "Consider the UK's position as host of the AI Safety Summit and its **post-Brexit regulatory divergence** from the EU AI Act. "
                "Further reading (optional) — UK AI Safety Institute (AISI) evaluations, Online Safety Act 2023, "
                "ICO enforcement records, Centre for Long-Term Resilience AI reports."
            ),
            "article_keywords": ["UK AI Safety Institute", "UK AI regulation binding rules", "Online Safety Act 2023", "ICO GDPR enforcement UK", "UK data protection post-Brexit"],
            "seeds": [
                "The UK should adopt binding AI safety rules rather than relying on voluntary codes and industry self-regulation.",
                "The UK's light-touch post-Brexit approach to AI regulation risks enabling harms that the EU AI Act is designed to prevent.",
                "The Online Safety Act's provisions on legal-but-harmful content set a problematic precedent for government oversight of online speech.",
                "Requiring age verification for social media platforms is justified even if it creates privacy trade-offs.",
                "UK data protection rules post-Brexit should remain fully equivalent to the EU's GDPR to protect UK-EU data flows.",
                "Government use of automated decision-making that affects individuals' rights should require mandatory transparency and right of appeal.",
                "The UK AI Safety Institute should be given independent statutory authority rather than operating purely under government direction.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the UK: Growth, inequality, and the cost of living",
            "description": "UK productivity stagnation, regional inequality, and the housing crisis.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **structural economic questions** — the productivity puzzle, housing supply, and fiscal choices. "
                "Further reading (optional) — Resolution Foundation, Institute for Fiscal Studies, LSE Centre for Economic Performance, "
                "OBR Fiscal Risks and Sustainability report, ONS Regional Economic Activity data."
            ),
            "article_keywords": ["UK productivity gap OECD", "National Living Wage UK evidence", "UK housing crisis planning", "UK regional inequality levelling up", "UK public investment infrastructure"],
            "seeds": [
                "Public sector austerity from 2010 to 2019 caused lasting damage to UK public services and long-run economic capacity.",
                "The National Living Wage should rise to £15 an hour within this parliament, in line with living cost evidence.",
                "The UK's chronic underinvestment in infrastructure and R&D relative to OECD peers is a primary cause of its productivity gap.",
                "London's dominance of the UK economy requires active regional industrial policy — market forces alone will not rebalance it.",
                "The UK housing crisis requires both more permissive planning reform and a significant expansion of publicly funded housebuilding.",
                "Inheritance tax reform should prioritise closing agricultural and business property relief loopholes before any reduction in the headline rate.",
                "The UK needs a sovereign wealth fund to invest North Sea windfall revenues in long-term productive assets for future generations.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the UK: The NHS, social care, and public health",
            "description": "Waiting lists, funding models, workforce retention, and whether the NHS can be restored to sustainability.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **NHS structure, funding, and access** — not personal health choices. "
                "Further reading (optional) — NHS England waiting list data (7m+ in 2024), Health Foundation 'NHS at 75' report, "
                "Nuffield Trust social care analyses, King's Fund workforce reports."
            ),
            "article_keywords": ["NHS waiting list funding 2024", "NHS social care elderly funding", "NHS workforce pay retention", "NHS privatisation independent sector", "UK obesity prevention policy"],
            "seeds": [
                "The NHS must remain free at the point of use for all, funded through general taxation — user charges would deter those who need care most.",
                "NHS waiting lists, which exceeded seven million in 2024, cannot be cleared without a significant and sustained real-terms funding increase.",
                "Social care for older and disabled people should be fully state-funded, ending the system under which individuals must deplete assets to pay for care.",
                "NHS staff pay has declined significantly in real terms since 2010 and requires urgent restoration to recruit and retain the workforce needed.",
                "Expanded use of independent sector providers, paid at NHS tariff rates, can meaningfully reduce waiting times without compromising NHS principles.",
                "Prevention — addressing obesity, smoking, and alcohol consumption — would reduce future NHS demand more effectively than efficiency measures alone.",
                "NHS digital records should be expanded so patients have full access to their own data and can share it seamlessly across different providers.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the UK: Defence, NATO, and Britain's role in the world",
            "description": "Trident, Ukraine, defence spending, and Britain's post-Brexit geopolitical position.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **force, alliances, and Britain's international commitments**. "
                "Further reading (optional) — IISS Military Balance, Budapest Memorandum (1994), "
                "RUSI defence reviews, House of Commons Defence Committee reports."
            ),
            "article_keywords": ["UK Trident renewal cost", "UK NATO 2 percent defence spending", "UK Ukraine Budapest Memorandum", "AUKUS strategic assessment", "UK overseas development aid 0.7"],
            "seeds": [
                "The UK should renew and maintain its Trident nuclear deterrent as a necessary contribution to NATO's nuclear posture.",
                "Britain should commit to spending 2.5% of GDP on defence as a sustained floor, not merely an aspirational target.",
                "The UK has a particular obligation to sustain military support for Ukraine given its role as a Budapest Memorandum signatory.",
                "Post-Brexit Britain has diminished its diplomatic influence in Europe in ways that damage UK national security interests.",
                "AUKUS strengthens UK strategic interests in the Indo-Pacific and represents a sound long-term security investment.",
                "UK overseas development assistance should be restored to 0.7% of GNI as required by the International Development Act.",
                "Britain's post-Brexit foreign policy lacks sufficient strategic coherence and needs a comprehensive independent review.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the UK: Parliament, voting, and constitutional reform",
            "description": "Lords reform, electoral systems, judicial independence, and the erosion of democratic norms.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** — not about any party's current position. "
                "Further reading (optional) — Electoral Reform Society, Constitution Unit UCL, "
                "Supreme Court judgment in Miller (2019), Venice Commission assessments of UK constitutional changes."
            ),
            "article_keywords": ["UK proportional representation evidence", "House of Lords reform elected", "UK Supreme Court independence", "voter ID disenfranchisement UK", "UK political donations transparency"],
            "seeds": [
                "First-past-the-post should be replaced with proportional representation for UK general elections.",
                "The House of Lords should be replaced by an elected second chamber with a clear democratic mandate.",
                "The Supreme Court's power to hold government actions unlawful under constitutional principles should be protected, not curtailed.",
                "Voter ID requirements introduced in 2023 disenfranchise legitimately entitled voters more than they prevent fraud.",
                "MP recall should be triggerable directly by constituents through a petition threshold, not only through a parliamentary committee.",
                "Political donation transparency rules should be substantially tightened to limit the influence of large donors on government policy.",
                "The minimum voting age should be reduced to 16 for all UK elections, as it already is for Scottish Parliament and Welsh Senedd elections.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the UK: Immigration, identity, and community",
            "description": "What the UK owes newcomers, and what it takes to build and maintain a cohesive society.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design**, not on the character or worth of individuals. "
                "Further reading (optional) — Migration Advisory Committee reports, UNHCR UK asylum statistics, "
                "IPPR 'Legitimate Concerns' report, Home Office Migration Transparency Data."
            ),
            "article_keywords": ["UK net migration policy MAC", "UK asylum seeker right to work", "UK offshore processing Rwanda ruling", "UK integration policy evidence", "UK community cohesion investment"],
            "seeds": [
                "Net migration targets expressed as absolute numbers are not a credible policy instrument and should be replaced with skills-based assessment frameworks.",
                "Asylum seekers should have the right to work while their claims are assessed — the prohibition harms integration prospects and public finances.",
                "Offshore processing of asylum claims is incompatible with the UK's obligations under the 1951 Refugee Convention and ECHR.",
                "Britain's ethnic and cultural diversity is a long-term economic and social asset that requires sustained public investment in cohesion infrastructure.",
                "Communities experiencing rapid demographic change require additional targeted public investment to maintain social infrastructure.",
                "UK citizenship naturalisation requirements should prioritise civic knowledge and democratic values over historical trivia.",
                "The hostile environment policy has caused documented harm to legal residents and British citizens and should be formally abolished.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the UK: Schools, universities, and preparing for work",
            "description": "Tuition fees, grammar schools, apprenticeships, and whether the system delivers for everyone.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, funding models, and what is taught** — not individual school performance. "
                "Further reading (optional) — Institute for Fiscal Studies HE funding analysis, Education Policy Institute, "
                "Sutton Trust social mobility research, OFSTED framework reviews."
            ),
            "article_keywords": ["UK university tuition fees graduate debt", "grammar schools inequality evidence", "UK apprenticeships funding parity", "OFSTED inspection reform", "UK teacher pay graduate professions"],
            "seeds": [
                "University tuition fees should be substantially reduced and the graduate contribution system reformed to reduce the long-term debt burden.",
                "Grammar schools should not be expanded — the evidence shows they increase inequality without improving overall educational attainment.",
                "Apprenticeships should receive equivalent per-pupil public funding to university places to give them genuine parity of esteem.",
                "OFSTED single-word judgements create counterproductive high-stakes inspection culture and should be replaced with school improvement support.",
                "Teacher pay in the UK has fallen significantly behind comparable graduate professions and must be substantially increased.",
                "State-funded schools that select pupils on religious grounds create social segregation and should transition to open admissions.",
                "The pupil premium should be substantially increased and its use audited more rigorously to close persistent attainment gaps.",
            ],
        },
    ]


def _curriculum_us() -> List[dict[str, Any]]:
    """US-specific big questions anchored in American political and institutional debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for the US: Climate policy, energy, and the American economy",
            "description": "Can the US lead on climate while protecting jobs and energy security?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **federal policy choices** — the Inflation Reduction Act, EPA authority, and fossil fuel infrastructure. "
                "Further reading (optional) — Rhodium Group US climate progress reports, Resources for the Future, "
                "Brookings energy policy analysis, NOAA climate data."
            ),
            "article_keywords": ["Inflation Reduction Act clean energy", "EPA greenhouse gas authority", "US Paris Agreement climate", "US LNG export climate impact", "US agricultural emissions policy"],
            "seeds": [
                "The Inflation Reduction Act's clean energy investments should be protected — rolling them back would set US decarbonisation back by a decade.",
                "The EPA's authority to regulate greenhouse gas emissions must be maintained against legislative attempts to restrict it.",
                "The United States should meet its nationally determined contribution under the Paris Agreement and fund it fully.",
                "New federal permits for LNG export terminals should be paused given their long-term lock-in of fossil fuel infrastructure.",
                "Federal agricultural subsidies should be substantially reoriented toward low-emissions and regenerative farming practices.",
                "States should not be permitted to block federally authorised clean energy infrastructure on their territory for political rather than technical reasons.",
                "The federal government should create a carbon border adjustment mechanism to prevent carbon leakage from countries without equivalent climate policies.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the US: Big Tech, AI, and the digital economy",
            "description": "Section 230, antitrust, and whether Washington can effectively govern Silicon Valley.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **federal regulation and trade-offs** between innovation, safety, and democratic accountability. "
                "Further reading (optional) — FTC antitrust enforcement actions, Senate AI Insight Forum reports, "
                "Georgetown CSET AI policy analyses, AI Safety Institute (NIST) frameworks."
            ),
            "article_keywords": ["Section 230 reform social media", "Big Tech antitrust FTC", "federal AI safety agency", "AI worker displacement fund", "data sovereignty foreign access"],
            "seeds": [
                "Section 230 liability protection for social media platforms should be narrowed where platforms knowingly amplify demonstrably harmful content.",
                "Antitrust enforcement against Amazon, Google, and Meta should be substantially strengthened — current market concentration harms competition.",
                "A federal AI safety agency with power to evaluate and conditionally halt high-risk deployments should be established.",
                "Workers displaced by AI automation should be supported by a publicly funded retraining and transition programme.",
                "Americans' personal data should not be sold to or accessed by foreign governments without explicit consent or a court order.",
                "The United States should lead in setting global AI governance standards rather than deferring to the EU or avoiding binding international frameworks.",
                "Social media platforms should be legally required to disclose their algorithmic recommendation systems to independent researchers.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the US: The economy, taxes, and who gets ahead",
            "description": "Minimum wage, student debt, the tax code, and whether the American Dream is accessible.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **systemic policy questions** — not about individual hard work or personal responsibility. "
                "Further reading (optional) — Congressional Budget Office, Economic Policy Institute, "
                "Chetty et al. 'The Fading American Dream' (2017), Tax Policy Center, IZA labour research."
            ),
            "article_keywords": ["federal minimum wage $15 evidence", "student loan forgiveness Biden", "carried interest loophole", "US wealth tax Saez Zucman", "right-to-work laws union membership"],
            "seeds": [
                "The federal minimum wage should be raised to $15 an hour and automatically indexed to inflation thereafter.",
                "Federal student loan forgiveness should be expanded substantially, prioritising borrowers from programmes with poor labour market outcomes.",
                "The carried interest tax preference for private equity and hedge fund managers should be eliminated.",
                "A wealth tax on fortunes above $50 million would raise significant revenue without materially harming productive investment.",
                "Right-to-work laws weaken collective bargaining and should be repealed at the federal level.",
                "US trade agreements must include binding, independently enforceable labour and environmental standards.",
                "The United States needs a federal paid family and medical leave programme — it is the only OECD country without one.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the US: Healthcare, insurance, and who gets covered",
            "description": "Medicare, the ACA, drug pricing, and why the US spends more and gets less than peers.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **coverage, cost, and system design** — not individual health choices. "
                "Further reading (optional) — Commonwealth Fund US health system analyses, CBO healthcare scoring, "
                "RAND Medicare for All study, Peterson-KFF Health System Tracker."
            ),
            "article_keywords": ["Medicare for All single payer study", "drug price negotiation Medicare", "Medicaid expansion states", "mental health parity enforcement", "employer health insurance mobility"],
            "seeds": [
                "The United States should move toward a single-payer Medicare for All system — it is the only model that would achieve universal coverage efficiently.",
                "The federal government should have comprehensive authority to negotiate drug prices directly with pharmaceutical companies.",
                "Medicaid expansion should be mandatory for all states — the current opt-out system creates unjustifiable coverage gaps.",
                "Mental health parity laws should be strictly enforced so that insurers cannot systematically limit mental health claims.",
                "Employer-based health insurance reduces worker mobility and economic efficiency and should be replaced with portable coverage.",
                "Reproductive healthcare services should be covered under all federally funded health insurance plans.",
                "The United States should pass a national paid sick leave requirement — its absence worsens public health and worker wellbeing.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the US: Military power, alliances, and America's global role",
            "description": "NATO burden-sharing, Pentagon spending, and whether US power stabilises or destabilises the world.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are questions about the **costs, legitimacy, and effectiveness of American military power**. "
                "Further reading (optional) — SIPRI US military expenditure data, Congressional Research Service, "
                "CSIS strategic assessments, War Powers Resolution debate."
            ),
            "article_keywords": ["US NATO commitments burden sharing", "Ukraine US military aid", "Congress war powers authorisation", "Pentagon budget audit", "US arms sales human rights"],
            "seeds": [
                "The United States should maintain its military commitments to NATO allies rather than conditioning them on burden-sharing targets.",
                "Continued US military support for Ukraine is a strategic investment in deterring further Russian aggression in Europe.",
                "Congress should pass legislation reasserting war powers so that no president can commit US forces to significant combat without authorisation.",
                "The US defence budget should be subject to rigorous independent efficiency audit before further increases are approved.",
                "US arms sales to governments that commit systematic human rights violations undermine American values and long-term security interests.",
                "Sustained engagement with China through international institutions is more effective than economic and technological decoupling as a strategy for managing rivalry.",
                "The United States should rejoin and strengthen its participation in multilateral institutions rather than continuing to withdraw from them.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the US: Democracy, voting rights, and institutional reform",
            "description": "The Electoral College, the filibuster, the Supreme Court, and whether US democracy needs structural reform.",
            "information_title": "How to read these statements",
            "information_body": (
                "Interpret these as **structural design questions** — not partisan claims. "
                "Further reading (optional) — Electoral Integrity Project, Brennan Center for Justice, "
                "Levitsky & Ziblatt 'How Democracies Die' (2018), Citizens United v. FEC (2010), "
                "Campaign Legal Center analyses."
            ),
            "article_keywords": ["Electoral College national popular vote", "Senate filibuster reform", "Supreme Court term limits justices", "gerrymandering independent redistricting", "Citizens United campaign finance"],
            "seeds": [
                "The Electoral College should be replaced by a national popular vote to ensure that every vote counts equally in presidential elections.",
                "The Senate filibuster should be abolished or substantially reformed so that majority rule can function in ordinary legislation.",
                "Supreme Court justices should serve staggered 18-year terms with regular and predictable appointments by each president.",
                "Independent redistricting commissions should be required in every state to eliminate partisan gerrymandering.",
                "Federal automatic voter registration should be introduced to maximise electoral participation without compromising integrity.",
                "The Citizens United decision should be overturned — unlimited anonymous political spending distorts democratic representation.",
                "All states should restore full voting rights to people who have completed their criminal sentences.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the US: Immigration, identity, and the American promise",
            "description": "Border policy, DACA, racial justice, and what it means to be American today.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design**, not the character or worth of individuals. "
                "Further reading (optional) — Migration Policy Institute, American Immigration Council, "
                "SFFA v. Harvard & UNC Supreme Court ruling (2023), Everytown gun violence research, "
                "National Academy of Sciences 'The Integration of Immigrants into American Society' (2015)."
            ),
            "article_keywords": ["DACA legal status path citizenship", "undocumented immigrants residency pathway", "SFFA race-conscious admissions ruling 2023", "universal background check gun violence", "US refugee admissions cap"],
            "seeds": [
                "DACA recipients who have built their lives in the United States deserve a clear statutory path to permanent legal status and citizenship.",
                "Undocumented immigrants who have resided in the United States for an extended period with no serious criminal record should be eligible for legal residency.",
                "The Supreme Court's 2023 prohibition on race-conscious college admissions will increase, not decrease, racial inequality in higher education access.",
                "Federal universal background check legislation for all gun purchases should be passed — the evidence that it reduces gun violence is strong.",
                "The United States accepts far too few refugees relative to its capacity and international obligations.",
                "Addressing racial disparities in policing requires structural reform — incremental measures have proved insufficient.",
                "The United States should significantly increase its refugee resettlement programme — the evidence on refugee economic integration is strongly positive.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the US: Schools, colleges, and the skills gap",
            "description": "School funding equity, student debt, vocational training, and what K-12 students should learn.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, funding equity, and curriculum** — not individual school performance. "
                "Further reading (optional) — Education Trust school funding equity research, Chetty et al. on colleges and mobility, "
                "National Center for Education Statistics, Fordham Institute on curriculum standards."
            ),
            "article_keywords": ["school funding property tax inequality", "school vouchers public education", "SAT ACT admissions income bias", "vocational trades funding college prep", "teacher pay national US districts"],
            "seeds": [
                "Per-pupil school funding should not vary by local property tax revenue — this mechanism systematically disadvantages students from lower-income communities.",
                "Public voucher programmes for private schools divert funding from the public school system and expand, rather than reduce, educational inequality.",
                "Standardised college admissions tests systematically disadvantage students from lower-income backgrounds and should be substantially de-emphasised.",
                "Vocational and trades programmes should be funded at the same per-student level as college-preparatory curricula.",
                "Teacher pay should be set at a nationally competitive professional rate, not left to wide variation across local districts.",
                "K-12 schools should teach comprehensive and accurate history of slavery and racial violence — this is a requirement of civic literacy.",
                "Universal free school meals for all K-12 students would reduce food insecurity and improve learning outcomes.",
            ],
        },
    ]


def _curriculum_nl() -> List[dict[str, Any]]:
    """Netherlands-specific big questions grounded in Dutch political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for the Netherlands: Nitrogen, energy, and the climate transition",
            "description": "How does the Netherlands balance climate targets with the interests of agriculture, industry, and energy security?",
            "information_title": "How to read these statements",
            "information_body": (
                "These questions concern **Dutch policy choices** — nitrogen rules, Groningen gas, and coastal adaptation. "
                "Further reading (optional) — Raad van State nitrogen ruling (2019), KNMI climate scenarios, "
                "PBL Netherlands Environmental Assessment Agency, CBS Statistics Netherlands energy data."
            ),
            "article_keywords": ["Netherlands nitrogen stikstof livestock", "Groningen gas earthquake seismic", "Dutch coal power phase-out", "Netherlands pension fund fossil fuel divestment", "Dutch nuclear energy expansion"],
            "seeds": [
                "The Netherlands must reduce livestock numbers significantly to meet its legally binding nitrogen emission targets under the Council of State ruling.",
                "Groningen gas extraction should have been phased out faster — the balance between energy supply and seismic safety was wrongly struck.",
                "Dutch water management expertise gives the Netherlands a special obligation to fund global sea-level adaptation in vulnerable nations.",
                "The Netherlands should close its remaining coal power stations before 2030 even if this temporarily raises electricity prices.",
                "Dutch pension funds should be required to fully divest from fossil fuel companies in line with fiduciary duty to beneficiaries.",
                "Nuclear energy should be part of the Netherlands' long-term electricity mix as part of the clean energy transition.",
                "Dutch households should face binding minimum energy efficiency standards before 2030, with substantial subsidies to help lower-income households comply.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the Netherlands: ASML, AI governance, and digital sovereignty",
            "description": "Can the Netherlands shape global tech policy from its unique position as home to ASML?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Dutch tech policy**, ASML export controls, EU AI Act implementation, and the Dutch DPA. "
                "Further reading (optional) — Dutch DPA (Autoriteit Persoonsgegevens) enforcement reports, "
                "ASML annual reports, Rathenau Instituut digital society research, EU AI Act (2024)."
            ),
            "article_keywords": ["ASML export controls China chips", "EU AI Act Dutch business compliance", "Dutch DPA GDPR enforcement Big Tech", "Netherlands digital sovereignty cloud", "ASML deep tech innovation Netherlands"],
            "seeds": [
                "The Dutch government was right to restrict ASML chip technology exports to China under US pressure, as the security risks outweigh the trade costs.",
                "The EU AI Act will benefit Dutch businesses in the long run by creating legal clarity, even if short-term compliance costs are significant.",
                "The Netherlands should invest more in domestic AI research capacity to reduce dependence on US and Chinese platforms.",
                "The Dutch Data Protection Authority needs significantly larger enforcement budgets to hold Big Tech accountable under GDPR.",
                "ASML's success demonstrates that the Netherlands should prioritise deep-tech industrial policy over further growth of financial services.",
                "Citizens' digital identity systems should be built on open-source software under public control, not proprietary commercial platforms.",
                "The Netherlands should establish a national algorithmic oversight body with investigatory powers and a public register of government AI systems.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the Netherlands: Housing, flex work, and Dutch prosperity",
            "description": "The housing crisis, flex contracts, pension reform, and whether Dutch prosperity is shared fairly.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **structural economic policy** — housing, labour market reform, pensions, and tax. "
                "Further reading (optional) — CPB Netherlands Bureau for Economic Policy Analysis, "
                "CBS housing data, ABP pension fund reports, SER (Social and Economic Council) reports."
            ),
            "article_keywords": ["Netherlands housing crisis 100000 homes", "flex contract zero hours Netherlands reform", "Dutch pension system defined contribution", "Netherlands tax treaty multinationals", "hypotheekrenteaftrek mortgage interest deduction"],
            "seeds": [
                "The Dutch government should directly build or commission at least 100,000 homes per year to address the structural housing shortage.",
                "Zero-hours and flex contracts should be substantially restricted so that more workers have access to permanent employment.",
                "The transition to defined-contribution pensions (the new Dutch pension system) is fairer for younger workers than the previous system.",
                "The Netherlands benefits disproportionately from its tax treaty network and should close loopholes exploited by multinationals.",
                "The wage gap between permanent and temporary workers doing equivalent jobs should be prohibited by law.",
                "Mortgage interest tax relief (hypotheekrenteaftrek) disproportionately benefits homeowners at the expense of renters and should be phased out.",
                "The Netherlands should make childcare free or near-free as a universal entitlement, not only for working parents.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the Netherlands: Healthcare access, the eigen risico, and elderly care",
            "description": "Is the Dutch insurance-based healthcare system still working equitably for everyone?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Dutch healthcare access, the eigen risico (deductible), and long-term care**. "
                "Further reading (optional) — RIVM National Institute for Public Health, Zorginstituut Nederland, "
                "SCP Netherlands Institute for Social Research on healthcare access, NZa healthcare authority data."
            ),
            "article_keywords": ["Dutch eigen risico healthcare deductible abolish", "Netherlands elderly care underfunding", "mental health waiting times Netherlands", "Dutch GP shortage rural areas", "Dutch preventive health sugar tax"],
            "seeds": [
                "The eigen risico (compulsory health deductible) should be abolished because it deters people from seeking necessary care.",
                "Elderly care in the Netherlands is chronically underfunded and requires a major sustained increase in public spending.",
                "Mental health waiting times in the Netherlands are unacceptably long and require urgent structural investment.",
                "The Dutch compulsory health insurance model achieves broader coverage than fully public systems in comparable countries.",
                "Preventive public health measures — including taxes on tobacco and ultra-processed food — are justified even where they restrict individual choice.",
                "GP shortages in rural areas of the Netherlands constitute a serious equity problem that requires targeted government intervention.",
                "The Netherlands should introduce a sugar tax on soft drinks and ultra-processed food to address rising rates of obesity and diet-related disease.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the Netherlands: Defence, Ukraine, and Dutch foreign policy",
            "description": "F-16s to Ukraine, NATO obligations, MH17, and the Netherlands' role in European security.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **alliances, military support, and international justice**. "
                "Further reading (optional) — IISS on Dutch defence capabilities, Dutch Court of Appeal MH17 damages ruling (2022), "
                "NATO burden-sharing assessments, AIV (Advisory Council on International Affairs) reports."
            ),
            "article_keywords": ["Netherlands F-16 Ukraine transfer", "Netherlands NATO 2 percent defence", "MH17 Russia verdict damages", "Dutch parliamentary defence oversight", "European defence force Netherlands"],
            "seeds": [
                "The Netherlands was right to transfer F-16 fighter jets to Ukraine in support of its legal right to self-defence.",
                "The Netherlands should reach NATO's 2% of GDP defence spending target within this decade.",
                "The MH17 damages claim against Russia should be pursued through all available international legal mechanisms.",
                "Dutch special forces involvement in armed conflicts should require explicit prior parliamentary authorisation.",
                "The Netherlands should advocate within the EU for a common European defence capability to reduce structural dependence on the US.",
                "Development aid should not be cut to fund higher defence spending — the two serve different strategic objectives.",
                "The Netherlands should advocate within NATO and the EU for formal security guarantees for non-NATO states on NATO's eastern border.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the Netherlands: Democracy, coalition formation, and political trust",
            "description": "Prolonged kabinetsformatie, the rise of populism, and what the Dutch political system needs.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **institutional design** — the formation process, media freedom, and civic trust. "
                "Further reading (optional) — Montesquieu Institute constitutional research, "
                "Parlement.com, RSF Press Freedom Index, ODIHR electoral reports on the Netherlands."
            ),
            "article_keywords": ["Netherlands proportional representation coalition formation", "kabinetsformatie time limit democratic", "NPO public broadcaster independence", "Dutch constitution rule of law protection", "Netherlands civic education schools"],
            "seeds": [
                "The Netherlands' proportional representation system produces more representative policy outcomes than majoritarian alternatives.",
                "Coalition formation taking months undermines democratic accountability and the process should be subject to statutory time limits.",
                "Public broadcasters like NPO need stronger statutory independence guarantees against political interference.",
                "The Dutch constitution should include explicit protection for the rule of law that cannot be overridden by parliamentary majorities.",
                "Municipalities should have substantially greater financial autonomy from the national government.",
                "Civic and media literacy education should be mandatory core subjects at secondary school level.",
                "The Netherlands should introduce binding referendums at national level, with proper information campaigns, as a complement to representative democracy.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the Netherlands: Immigration, integration, and Dutch identity",
            "description": "Asylum system pressure, integration policy, and what it means to be Dutch today.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design**, not on people's backgrounds or worth. "
                "Further reading (optional) — CBS Statistics Netherlands migration data, COA (Central Agency for the Reception of Asylum Seekers) reports, "
                "SCP Netherlands Institute for Social Research integration data, European Court of Justice asylum rulings."
            ),
            "article_keywords": ["Netherlands EU asylum obligations distribution", "Dutch integration programme mandatory", "Netherlands housing crisis causes migration", "labour market discrimination Netherlands", "Dutch civic identity democratic values"],
            "seeds": [
                "The Netherlands must honour its legal obligations under EU asylum rules even when the volume of applications is high.",
                "Integration programmes should be mandatory, well-funded, and focused on language acquisition and employment from the outset.",
                "The Dutch housing crisis is caused primarily by inadequate supply and planning failures, not by immigration.",
                "Discrimination in the Dutch labour and housing market must be actively countered through law enforcement, not just legislation.",
                "Municipalities should have the right to distribute asylum seekers across the country equitably, rather than concentrating them.",
                "Dutch civic identity should be grounded in shared democratic values, not ethnic or cultural heritage.",
                "The Netherlands should allow newcomers to vote in local elections after two years of legal residence, as several other EU countries already permit.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the Netherlands: MBO, HBO, and education for a changing economy",
            "description": "Skills shortages, early tracking, and whether Dutch education is fit for the future.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **system design and access** — the MBO-HBO-WO ladder, teacher pay, and early selection. "
                "Further reading (optional) — Inspectie van het Onderwijs (Education Inspectorate) reports, "
                "Onderwijsraad (Education Council) policy analyses, CPB education returns research, PISA Netherlands data."
            ),
            "article_keywords": ["Netherlands early tracking 12 age inequality", "MBO vocational prestige Netherlands", "Dutch teacher shortage pay", "early childhood education Netherlands disadvantage", "Dutch student finance grant loan"],
            "seeds": [
                "Early tracking at age 12 into secondary school streams (vmbo/havo/vwo) entrenches socioeconomic inequality and should be delayed.",
                "MBO graduates contribute as much to the Dutch economy as university graduates and should be treated as equivalent in terms of public investment.",
                "Teacher shortages in the Netherlands are the direct result of wages falling behind other graduate professions — pay must rise.",
                "The Netherlands should invest substantially more in early childhood education and care to close disadvantage gaps before children start primary school.",
                "The student finance system (studielening) should be replaced with grants for students from lower-income families.",
                "Civic literacy and media literacy should be mandatory core subjects at primary school level.",
                "The Netherlands should establish a national skills forecasting system so training programmes are aligned with actual labour market needs.",
            ],
        },
    ]


def _curriculum_ie() -> List[dict[str, Any]]:
    """Ireland-specific big questions grounded in Irish society and political debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Ireland: Climate action, farming, and the Irish environment",
            "description": "Can Ireland meet its legally binding climate targets while protecting rural livelihoods?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Irish policy choices** — agricultural methane, peat bog restoration, and planning reform. "
                "Further reading (optional) — EPA Ireland greenhouse gas inventories, Climate Action Plan 2024, "
                "IPCC AR6 on agriculture methane, Climate Change Advisory Council annual reviews."
            ),
            "article_keywords": ["Ireland cattle herd reduction climate", "Ireland peat bog restoration carbon", "Ireland wind solar planning fast track", "Ireland per capita emissions Europe", "Ireland offshore wind energy export"],
            "seeds": [
                "Ireland must reduce cattle and dairy herd sizes significantly to meet its legally binding sectoral emission targets under the Climate Action Plan.",
                "Peat bog restoration should be prioritised over continued agricultural use even where this displaces farmers from traditional land use.",
                "Planning for large-scale onshore and offshore wind and solar farms should be fast-tracked given Ireland's renewable energy potential.",
                "Ireland's per-capita emissions are among the highest in the EU and this requires urgent policy change across agriculture, transport, and buildings.",
                "Community benefit funds from wind farms should flow directly to affected residents, not only to local authorities.",
                "Ireland should invest in offshore wind at the scale needed to become a net exporter of clean electricity to Europe.",
                "Ireland should set a binding domestic target to reduce transport emissions by 50% by 2030, backed by investment in rural public transport.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Ireland: Tech multinationals, data centres, and digital governance",
            "description": "Is Ireland's dependence on US tech FDI a strength or a structural economic vulnerability?",
            "information_title": "How to read these statements",
            "information_body": (
                "Consider Ireland's role as **European headquarters** for US tech giants and as EU lead supervisor under GDPR. "
                "Further reading (optional) — DPC (Data Protection Commission) enforcement statistics, "
                "ESRI economic analysis of FDI, EirGrid grid capacity reports, IDA Ireland FDI data."
            ),
            "article_keywords": ["Ireland tech FDI concentration risk", "DPC GDPR enforcement resources", "Ireland data centres electricity grid", "Ireland corporation tax rate multinationals", "Irish universities AI computer science"],
            "seeds": [
                "Ireland relies too heavily on a small number of US tech multinationals and needs to actively diversify its economic base.",
                "The Data Protection Commission needs significantly more resources to enforce GDPR effectively against major tech platforms.",
                "New data centres in Ireland should not be approved while the national electricity grid faces capacity constraints.",
                "Ireland benefits substantially from tech FDI and should actively compete to retain these companies while meeting regulatory obligations.",
                "Irish universities should invest substantially more in AI and computer science to build indigenous domestic tech capacity.",
                "Tech companies' low effective tax rates in Ireland benefit the exchequer in the short term but are unfair to other EU member states.",
                "Ireland should use its position as European headquarters for major tech companies to actively shape global AI governance from within.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Ireland: Housing, cost of living, and the Irish economy",
            "description": "Ireland's housing emergency, reliance on corporate tax, and the cost of living crisis.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **structural questions** about Ireland's economy — housing supply, tax base, and wages. "
                "Further reading (optional) — ESRI housing research, Department of Finance Tax Strategy Group, "
                "Living Wage Technical Group reports, SCSI property market data."
            ),
            "article_keywords": ["Ireland state housing social affordable direct build", "Airbnb short-term let restriction Ireland", "Ireland corporate tax diversification", "Ireland living wage minimum wage", "Ireland planning high density transit"],
            "seeds": [
                "The state should directly build social and affordable housing at substantial scale rather than primarily relying on the private market.",
                "Short-term rental platforms should be heavily restricted in areas with acute housing shortages.",
                "Ireland must begin reducing its reliance on corporate tax revenues by broadening the tax base before the next economic shock.",
                "The minimum wage in Ireland should rise to a rate that covers rent and basic living costs in all major cities.",
                "Planning permission for high-density housing near public transport should be substantially streamlined.",
                "Remote working rights should be enshrined in legislation to reduce geographic concentration of employment in Dublin.",
                "The Land Development Agency should be given greater powers and a larger capital allocation to directly deliver social and affordable housing at scale.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Ireland: Sláintecare, the two-tier system, and mental health",
            "description": "Can Ireland build the universal health system it legislated for?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Sláintecare implementation, waiting lists, and the public-private divide** in Irish healthcare. "
                "Further reading (optional) — Sláintecare Implementation Advisory Council reports, "
                "HIQA (Health Information and Quality Authority) analyses, "
                "Mental Health Commission annual reports, Oireachtas health committee hearings."
            ),
            "article_keywords": ["Sláintecare implementation tax increase", "private health insurance public hospital beds Ireland", "mental health spending Ireland budget", "GP fee abolition Ireland", "HSE reform regional health authorities"],
            "seeds": [
                "Sláintecare should be implemented in full, even if this requires significant tax increases.",
                "Private health insurance in Ireland gives those who can afford it unfair priority access to public hospital beds.",
                "Mental health spending in Ireland is too low as a share of the overall health budget and should be doubled.",
                "GP fees should be abolished for all patients, not only medical card holders, to remove a financial barrier to primary care.",
                "Consultants with private practices should not be permitted to hold public hospital contracts simultaneously.",
                "The HSE is too large and centralised and should be replaced with empowered regional health authorities with clear accountability.",
                "A women's health strategy, including access to IVF and reproductive healthcare, should be a funded priority in every health budget.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Ireland: Neutrality, defence, and Ireland's role in the world",
            "description": "Should Ireland maintain military neutrality or assume greater responsibility for European security?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **Irish neutrality, UN peacekeeping, and European defence**. "
                "Further reading (optional) — Government Commission on the Future of Irish Defence Forces (2022), "
                "Irish Neutrality League, PDFORRA reports, EU Common Security and Defence Policy documents."
            ),
            "article_keywords": ["Irish military neutrality reform NATO", "Ireland defence spending increase", "Irish neutrality constitution", "Ireland UN peacekeeping contribution", "EU mutual defence Article 42 Ireland"],
            "seeds": [
                "Ireland's policy of military neutrality should be formally reviewed — it no longer reflects the realities of European security.",
                "Ireland should increase defence spending significantly given the deteriorating European security environment.",
                "Irish neutrality should be enshrined in the constitution to prevent future governments abandoning it without a public mandate.",
                "Ireland should maintain a strong position on international humanitarian law and Palestinian civilian protection at the UN.",
                "EU mutual defence commitments under Article 42.7 already effectively qualify Irish neutrality in practice.",
                "Ireland should substantially expand its UN peacekeeping contributions as an expression of its foreign policy values.",
                "Ireland should formally and publicly support Palestinian statehood at the UN and use its Security Council membership to advance that position.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Ireland: The Dáil, Citizens' Assemblies, and Irish democracy",
            "description": "Electoral reform, Citizens' Assemblies, and how to restore trust in Irish politics.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** — not about any party's current record. "
                "Further reading (optional) — Electoral Commission Ireland reports, "
                "Citizens' Assembly Ireland published recommendations, "
                "Democratic Audit of Ireland, SIPO (Standards in Public Office Commission) reports."
            ),
            "article_keywords": ["Ireland Citizens Assembly deliberative democracy", "Dáil reform sitting hours scrutiny", "Seanad abolition reform Ireland", "political donations ban corporations Ireland", "votes abroad Irish citizens Dáil"],
            "seeds": [
                "Ireland's Citizens' Assemblies have been a genuine democratic innovation and should be used more frequently for complex policy questions.",
                "Dáil sitting hours should be extended and reformed so TDs spend more time scrutinising legislation.",
                "Political donations from corporations and property developers should be banned entirely.",
                "Voting in Dáil elections should be extended to Irish citizens resident abroad.",
                "Lowering the voting age to 16 in all elections would strengthen democratic participation.",
                "Ireland should consider moving to a unicameral parliament by abolishing or fundamentally reforming the Seanad.",
                "The number of TDs in Dáil Éireann should be increased to improve parliamentary scrutiny as the population and legislative workload grow.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Ireland: Immigration, identity, and modern Irish society",
            "description": "Ireland's rapidly changing demographics and what it means to belong in contemporary Ireland.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy and values**, not on people's backgrounds. "
                "Further reading (optional) — CSO Census 2022 data, ESRI integration research, "
                "International Protection Act 2024, Report of the Commission on the Irish Diaspora."
            ),
            "article_keywords": ["Ireland direct provision abolish housing", "Ireland immigration economic contribution", "Ireland institutional abuse reparations Magdalene", "homelessness Ireland housing policy failure", "Irish diaspora return immigration"],
            "seeds": [
                "Direct provision for asylum seekers should be replaced with community-based housing and support — the International Protection Act 2024 begins this transition.",
                "Ireland's economic success depends substantially on continued immigration and the state should make this case publicly.",
                "The Irish state has a duty to formally acknowledge and pay reparations to survivors of institutional abuse.",
                "Homelessness in Ireland is a political and policy failure, not an inevitable outcome of market conditions.",
                "Ireland should make it substantially easier for the Irish diaspora to return and contribute to the economy.",
                "Anti-immigration rhetoric in Irish political discourse poses a serious risk to social cohesion.",
                "Ireland should adopt an active anti-racism strategy with funded enforcement mechanisms and measurable targets.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Ireland: CAO, apprenticeships, and the future of Irish education",
            "description": "The points race, teacher pay, and whether Irish education delivers for all.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, the CAO system, and skills** — not individual school performance. "
                "Further reading (optional) — HEA (Higher Education Authority) access reports, "
                "ESRI 'Learning for Life' education research, "
                "SOLAS (Further Education and Training Authority), Teaching Council Ireland."
            ),
            "article_keywords": ["CAO points race reform Ireland", "Ireland teacher pay graduate comparison", "apprenticeships Ireland funding parity degree", "Irish schools personal finance civic education", "religious schools admission criteria state funding"],
            "seeds": [
                "The CAO points race places harmful levels of pressure on teenagers and should be fundamentally reformed.",
                "Teacher pay in Ireland is too low relative to other graduate professions and must rise to attract and retain talent.",
                "Apprenticeships and further education courses should be funded and socially respected at the same level as academic degrees.",
                "Irish schools should teach personal finance, civic education, and media literacy as compulsory core subjects.",
                "Religious bodies should have no role in determining admissions criteria for state-funded schools.",
                "Third-level fees should be abolished and replaced with a graduate contribution collected through the tax system.",
                "All state-funded schools should be required to offer the same curriculum regardless of religious ethos.",
            ],
        },
    ]


def _curriculum_de() -> List[dict[str, Any]]:
    """Germany-specific big questions grounded in German political debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Germany: Energiewende, nuclear, and climate targets",
            "description": "What does the Energiewende cost, has the nuclear phase-out been a mistake, and can Germany meet its 2045 climate neutrality target?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **German energy policy choices** — the nuclear phase-out, coal exit, Energiewende costs, and 2045 climate neutrality. "
                "Further reading (optional) — Agora Energiewende analysis, Umweltbundesamt (Federal Environment Agency) reports, "
                "DIW Berlin energy economics, Federal Climate Change Act (KSG) targets."
            ),
            "article_keywords": ["Germany nuclear phase-out climate impact", "Kohleausstieg 2030 acceleration", "Energiewende cost electricity prices", "Germany green hydrogen industrial decarbonisation", "Autobahn speed limit emissions"],
            "seeds": [
                "Germany's decision to phase out nuclear power was a strategic error that increased both carbon emissions and energy costs.",
                "The Kohleausstieg (coal phase-out) should be accelerated to 2030 rather than allowed to slip to 2038.",
                "Germany's Energiewende demonstrates that large-scale renewable transitions are feasible, despite significant implementation costs.",
                "German households and industry pay electricity prices among the highest in Europe — this is a serious competitiveness problem.",
                "Germany should invest heavily in green hydrogen production and infrastructure to decarbonise its industrial base.",
                "Germany should introduce Autobahn speed limits — it is the only major EU country without permanent motorway speed restrictions.",
                "Germany should require all new buildings to meet near-zero energy standards and offer substantial subsidies for retrofitting existing stock.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Germany: Digitalisation, AI, and the Mittelstand",
            "description": "Can Germany's traditional industrial strengths survive the digital revolution, and is the EU AI Act an asset or a handicap?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **German digital policy**, GDPR origins, EU AI Act compliance, and the Mittelstand's digital readiness. "
                "Further reading (optional) — Bitkom digitalisation index, Fraunhofer AI research, "
                "DIW digital economy analysis, Monopolies Commission on digital markets."
            ),
            "article_keywords": ["Germany Mittelstand digitalisation lag", "Germany GDPR data protection AI investment", "Germany national AI strategy US China", "German manufacturing AI automation jobs", "European sovereign cloud Germany"],
            "seeds": [
                "Germany's Mittelstand is falling dangerously behind in digitalisation and requires active government intervention and investment.",
                "Germany's strong data protection tradition, which shaped GDPR, should not be weakened to attract tech investment.",
                "Germany needs a national AI strategy that actively competes with the US and China in capability, not only regulation.",
                "German manufacturing should embrace AI-driven automation even where it reduces employment in specific sectors.",
                "Germany should lead in developing European sovereign cloud infrastructure independent of US hyperscale providers.",
                "Public services in Germany are unacceptably analogue — digital government must become a national strategic priority.",
                "Germany should strengthen anti-monopoly measures against US and Chinese digital platforms that dominate German digital markets.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Germany: Growth, the debt brake, and the German economic model",
            "description": "Is the social market economy still fit for purpose? What should be done about the Schuldenbremse and industrial subsidies?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **structural economic questions** — the Schuldenbremse, Mindestlohn, Kurzarbeit, and industrial policy. "
                "Further reading (optional) — Sachverständigenrat (German Council of Economic Experts) annual reports, "
                "IMF Germany Article IV consultations, DIW and ifo Institute economic analyses."
            ),
            "article_keywords": ["Schuldenbremse debt brake reform investment", "Germany Kurzarbeit short-time work scheme", "Mindestlohn 15 euro minimum wage", "Germany automotive industrial dependency", "Eastern Germany structural economic gap"],
            "seeds": [
                "The Schuldenbremse (constitutional debt brake) should be reformed to allow public investment in infrastructure and the green transition.",
                "Germany's Kurzarbeit scheme should be maintained as a permanent feature of the labour market rather than only an emergency measure.",
                "The Mindestlohn (minimum wage) should rise to €15 per hour and be indexed to living costs.",
                "Germany's economic model is dangerously over-dependent on automotive exports and requires active diversification.",
                "Federal and state industrial subsidies to the car sector have delayed necessary transformation into electric vehicles and clean technology.",
                "Eastern Germany still faces structural economic disadvantages that require sustained, targeted federal support.",
                "Germany should develop active industrial policy to support the Mittelstand's transition to employee ownership and worker co-determination models.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Germany: The two-tier health system and care for an aging society",
            "description": "Is Germany's dual public-private health insurance system equitable, and can long-term care be sustainably funded?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **GKV vs PKV, Pflegereform, and care workforce** issues in Germany. "
                "Further reading (optional) — Barmer GEK health insurance reports, SVR Gesundheit (Advisory Council on Health), "
                "Bertelsmann Stiftung hospital reform analysis, Federal Ministry of Health data."
            ),
            "article_keywords": ["GKV PKV Germany merge single system", "Germany Pflegeversicherung long-term care reform", "German care workers pay shortage", "German hospital reform consolidation", "Germany mental health waiting times"],
            "seeds": [
                "Germany should merge its statutory (GKV) and private (PKV) health insurance systems into a single solidarity-based system.",
                "Long-term care insurance (Pflegeversicherung) contributions are substantially too low and must rise to meet future demographic demand.",
                "Care workers in Germany are systematically underpaid and understaffed — this constitutes a policy failure requiring urgent remedy.",
                "Higher earners should not be able to opt out of the statutory health insurance system.",
                "Germany's hospital system has too many small, underfunded hospitals and needs consolidation to improve quality and efficiency.",
                "Mental health waiting times in Germany are unacceptably long and constitute a public health crisis.",
                "Germany should invest substantially more in preventive health programmes targeting obesity, smoking, and alcohol-related disease.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Germany: Zeitenwende, Ukraine, and German security policy",
            "description": "Has Germany genuinely turned the page on post-WWII pacifism? What does the Zeitenwende require in practice?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **German rearmament, Russia policy, and European security**. "
                "Further reading (optional) — Stiftung Wissenschaft und Politik (SWP) security analyses, "
                "Bundeswehr capability assessments, IISS Military Balance Germany, "
                "Bundestag defence committee reports."
            ),
            "article_keywords": ["Germany Zeitenwende defence spending NATO", "Bundeswehr readiness capability", "Germany Nordstream energy dependence Russia mistake", "Germany Taurus Ukraine weapons", "European defence autonomy Germany"],
            "seeds": [
                "Germany's post-WWII pacifist strategic culture has been a liability for European security that the Zeitenwende must genuinely change.",
                "Germany should reach NATO's 2% of GDP defence spending target and sustain it as a floor, not a ceiling.",
                "Germany made a serious strategic error in allowing its energy dependence on Russian gas to deepen under Nord Stream 1 and 2.",
                "Germany should supply Taurus cruise missiles to Ukraine — the strategic case for doing so outweighs the risks of escalation.",
                "Germany's experience of Ostpolitik does not vindicate engagement with authoritarian states as a general model — context matters.",
                "Germany should take a leading role in building a genuinely autonomous European defence capability within NATO.",
                "Germany should take a leadership role in coordinating EU sanctions policy toward Russia rather than lagging behind smaller member states.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Germany: Democracy, the AfD, and German political institutions",
            "description": "How should Germany respond to the rise of the AfD and strengthen democratic resilience?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **institutional design** — the Basic Law, party bans, and democratic resilience mechanisms. "
                "Further reading (optional) — Bundesverfassungsgericht (Federal Constitutional Court) jurisprudence, "
                "Verfassungsschutz annual reports, Bertelsmann Transformation Index, "
                "Venice Commission assessments of Germany."
            ),
            "article_keywords": ["AfD ban Article 21 Basic Law unconstitutional", "Bundestag size reform electoral", "AfD firewall coalition CDU SPD", "Federal Constitutional Court independence Germany", "Germany lobbying transparency law"],
            "seeds": [
                "The AfD should be subject to a formal ban procedure under Article 21 of the Basic Law if evidence of anti-constitutional activity is established.",
                "Germany's 5% electoral threshold prevents fragmentation but excludes legitimate minority voices — its level should be reconsidered.",
                "The Bundestag is too large following recent electoral reforms and should be reduced through a revised electoral law.",
                "The democratic firewall against coalition with the AfD is necessary to defend constitutional democratic norms.",
                "The Federal Constitutional Court's independence must be protected against attempts by parliamentary majorities to alter its composition.",
                "Germany needs substantially stronger lobbying transparency legislation to reduce the undue influence of corporations on legislation.",
                "Germany should make naturalisation easier and faster — current citizenship requirements are unnecessarily burdensome for long-term residents.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Germany: Migration, integration, and German identity",
            "description": "From Willkommenskultur to the current debate — where should German migration and integration policy go?",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design and values** — not on individuals' backgrounds. "
                "Further reading (optional) — Sachverständigenrat Migration (Expert Council on Integration and Migration), "
                "BAMF Federal Office for Migration and Refugees, IAB labour market integration research, "
                "Bertelsmann Stiftung integration barometer."
            ),
            "article_keywords": ["Germany 2015 Willkommenskultur refugee assessment", "Germany integration programme funding", "Germany skilled migration needs pension", "Germany deportation Afghanistan failed asylum", "Germany anti-discrimination enforcement"],
            "seeds": [
                "Germany's 2015 Willkommenskultur was the appropriate moral and legal response to the European refugee crisis.",
                "Integration programmes in Germany need substantially more funding and must be completed before permanent status is determined.",
                "Germany needs significantly more skilled migration to sustain its economy, fill labour shortages, and fund its pension system.",
                "Deportations of failed asylum seekers to conflict-affected countries like Afghanistan should not be carried out.",
                "Anti-discrimination laws in Germany require significantly stronger enforcement — the gap between legal protection and lived experience is too wide.",
                "Germany's migration debate has moved too far in the direction of restriction, at the cost of addressing genuine long-term economic needs.",
                "Germany should increase the proportion of students progressing to university by investing in higher education access, not only in the vocational route.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Germany: Bildung, Gymnasium, and equity in education",
            "description": "Does the German education system still serve children from all backgrounds equitably?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **system design and equity** — early selection, Gymnasium prestige, Ausbildung, and Bildungsföderalismus. "
                "Further reading (optional) — PISA results for Germany, KMK (Standing Conference of the Ministers of Education) data, "
                "BMBF education reports, Bertelsmann Stiftung Chancenspiegel social mobility research."
            ),
            "article_keywords": ["Germany early tracking 10 Gymnasium inequality", "German dual vocational Ausbildung undervalued", "Germany Bildungsföderalismus 16 state systems", "Germany teacher pay national standard", "Germany Ganztagsschule full-day school right"],
            "seeds": [
                "Germany's early selection at age 10 for Gymnasium, Realschule, or Hauptschule tracks systematically disadvantages children from lower-income families.",
                "The dual vocational training system (Ausbildung) is undervalued relative to academic routes and should receive equivalent public investment.",
                "Germany's Bildungsföderalismus — 16 separate state school systems with different curricula — creates unacceptable inequality of educational experience.",
                "Teacher pay in Germany should be set at a national standard and raised for all states.",
                "All German children should have access to full-day schooling (Ganztagsschule) as a legal right.",
                "German universities are significantly underfunded by international comparison and this threatens research quality.",
                "Germany should require all secondary schools to teach civic literacy and democratic participation as a compulsory subject.",
            ],
        },
    ]


def _curriculum_fr() -> List[dict[str, Any]]:
    """France-specific big questions grounded in French political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for France: Nuclear, agriculture, and the energy transition",
            "description": "Can France lead Europe on nuclear while meeting its climate targets and addressing agricultural emissions?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **French energy choices** — nuclear expansion, agricultural methane, and the Loi Climat et Résilience. "
                "Further reading (optional) — Haut Conseil pour le Climat annual reports, RTE energy scenarios, "
                "ADEME energy transition analyses, EDF corporate reports."
            ),
            "article_keywords": ["France nuclear EDF expansion plan", "French agriculture methane emissions reform", "France building insulation renovation", "EDF renationalisation energy sovereignty", "French farmers protests environmental reform"],
            "seeds": [
                "France was right to maintain and expand nuclear power as the backbone of a low-carbon electricity grid.",
                "France's agricultural sector must substantially reduce methane emissions even though this threatens some traditional farming practices.",
                "French households should face binding requirements to insulate their homes as part of the national decarbonisation strategy.",
                "EDF's renationalisation was necessary to maintain French energy sovereignty and coordinate the nuclear build programme.",
                "France should use its nuclear expertise to help other EU countries decarbonise rather than discouraging nuclear in European energy policy.",
                "French farmers' protests should not be used to delay necessary environmental reforms in agricultural policy.",
                "France should introduce a carbon border adjustment on all imports to complement the EU's CBAM and protect domestic industry from unfair competition.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for France: AI, tech sovereignty, and La French Tech",
            "description": "Can France build world-class AI while defending European digital sovereignty?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **French tech policy**, the French Tech ecosystem, CNIL enforcement, and EU AI Act governance. "
                "Further reading (optional) — CNIL annual reports, France Stratégie AI analyses, "
                "Mistral AI technical papers, Conseil National du Numérique reports."
            ),
            "article_keywords": ["France Mistral AI investment sovereign", "CNIL enforcement Big Tech France", "France TikTok ban government devices", "French cultural exception AI generated content", "EU AI copyright training data France"],
            "seeds": [
                "France should invest substantially more in AI companies like Mistral to challenge US and Chinese dominance.",
                "The CNIL needs a larger budget and stronger enforcement powers to hold major tech platforms accountable under GDPR.",
                "France's approach to restricting TikTok on government devices should be extended to other contexts where state data security is at risk.",
                "French cultural exception policies should be extended to AI-generated content and digital platforms.",
                "France should lead Europe in requiring that AI training data respects copyright and that rights-holders are compensated.",
                "European digital sovereignty is best achieved through common European standards and capabilities, not through national protectionism.",
                "France should require that AI training datasets used by French companies comply with EU copyright law and cultural diversity obligations.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for France: Retraites, the 35-hour week, and the French economic model",
            "description": "Macron's pension reform, labour market flexibility, and who pays for France's social model.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **structural policy questions** about the French economic and social model. "
                "Further reading (optional) — Conseil d'Analyse Économique (CAE) research, "
                "INSEE labour market data, France Stratégie productivity analyses, "
                "COR (Conseil d'Orientation des Retraites) pension assessments."
            ),
            "article_keywords": ["French pension reform 64 retirement age", "35 heures France economic impact", "French labour code CDI CDD rigidity", "French state size public spending GDP", "France youth unemployment structural causes"],
            "seeds": [
                "Raising the French retirement age to 64 was economically necessary given demographic trends, even though it was politically contested.",
                "The 35-hour working week has protected French workers' quality of life without the economic damage that critics predicted.",
                "France's labour code makes companies too cautious about hiring on permanent (CDI) contracts, contributing to high youth unemployment.",
                "The French state at around 57% of GDP is the highest in the OECD and requires structural reform, not only efficiency savings.",
                "France needs to invest significantly more in vocational training to reduce chronic youth unemployment.",
                "The two-tier French labour market — insiders with CDI protection and outsiders on precarious contracts — requires fundamental reform.",
                "France should conduct a formal national reckoning with its colonial history through school curricula reform, museum policy, and official acknowledgement.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for France: Sécurité Sociale, déserts médicaux, and French healthcare",
            "description": "Is France's acclaimed universal health system still delivering equitably for everyone?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, funding, and the désertification médicale** affecting rural France. "
                "Further reading (optional) — DREES health statistics, Cour des Comptes healthcare audits, "
                "IRDES health economics research, INSEE geographic health access data."
            ),
            "article_keywords": ["France Sécurité Sociale universal coverage model", "déserts médicaux rural GP shortage France", "French private clinics public subsidies", "France mental health funding European comparison", "French emergency department A&E waiting times"],
            "seeds": [
                "France's universal health coverage model is one of its greatest social achievements and must be protected against cuts.",
                "Medical deserts in rural France constitute a public health emergency requiring mandatory measures, not only financial incentives.",
                "Private clinics should not receive public subsidies while the public hospital system is underfunded.",
                "Mental health services in France are severely underfunded relative to other comparable European countries.",
                "France should introduce a tax on ultra-processed food to address rising rates of obesity and diet-related disease.",
                "Waiting times in French accident and emergency departments have become unacceptably long and reflect structural workforce failures.",
                "France should expand access to contraception and reproductive health services, which are currently underprovided in rural areas.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for France: Nuclear deterrent, Françafrique, and European strategic autonomy",
            "description": "France's nuclear posture, Africa policy, and Macron's case for EU strategic autonomy.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **French military power, postcolonial obligations, and European defence**. "
                "Further reading (optional) — IRSEM (Institut de Recherche Stratégique de l'École Militaire), "
                "French Senate defence committee reports, IFRI security analyses, "
                "French White Paper on Defence and National Security."
            ),
            "article_keywords": ["French nuclear deterrent force de frappe", "Françafrique French military Africa withdrawal", "EU strategic autonomy Macron", "France Ukraine military support", "European defence collective funding bonds"],
            "seeds": [
                "France's independent nuclear deterrent is an essential contribution to European security and should be maintained.",
                "France's post-colonial military presence in Africa has done more harm than good and should be ended.",
                "Macron's push for EU strategic autonomy is strategically correct — Europe cannot remain indefinitely dependent on US security guarantees.",
                "France should contribute more military equipment to Ukraine, consistent with supporting its right to self-defence.",
                "France's permanent UN Security Council seat carries special responsibilities it has not consistently met.",
                "European defence should be funded collectively through EU bonds and common procurement, not only through national defence budgets.",
                "France should reintegrate more fully into NATO's integrated military command structure to strengthen European defence coordination.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for France: La Ve République, gilets jaunes, and democratic reform",
            "description": "Is the Fifth Republic's strong presidency a democratic strength or a structural weakness?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** — the Fifth Republic's presidential power, referenda, and the National Assembly. "
                "Further reading (optional) — Conseil Constitutionnel jurisprudence, "
                "Terra Nova policy analyses, CEVIPOF political science research, "
                "Venice Commission assessments of French constitutional practice."
            ),
            "article_keywords": ["Fifth Republic presidential power reform parliamentary", "gilets jaunes economic inequality grievances", "France proportional representation National Assembly", "Article 49.3 parliament bypass France", "Citizens Convention Climate France deliberative"],
            "seeds": [
                "The Fifth Republic gives the President too much power and should be reformed toward a more genuinely parliamentary model.",
                "The gilets jaunes movement exposed legitimate grievances about economic inequality and democratic exclusion that have not been structurally addressed.",
                "France should introduce proportional representation for National Assembly elections.",
                "Using Article 49.3 to bypass parliament on major legislation without a democratic emergency undermines legislative legitimacy.",
                "Citizens' assemblies, as demonstrated by the Convention Citoyenne pour le Climat, should become a regular feature of French democracy.",
                "The rise of the Rassemblement National reflects failures by mainstream parties to address real economic concerns of peripheral France.",
                "France should significantly reduce the maximum term length for local elected officials to prevent entrenched local political oligarchies.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for France: Laïcité, immigration, and French cohesion",
            "description": "The headscarf debate, les banlieues, and what French republicanism means in practice.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design and values** — not on individuals' religious or cultural choices. "
                "Further reading (optional) — Haut Conseil à l'Intégration, INED migration statistics, "
                "Institut Montaigne banlieues research, CEVIPOF social cohesion surveys."
            ),
            "article_keywords": ["French laïcité religious expression limits", "banlieues economic exclusion France", "France immigration integration capacity", "discrimination hiring France Maghreb", "France republican integration model assessment"],
            "seeds": [
                "Laïcité as applied in France restricts legitimate religious expression in ways that go beyond what secularism requires.",
                "France's banlieues reflect decades of deliberate economic and geographic exclusion that policing cannot resolve.",
                "France's integration infrastructure is insufficiently resourced relative to the pace of arrivals, creating real social strain.",
                "Discrimination in hiring and housing against French citizens of immigrant background is a serious ongoing injustice requiring active enforcement.",
                "France's republican integration model — prioritising individual assimilation over communitarian recognition — has produced contested outcomes that require honest evaluation.",
                "Zone-based affirmative action (discrimination positive géographique) targeting disadvantaged urban areas should be expanded.",
                "France should implement mandatory anti-discrimination training in all public sector hiring and in companies above a minimum size.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for France: Grandes écoles, le bac, and French education",
            "description": "Does French elite education perpetuate privilege more than it creates opportunity?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access and system design** — the grandes écoles, baccalauréat reform, Parcoursup, and lycée professionnel. "
                "Further reading (optional) — DEPP (Direction de l'Évaluation, de la Prospective et de la Performance) educational statistics, "
                "Cour des Comptes grandes écoles audit, France Stratégie social mobility research."
            ),
            "article_keywords": ["grandes écoles France privilege elite access", "Parcoursup algorithm university admission fairness", "lycée professionnel resources academic parity", "French baccalaureate reform assessment", "teacher pay France graduate comparison"],
            "seeds": [
                "The grandes écoles system perpetuates elite social reproduction and should be opened up through reformed admissions and integration with universities.",
                "Parcoursup's opaque algorithmic allocation makes university entrance less transparent and equitable than the previous system.",
                "Lycée professionnel students are resourced at a significantly lower level than academic track students and deserve equality of investment.",
                "The French baccalauréat reform has produced better subject alignment with students' abilities than the previous undifferentiated examination.",
                "Teacher pay in France has fallen significantly behind other graduate professions and must be raised substantially.",
                "Philosophy as a compulsory baccalauréat subject is a distinctive strength of French secondary education that should be retained.",
                "France should make French Sign Language (LSF) a recognised medium of instruction and increase resources for inclusive schooling.",
            ],
        },
    ]


def _curriculum_ca() -> List[dict[str, Any]]:
    """Canada-specific big questions grounded in Canadian political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Canada: Oil sands, the carbon price, and climate leadership",
            "description": "Can Canada credibly claim climate leadership while remaining one of the world's largest oil producers?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Canadian policy choices** — Trans Mountain, the federal carbon price, and Indigenous land rights. "
                "Further reading (optional) — Environment and Climate Change Canada emissions reports, "
                "Canadian Net-Zero Emissions Accountability Act, "
                "NRCAN natural resources data, Pembina Institute energy analysis."
            ),
            "article_keywords": ["Canada oil sands expansion climate credibility", "Canada federal carbon price", "Trans Mountain pipeline Indigenous rights", "Canada boreal forest carbon sink", "Canada clean electricity grid 2035"],
            "seeds": [
                "Canada cannot credibly claim climate leadership while continuing to expand oil sands production.",
                "The federal carbon price is the most cost-effective policy instrument for reducing Canadian emissions, even when it is politically contested.",
                "The Trans Mountain pipeline expansion should have been cancelled on environmental and Indigenous rights grounds.",
                "Canada should be a global leader in protecting its boreal forests as a major terrestrial carbon sink.",
                "Federal and provincial climate policies are insufficiently coordinated to achieve Canada's Paris Agreement commitments.",
                "Clean electricity should constitute 100% of Canada's grid by 2035 — the resources and technology to achieve this exist.",
                "Canada should introduce a moratorium on new oil and gas export permits while the country develops a binding long-term energy transition plan.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Canada: AI leadership, digital regulation, and the digital economy",
            "description": "Is Canada doing enough to keep its AI talent at home and shape global digital governance?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Canadian tech policy** — AI research investment, the Online Streaming Act (C-11), and federal AI governance. "
                "Further reading (optional) — CIFAR AI research reports, Canadian Institute for Advanced Research, "
                "Standing Committee on Industry Science and Technology on AI, OPC (Privacy Commissioner of Canada) reports."
            ),
            "article_keywords": ["Canada AI talent retention brain drain US", "Bill C-11 Online Streaming Act CRTC", "Canada federal AI regulation framework", "Canada PIPEDA privacy law reform GDPR", "Canada sovereign cloud computing infrastructure"],
            "seeds": [
                "Canada is losing too much AI research talent to the United States and needs major sustained investment to retain it.",
                "The Online Streaming Act (Bill C-11) is a legitimate attempt to ensure platforms fund Canadian cultural content in the digital age.",
                "Canada needs a comprehensive federal AI regulatory framework to protect citizens from algorithmic discrimination and harm.",
                "Canada's federal privacy law (PIPEDA) is outdated and needs to be strengthened to reach GDPR-equivalent standards.",
                "Public investment in computing infrastructure for AI research should be treated as strategic national infrastructure, not discretionary spending.",
                "Canada should develop sovereign cloud capacity rather than depending entirely on US-headquartered cloud providers for government data.",
                "Canada's federal government should make open-source AI development a national priority and fund public AI infrastructure as a shared public good.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Canada: Housing, wages, and the Canadian dream",
            "description": "Toronto and Vancouver housing costs, temporary foreign workers, and generational wealth inequality.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **structural policy** — housing supply, wages, and what Canada owes to workers. "
                "Further reading (optional) — CMHC housing supply analyses, Bank of Canada housing research, "
                "Parliamentary Budget Officer reports, Statistics Canada income and wealth data."
            ),
            "article_keywords": ["Canada federal housing affordable social direct build", "Canada zoning reform federal funding cities", "temporary foreign worker programme wages", "Canada minimum wage $20 living wage", "Canada immigration housing infrastructure capacity"],
            "seeds": [
                "The federal government should take a substantially more active role in directly building affordable housing rather than primarily funding provinces.",
                "Zoning reform to permit high-density housing near transit should be made mandatory for cities receiving federal infrastructure funding.",
                "Canada's temporary foreign worker programmes are being misused by some employers to undercut wages for Canadian workers.",
                "The federal minimum wage should rise to $20 an hour and be indexed to living costs.",
                "Canada's recent immigration levels have exceeded housing and infrastructure capacity, requiring better coordination of policy.",
                "Generational inequality in housing wealth — where older Canadians hold assets that younger Canadians cannot access — is a defining social challenge.",
                "Canada should reform its supply management system in dairy and poultry, which imposes significant costs on Canadian consumers.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Canada: Wait times, pharmacare, and the future of Medicare",
            "description": "Is Canadian universal healthcare still delivering on its founding promise?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **system design** — wait times, provincial jurisdiction, pharmacare, and dental care. "
                "Further reading (optional) — CIHI (Canadian Institute for Health Information) wait time data, "
                "Parliamentary Budget Officer pharmacare costing, CMA physician surveys, "
                "Romanow Commission on the Future of Health Care in Canada."
            ),
            "article_keywords": ["Canada universal healthcare wait times underfunding", "Canada pharmacare national programme", "Canada health transfer provinces federal", "Canada private surgical clinics Canada Health Act", "Canada dental pharmacare public coverage"],
            "seeds": [
                "Canada's universal healthcare system is chronically underfunded and requires major new sustained public investment.",
                "A national pharmacare programme covering all Canadians is long overdue and fiscally affordable.",
                "Federal health transfers to provinces should be substantially increased with accountability strings attached.",
                "Private surgical clinics operating alongside the public system violate the Canada Health Act's prohibition on extra-billing.",
                "Canada's mental health system is so severely underfunded that it constitutes a public health emergency.",
                "Dental care and vision care should be included in universal public coverage, as they are in most comparable countries.",
                "Canada should establish a national long-term care strategy with legally binding minimum standards and sustained federal funding.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Canada: NATO, Arctic sovereignty, and Canadian defence",
            "description": "NORAD modernisation, the 2% NATO target, and Canada's obligations in a changing security environment.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **Canadian military obligations, Arctic sovereignty, and alliance commitments**. "
                "Further reading (optional) — Canadian Defence Policy Review, House of Commons National Defence Committee, "
                "Arctic Council Canada, NORAD Modernization Plan, PBO defence spending analysis."
            ),
            "article_keywords": ["Canada NATO 2 percent defence spending commitment", "NORAD modernisation Canada", "Canadian Arctic sovereignty climate", "Canada Ukraine military support", "Canada domestic defence procurement"],
            "seeds": [
                "Canada should meet NATO's 2% of GDP defence spending commitment rather than continuing to free-ride on alliance partners.",
                "NORAD modernisation is essential for Canadian sovereignty and continental defence and should be funded without further delay.",
                "Canada has a special obligation to assert Arctic sovereignty given accelerating climate-driven access to Arctic waters.",
                "Canada should increase its military support to Ukraine significantly.",
                "Canadian defence spending should prioritise domestic procurement and industrial capability, not only purchasing US equipment.",
                "Canada should expand its UN peacekeeping contributions as an expression of its multilateral values.",
                "Canada should develop a specific Arctic defence strategy and invest in Arctic-capable military and coastguard assets.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Canada: Electoral reform, Senate, and democratic institutions",
            "description": "FPTP versus proportional representation, Senate reform, and trust in Canadian democratic institutions.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** — not claims about any party's record. "
                "Further reading (optional) — Electoral Reform Committee of the House of Commons (2016), "
                "Senate Modernization Report, Elections Canada data, Samara Centre for Democracy research."
            ),
            "article_keywords": ["Canada electoral reform proportional representation 2015 promise", "Senate reform abolish elected Canada", "Supreme Court appointment Parliament confirmation", "PMO power Parliament accountability", "lobbying transparency Canada federal"],
            "seeds": [
                "Canada should replace first-past-the-post with a proportional representation system, as was promised in the 2015 federal election.",
                "The Senate should be abolished or replaced with an elected body with a democratic mandate representing provinces.",
                "Supreme Court justices should be confirmed by a parliamentary committee rather than appointed solely by the Prime Minister.",
                "The power of the Prime Minister's Office over the government and Parliament is excessive and requires legislative constraints.",
                "Municipal governments need substantially more financial autonomy and tax powers to address urban challenges.",
                "Mandatory lobbying transparency should be strengthened so citizens can see who is influencing federal policy decisions.",
                "Canada should introduce fixed federal election dates, removing the Prime Minister's discretionary power to call early elections.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Canada: Reconciliation, immigration, and Canadian identity",
            "description": "Truth and Reconciliation, immigration levels, and what it means to be Canadian.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy and values** — not on the background of individual people. "
                "Further reading (optional) — Truth and Reconciliation Commission 94 Calls to Action, "
                "National Inquiry into MMIWG, Statistics Canada demographic projections, "
                "IRCC immigration levels plan data."
            ),
            "article_keywords": ["Canada TRC 94 calls to action implementation", "residential schools reparations Canada", "Canada immigration levels integration capacity", "anti-Asian racism Canada policy response", "Indigenous self-determination land rights Canada"],
            "seeds": [
                "Canada has a legal and moral obligation to implement all 94 Truth and Reconciliation Commission Calls to Action.",
                "Residential school survivors and their descendants are owed meaningful reparations, not only formal apologies.",
                "Canada's recent immigration levels have exceeded what housing and public service infrastructure can support.",
                "Anti-Asian and anti-Muslim racism in Canada is a serious and ongoing problem that requires active and funded policy responses.",
                "French-English bilingualism is a genuine institutional strength of Canada that should be actively promoted, not merely preserved.",
                "Indigenous nations should have genuine self-determination and jurisdiction over lands and resources within their traditional territories.",
                "Canada should create a dedicated urban Indigenous housing programme, recognising that more than 60% of Indigenous people now live in cities.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Canada: Universities, trades, and learning for a changing economy",
            "description": "Student debt, the skilled trades shortage, and whether Canadian education serves everyone equitably.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access and system design** — tuition levels, apprenticeships, and provincial jurisdiction. "
                "Further reading (optional) — Statistics Canada university tuition data, "
                "SODES skilled trades shortage research, "
                "PBO student loan analysis, Canada School Nutrition Programme advocacy."
            ),
            "article_keywords": ["Canada university tuition debt federal transfers", "skilled trades shortage Canada apprenticeship", "Canada student loan forgiveness expansion", "French immersion universal access Canada", "Indigenous language education federal funding"],
            "seeds": [
                "University tuition in Canada is too high and should be significantly reduced through increased federal transfers.",
                "Skilled trades are structurally underfunded and undervalued in Canada — this requires urgent policy change.",
                "Federal student loan forgiveness programmes should be substantially expanded, particularly for students from lower-income backgrounds.",
                "French immersion access should be universal across English Canada, not dependent on geography or lottery.",
                "Indigenous language education should be fully funded by the federal government as a core element of reconciliation.",
                "Canada needs a national school nutrition programme — it remains the only G7 country without one.",
                "Canada should establish a national post-secondary education quality framework to ensure credentials are recognised consistently across all provinces.",
            ],
        },
    ]


def _curriculum_sg() -> List[dict[str, Any]]:
    """Singapore-specific big questions grounded in Singaporean society and policy debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Singapore: Green Plan 2030, regional haze, and sustainability",
            "description": "Can Singapore lead on sustainability as a small, resource-dependent city-state?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Singapore's Green Plan 2030**, energy imports, and regional deforestation diplomacy. "
                "Further reading (optional) — National Climate Change Secretariat Singapore, "
                "EMA (Energy Market Authority) statistics, NEA carbon tax reviews, "
                "ASEAN Agreement on Transboundary Haze Pollution."
            ),
            "article_keywords": ["Singapore carbon tax level increase", "Singapore palm oil deforestation trade", "Singapore ASEAN climate leadership", "Singapore Green Plan 2030 ambition", "Singapore natural gas electricity alternative"],
            "seeds": [
                "Singapore's carbon tax is too low to drive meaningful business behaviour change and should be raised significantly above current levels.",
                "Singapore should refuse palm oil imports from suppliers that engage in deforestation, regardless of the trade costs.",
                "As a small but wealthy and well-connected state, Singapore should do more to lead climate diplomacy within ASEAN.",
                "Singapore's Green Plan 2030 targets are insufficiently ambitious given the country's wealth, technical capacity, and geographic vulnerability.",
                "Singapore should invest in regional clean electricity imports via undersea cables, even if this creates some supply dependency.",
                "Singapore should accelerate the reduction of natural gas in its electricity generation mix given its climate commitments.",
                "Singapore should seriously investigate nuclear power as part of its long-term clean energy mix, given its severe land constraints.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Singapore: Smart Nation, fintech, and digital governance",
            "description": "Is Singapore's Smart Nation programme the right model for digital government, and what are the trade-offs?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Smart Nation, the PDPA, fintech regulation, and surveillance trade-offs**. "
                "Further reading (optional) — Smart Nation and Digital Government Office reports, "
                "PDPC (Personal Data Protection Commission) enforcement data, "
                "MAS (Monetary Authority of Singapore) fintech frameworks, GovTech annual reports."
            ),
            "article_keywords": ["Singapore Smart Nation data privacy", "Singapore fintech regulatory sandbox MAS", "Singapore PDPA privacy GDPR comparison", "facial recognition Singapore surveillance parliament", "Singpass digital identity expansion Singapore"],
            "seeds": [
                "Singapore's Smart Nation programme collects too much personal data and requires significantly stronger privacy protections and independent oversight.",
                "Singapore's fintech regulatory sandbox is a global model that effectively balances innovation with consumer protection.",
                "Singapore should enact stronger digital personal data protection legislation aligned with international GDPR-standard principles.",
                "Facial recognition technology in public spaces by government agencies should require parliamentary authorisation and sunset clauses.",
                "Singapore's Singpass digital identity system should be extended to more government and private services with appropriate consent frameworks.",
                "Singapore risks excessive dependence on US and Chinese tech companies for critical national digital infrastructure.",
                "Singapore should publish a national algorithmic register requiring public sector agencies to disclose AI systems used in decisions affecting citizens.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Singapore: HDB, foreign workers, and the Singapore social compact",
            "description": "Housing affordability, foreign labour policy, and whether Singapore's growth model still works for everyone.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **structural policy** — HDB affordability, foreign worker levies, the CPF system, and progressive taxation. "
                "Further reading (optional) — HDB annual reports, MOM (Ministry of Manpower) labour statistics, "
                "CPF Board data, Singstat income distribution, Budget speeches."
            ),
            "article_keywords": ["HDB Singapore affordability young buyers", "Singapore foreign workers wage competition", "CPF retirement savings adequacy Singapore", "Singapore progressive tax wealth inequality", "Singapore cost of living inequality"],
            "seeds": [
                "HDB flats have become too expensive for young Singaporeans entering the property market for the first time.",
                "Singapore relies too heavily on low-wage foreign workers in ways that suppress wages and conditions for Singaporean workers.",
                "The CPF system is a strong model for retirement savings that should be strengthened rather than dismantled.",
                "Singapore needs a more progressive tax structure in which the wealthiest contribute proportionally more.",
                "Singapore's inequality, while lower than in many comparable cities, remains high relative to its level of human development.",
                "The government should more actively regulate cost-of-living pressures, not only manage them through targeted subsidies.",
                "Singapore should introduce a property gains tax to reduce speculative investment in HDB resale and private residential property.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Singapore: MediShield Life, eldercare, and an aging population",
            "description": "Can Singapore's 3M health financing model sustain an aging society at scale?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Medisave, MediShield Life, CareShield Life, and long-term care access**. "
                "Further reading (optional) — MOH (Ministry of Health Singapore) annual reports, "
                "AIC (Agency for Integrated Care) eldercare data, "
                "IMH (Institute of Mental Health) mental health surveys, Lien Foundation eldercare research."
            ),
            "article_keywords": ["MediShield Life premiums income affordability", "Singapore eldercare public investment ageing", "Singapore mental health funding stigma", "Singapore 3M healthcare sustainability", "hospital waiting times Singapore public beds"],
            "seeds": [
                "MediShield Life premiums are too high for lower- and middle-income Singaporeans and should be more heavily subsidised.",
                "Singapore needs a substantially larger public investment in eldercare as the population ages faster than the financing system can support.",
                "Mental health services in Singapore are underfunded and carry too much social stigma — both must change through active policy.",
                "Singapore's 3M (Medisave, MediShield, Medifund) framework is sound in principle but requires significant updating for an aging society.",
                "Long hospital waiting times indicate that Singapore needs more public hospital beds and clinical staff.",
                "Caregivers — disproportionately women — should receive direct financial support from the state for the economic value of their work.",
                "Singapore should introduce mandatory basic mental health screening in primary care as part of routine annual health checks.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Singapore: Regional security and navigating great-power rivalry",
            "description": "How should Singapore manage US-China competition while maintaining its strategic autonomy?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **Singapore's strategic position and defence policy**. "
                "Further reading (optional) — IISS military balance, RSIS Singapore security analyses, "
                "FPDA Treaty documentation, Singapore MINDEF defence white paper."
            ),
            "article_keywords": ["Singapore US China rivalry strategic autonomy", "Singapore national service conscription", "Singapore cybersecurity defence investment", "Five Power Defence Arrangements FPDA", "Singapore ASEAN dialogue US China mediation"],
            "seeds": [
                "Singapore should continue its policy of not formally taking sides between the US and China even under increasing bilateral pressure.",
                "National Service (conscription) remains essential to Singapore's deterrence posture and should be maintained.",
                "Singapore should invest more in cybersecurity and non-military security capabilities given the nature of contemporary threats.",
                "The Five Power Defence Arrangements remain a relevant framework for Singapore's regional security.",
                "Singapore's defence spending is appropriate to its security environment and strategic requirements.",
                "Singapore should play a more active role in facilitating dialogue between the US and China in Southeast Asia.",
                "Singapore should develop a comprehensive national cybersecurity strategy with mandatory incident reporting for critical infrastructure operators.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Singapore: The GRC system, press freedom, and political openness",
            "description": "Is Singapore's political system becoming more open, and what reforms would strengthen democratic accountability?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** about Singapore's political structures. "
                "Further reading (optional) — Singapore Elections Department data, "
                "RSF Press Freedom Index, Freedom House Singapore assessment, "
                "Parliamentary Hansard, ISA (Internal Security Act) historical usage data."
            ),
            "article_keywords": ["GRC group representation constituency reform", "Singapore press freedom ranking RSF", "Singapore Internal Security Act ISA repeal", "Workers Party parliament accountability Singapore", "Singapore Freedom of Information Act transparency"],
            "seeds": [
                "The Group Representation Constituency (GRC) system should be reformed or abolished — its effect on electoral competition warrants independent review.",
                "Singapore's press freedom ranking is too low for a country of its wealth and development — this represents a governance deficit.",
                "The Internal Security Act should be repealed — indefinite detention without trial has no place in a modern constitutional state.",
                "A stronger political opposition in parliament would make Singapore's government more accountable and improve policy outcomes.",
                "Defamation laws and POFMA should not be used to restrict legitimate political criticism or journalism.",
                "Singapore needs a Freedom of Information Act to improve government transparency and civic engagement.",
                "Singapore should hold a national civic conversation on democratic reform, independently chaired, before the next general election.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Singapore: Race harmony, foreign talent, and Singaporean identity",
            "description": "The CMIO framework, foreign talent policy, and what Singaporean identity means in a diverse society.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design**, not on individuals' backgrounds. "
                "Further reading (optional) — NUS sociology research on race in Singapore, "
                "MOM fair employment practices reports, MSF (Ministry of Social and Family Development) data, "
                "IPS (Institute of Policy Studies) social cohesion surveys."
            ),
            "article_keywords": ["Singapore CMIO race framework reform", "Section 377A repeal Singapore LGBTQ", "Singapore foreign talent Singaporeans employment", "Malay Indian discrimination employment Singapore", "Singapore permanent residency citizenship pathways"],
            "seeds": [
                "Singapore's government-defined CMIO (Chinese/Malay/Indian/Other) racial framework is increasingly outdated and should be reformed.",
                "The repeal of Section 377A was the right decision for an inclusive and modern Singapore.",
                "Foreign talent in Singapore has made an essential contribution to its success and should not be characterised as a threat to Singaporeans.",
                "More needs to be done to address persistent discrimination against Malay and Indian Singaporeans in employment.",
                "Singapore's social cohesion is a genuine asset that requires ongoing active policy investment.",
                "Singapore should make it easier for long-term residents who have contributed to the country to access permanent residency and citizenship.",
                "Singapore should introduce a national eldercare leave entitlement allowing workers to take paid leave to care for aging family members.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Singapore: PSLE, SkillsFuture, and the tuition arms race",
            "description": "Is Singapore's education system breeding excellence or anxiety, and is SkillsFuture working?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **PSLE reform, tuition industry, SkillsFuture effectiveness, and what education is for**. "
                "Further reading (optional) — MOE (Ministry of Education) Singapore PSLE reform papers, "
                "SkillsFuture Council reports, IPS education research, "
                "PISA Singapore data, Lien Foundation education surveys."
            ),
            "article_keywords": ["PSLE pressure 12 year old Singapore reform", "private tuition industry inequality Singapore regulate", "SkillsFuture credits redesign effectiveness", "Singapore academic achievement character skills balance", "Singapore university expansion knowledge economy"],
            "seeds": [
                "The pressure of the PSLE on 12-year-olds is causing serious and measurable harm to children's wellbeing that outweighs the benefits of early selection.",
                "The private tuition industry widens educational inequality and should be substantially regulated.",
                "SkillsFuture credits have not achieved sufficient impact and require a fundamental programme redesign.",
                "Singapore's school system still places excessive emphasis on academic achievement to the detriment of character development and broader skills.",
                "University places should be substantially expanded given Singapore's knowledge-economy needs.",
                "Schools should teach financial literacy and civic education as core subjects from secondary school.",
                "Singapore should pilot portfolio-based university admissions as an alternative to exam-only selection for arts and social science programmes.",
            ],
        },
    ]


def _curriculum_jp() -> List[dict[str, Any]]:
    """Japan-specific big questions grounded in Japanese political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Japan: Nuclear restarts, coal, and the path to carbon neutrality",
            "description": "After Fukushima, can Japan build a credible path to 2050 carbon neutrality?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Japanese energy choices** — nuclear restarts, coal dependency, and the Green Transformation (GX) strategy. "
                "Further reading (optional) — Agency for Natural Resources and Energy (ENECHO) data, "
                "Japan's GX Promotion Act, Ministry of Environment climate policy, "
                "ISEP (Institute for Sustainable Energy Policies) research."
            ),
            "article_keywords": ["Japan nuclear restart decarbonisation", "Japan coal power new construction climate", "Japan offshore wind investment manufacturing", "Japan 2050 carbon neutrality GX policy", "Japan Fukushima nuclear risk assessment"],
            "seeds": [
                "Japan was right to restart nuclear power plants as part of its decarbonisation strategy — the climate case outweighs the safety concerns.",
                "Japan's continued construction and planning of new coal power plants is incompatible with its 2050 carbon neutrality commitment.",
                "Japan should invest in offshore wind at a scale comparable to its investment in automotive manufacturing.",
                "Japan's 2050 carbon neutrality target requires energy policies far more ambitious than those currently in place.",
                "The Fukushima disaster should not prevent a rational, evidence-based reassessment of nuclear power's role in Japan's energy mix.",
                "Japan's island geography gives it substantial renewable energy potential — tidal, wave, and geothermal — that is being underexploited.",
                "Japan should set a more ambitious 2030 emissions reduction target aligned with a 1.5°C pathway, not only its current nationally determined contribution.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Japan: AI strategy, robotics, and digital transformation",
            "description": "Can Japan lead in AI and robotics while addressing its well-documented digital government failures?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Japan's AI strategy**, the My Number digital ID system, and the Digital Agency's reform programme. "
                "Further reading (optional) — Japan AI Strategy 2022, Digital Agency annual reports, "
                "Ministry of Economy, Trade and Industry (METI) digital transformation analyses, "
                "JEITA semiconductor reports."
            ),
            "article_keywords": ["Japan TSMC semiconductor investment strategic", "Japan My Number digital ID reform", "Japan government IT systems digital agency", "Japan robotics AI manufacturing automation", "Japan data protection Act APPI reform"],
            "seeds": [
                "Japan's investment in attracting TSMC semiconductor production strengthens its strategic position in the global chip supply chain significantly.",
                "Japan's My Number digital identity system should be accelerated, with stronger privacy protections, to enable modern digital public services.",
                "Japan needs to fundamentally overhaul its government IT systems, which lag behind other advanced economies by decades.",
                "Japan's strength in robotics puts it in a strong position to lead on AI-driven manufacturing automation.",
                "Japan should adopt personal data protection standards fully aligned with international best practice to participate effectively in global digital trade.",
                "Japan's tech sector needs more inward migration to address severe skill shortages, particularly in software engineering.",
                "Japan should develop a comprehensive data governance framework governing how AI companies can use data generated by Japanese citizens.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Japan: Deflation, wages, and the economic model",
            "description": "Japan's lost decades, wage stagnation, women's labour force participation, and whether structural reform is finally happening.",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Japanese economic structure** — wage growth, women's participation, and corporate governance reform. "
                "Further reading (optional) — Bank of Japan monetary policy assessments, "
                "Ministry of Health, Labour and Welfare wage statistics, "
                "JPX (Tokyo Stock Exchange) corporate governance reform guidance, Cabinet Office gender equality data."
            ),
            "article_keywords": ["Japan corporate cash holdings investment shareholder", "Japan women workforce participation structural barriers", "Japan minimum wage 1500 yen deflation", "Abenomics assessment structural reform", "Japan seishain regular employment inequality"],
            "seeds": [
                "Japan's corporations hold excessive cash reserves and should be required to invest them or return them to shareholders.",
                "Japanese women's labour force participation is structurally constrained by discriminatory workplace norms that require legal reform.",
                "Japan's minimum wage should be raised to ¥1,500 per hour nationally to address chronic wage stagnation.",
                "Abenomics failed to address the structural causes of Japan's economic stagnation despite its monetary innovation.",
                "Japan needs significant corporate governance reform to make its major companies internationally competitive.",
                "Japan's dual labour market — privileged regular employees (seishain) alongside precarious non-regular workers — entrenches deep inequality.",
                "Japan should allow more flexible working arrangements and shorten the standard working week to improve productivity and work-life balance.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Japan: Universal health insurance, aging, and end-of-life care",
            "description": "How can Japan sustain its world-class healthcare system as it ages faster than anywhere else on earth?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **Japan's universal health insurance, demographic pressure, and mental health**. "
                "Further reading (optional) — Ministry of Health, Labour and Welfare healthcare data, "
                "OECD Health at a Glance Japan, Japan Medical Association surveys, "
                "National Institute of Population and Social Security Research projections."
            ),
            "article_keywords": ["Japan universal health insurance sustainability", "Japan doctor nurse shortage aging", "Japan mental health stigma underfunding", "Japan palliative end-of-life care access", "Japan foreign healthcare workers immigration"],
            "seeds": [
                "Japan's universal health insurance system is one of its greatest social achievements and must be protected from cost-cutting.",
                "Japan needs to train and retain significantly more doctors and nurses to meet the healthcare demands of its aging population.",
                "Japan's mental health system is underfunded and highly stigmatised — both problems must be addressed through sustained policy.",
                "Japan should expand access to quality palliative care and end-of-life support outside of hospital settings.",
                "Healthcare insurance premiums for Japan's aging population should be more substantially cross-subsidised from general income taxation.",
                "Japan should accept significantly more foreign healthcare workers, with appropriate training and language support, to address its severe workforce shortage.",
                "Japan should establish a national dementia care strategy with adequate public funding for community-based care services.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Japan: Article 9, Taiwan, and Japanese rearmament",
            "description": "Should Japan formally revise Article 9 of its constitution and assume greater regional defence responsibilities?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **Japan's security posture, Article 9 of the constitution, and regional alliances**. "
                "Further reading (optional) — Japan's National Security Strategy (2022), "
                "CSIS Pacific Forum strategic assessments, Quad joint statements, "
                "Ministry of Defence (Japan) defence white papers."
            ),
            "article_keywords": ["Japan Article 9 constitution revision defence", "Japan defence spending 2 percent GDP", "Japan Taiwan Strait security commitment", "Quad Japan India Australia security", "Japan South Korea defence cooperation history"],
            "seeds": [
                "Japan should formally revise Article 9 of its constitution to reflect its actual and growing defence posture.",
                "Japan doubling defence spending to 2% of GDP is a necessary and overdue response to North Korean and Chinese military developments.",
                "Japan should make clearer security commitments regarding Taiwan given its strategic and economic significance.",
                "The Quad (US, Japan, India, Australia) is an important counterbalance to Chinese military expansion in the Indo-Pacific.",
                "Japan's pacifist tradition, even if constitutionally revised, remains an important part of its global diplomatic identity.",
                "Japan should develop stronger bilateral defence cooperation with South Korea despite unresolved historical tensions.",
                "Japan should formally end the longstanding ban on exporting lethal weapons to allies as part of its updated security posture.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Japan: LDP dominance, women in parliament, and political reform",
            "description": "One-party dominance, political funding scandals, and Japan's democratic deficit.",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **institutional design questions** about Japanese democracy. "
                "Further reading (optional) — IPU Women in Parliament data (Japan), "
                "Political Funds Control Act enforcement data, Electoral Integrity Project, "
                "Cabinet Legislation Bureau constitutional interpretations."
            ),
            "article_keywords": ["LDP Japan dominance accountability democratic", "women parliament Japan IPU ranking", "Nippon Kaigi religious nationalism LDP", "Japan rural urban vote weight malapportionment", "Japan political funding seiji shikin transparency"],
            "seeds": [
                "Japan's near-permanent LDP dominance weakens democratic accountability and produces policy capture by narrow interests.",
                "Japan's proportion of women in parliament is among the lowest in the OECD and requires active legislative intervention to change.",
                "The close relationship between elements of the LDP and organisations advocating nationalist constitutional revision requires public scrutiny.",
                "Japan's electoral system creates significant rural-urban vote weight imbalances that the courts should correct.",
                "Japan's political funding system (seiji shikin kisei) requires comprehensive transparency reform after recent donation scandals.",
                "Japan should make it easier for citizens to use referendums to resolve constitutional questions.",
                "Japan should establish an independent anti-corruption agency with investigatory powers, given the repeated political funding scandals.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Japan: Immigration, the birth rate crisis, and social isolation",
            "description": "Japan's demographic emergency, its ambivalence about immigration, and the loneliness epidemic.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design** — immigration, childcare, and what Japan's future looks like. "
                "Further reading (optional) — National Institute of Population and Social Security Research demographic projections, "
                "Ministry of Internal Affairs hikikomori survey data, "
                "OECD fertility and childcare policy comparisons, Immigration Services Agency statistics."
            ),
            "article_keywords": ["Japan immigration permanent residence economic", "Japan childcare parental leave birth rate reform", "hikikomori social withdrawal government intervention Japan", "Japan dual nationality ban reform", "Japan same-sex marriage legal recognition"],
            "seeds": [
                "Japan must accept significantly more permanent immigration to sustain its economy and pension system.",
                "Japan's childcare and parental leave policies still do not enable women to have children and pursue careers on equal terms.",
                "Hikikomori (severe social withdrawal) and the loneliness epidemic require sustained government intervention and destigmatisation.",
                "Japan should allow dual nationality — the current prohibition imposes unnecessary economic and social costs.",
                "Discrimination against foreign residents and naturalised citizens must be actively combated through law and enforcement.",
                "Same-sex partnership rights should be legally recognised at the national level, rather than being left to individual municipalities.",
                "Japan should formally prohibit discrimination in employment on the basis of sexual orientation and gender identity at the national level.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Japan: Juken, entrance exam culture, and education reform",
            "description": "Is Japan's entrance exam-driven education system fit for a creative, innovative economy?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **system design** — entrance exam culture (juken), the kyōtsū tesuto, English education, and university reform. "
                "Further reading (optional) — MEXT (Ministry of Education, Culture, Sports, Science and Technology) education statistics, "
                "PISA Japan results, OECD Education at a Glance Japan, Benesse education research."
            ),
            "article_keywords": ["Japan juken entrance exam stress reform", "Japan English education reform fluency", "Japan university reform international ranking", "juku tutoring inequality Japan regulate", "Japan liberal arts critical thinking university"],
            "seeds": [
                "Japan's university entrance exam culture (juken) creates damaging levels of stress without producing better long-term learning outcomes.",
                "English language education in Japan must be fundamentally reformed — the current approach prioritises grammar over communicative competence.",
                "Japan's universities need significant reform in governance, internationalisation, and funding to become globally competitive.",
                "Juku (private tutoring schools) widen educational inequality and the exam system should be reformed so they are less necessary.",
                "Japan needs more liberal arts education that builds critical thinking and adaptability, alongside technical specialisation.",
                "Japanese schools should actively teach students the full history of the country's actions in the Asia-Pacific war, based on historical evidence.",
                "Japan should make English medium instruction available in all national universities for at least 20% of degree programmes.",
            ],
        },
    ]


def _curriculum_cn() -> List[dict[str, Any]]:
    """Global big questions framed for international audiences, with particular relevance to Asia-Pacific and China-related debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions: China, Asia, and global climate responsibility",
            "description": "How should the world's largest emitter balance development goals with climate commitments?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **global climate choices** where China's decisions have major international consequences. "
                "Further reading (optional) — Global Carbon Project, IPCC AR6 Common But Differentiated Responsibilities principle, "
                "IEA China energy outlook, Climate Action Tracker assessments."
            ),
            "article_keywords": ["China 2060 carbon neutrality commitment credibility", "Belt Road Initiative coal overseas financing", "historical emissions responsibility developed developing", "China renewable energy capacity growth", "US China climate cooperation competition"],
            "seeds": [
                "China's 2060 carbon neutrality commitment is meaningful but requires substantially more ambitious near-term policies to be credible.",
                "China's Belt and Road Initiative must stop financing overseas coal power plants — the climate cost cannot be offset by other investments.",
                "Developed countries bear a greater historical responsibility for cumulative atmospheric carbon than rapidly industrialising nations.",
                "China's expansion of solar and wind capacity is one of the most consequential developments in global climate action.",
                "Developing countries should not be pressured to decarbonise at the same pace as wealthy nations that industrialised over two centuries.",
                "Climate change cooperation between the US and China should be insulated from other elements of strategic rivalry.",
                "China's domestic coal capacity must begin declining significantly before 2035 if its carbon neutrality pledge is to be credible.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions: AI governance, data sovereignty, and the global tech order",
            "description": "How should the world govern artificial intelligence and protect digital rights across different political systems?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **global AI governance choices** and competing regulatory models. "
                "Further reading (optional) — UN Advisory Body on AI (2024), Bletchley AI Safety Declaration, "
                "GPAI (Global Partnership on AI), EU AI Act, "
                "OECD AI Principles."
            ),
            "article_keywords": ["data localisation sovereignty international", "AI explainability accountability rights", "UN AI governance treaty process", "US China AI decoupling security", "open source AI monopoly prevention global"],
            "seeds": [
                "Countries should have the right to require that citizens' data is stored and processed domestically — data sovereignty is a legitimate policy goal.",
                "Artificial intelligence systems that make decisions affecting individuals' rights must be explainable and subject to meaningful appeal.",
                "Global AI safety standards should be agreed through a UN-level multilateral process, not set unilaterally by any single country or trading bloc.",
                "Technology decoupling between the US and China makes it harder to coordinate on shared AI safety risks that affect all countries.",
                "Open-source AI development benefits all countries by preventing technological monopolies from forming around a small number of powerful actors.",
                "International cooperation on AI safety research should continue regardless of geopolitical tensions between major powers.",
                "All countries should establish independent national AI safety bodies with the authority to evaluate and pause high-risk AI deployments.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions: Trade, development, and global economic fairness",
            "description": "Is the global economic order fair to developing countries, and how should it be reformed?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **trade rules, development finance, and global economic equity**. "
                "Further reading (optional) — WTO dispute settlement system, IMF governance reforms, "
                "World Bank debt sustainability framework, UNCTAD trade development reports."
            ),
            "article_keywords": ["WTO reform developing countries fairness", "Belt Road debt sustainability protection", "US China trade tariffs consumer cost", "infant industry protection developing countries", "IMF World Bank governance reform developing"],
            "seeds": [
                "The WTO's rules need fundamental reform to better serve the interests of developing countries, not only established trading powers.",
                "Belt and Road Initiative loan agreements should include stronger debt sustainability protections for recipient countries.",
                "Trade tariffs between the US and China are ultimately borne by ordinary consumers and businesses in both countries.",
                "Developing countries should retain the right to protect domestic industries while they build the capacity to compete internationally.",
                "Over-reliance on any single country for critical supply chains is a systemic economic and security risk that all nations should reduce.",
                "International financial institutions like the IMF and World Bank should give substantially more decision-making weight to developing nations.",
                "International development finance for infrastructure should be coordinated through multilateral development banks rather than bilateral lending arrangements.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions: Global health, pandemic lessons, and health equity",
            "description": "What did the world learn from COVID-19, and how must global health architecture change?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **global health preparedness, vaccine equity, and international cooperation**. "
                "Further reading (optional) — Independent Panel for Pandemic Preparedness and Response (IPPR) report (2021), "
                "WHO Pandemic Accord negotiations, Lancet COVID-19 Commission, "
                "MSF vaccine equity campaign."
            ),
            "article_keywords": ["COVID vaccine patent waiver TRIPS", "WHO pandemic treaty stronger powers", "vaccine nationalism preventable deaths COVID", "pandemic preparedness fund permanent financing", "universal health coverage global low income"],
            "seeds": [
                "Vaccine patents should be waived during pandemics so that all countries can manufacture doses without licensing barriers.",
                "The WHO needs substantially stronger powers to investigate outbreaks quickly, without member state obstruction.",
                "Rich countries' vaccine nationalism during COVID caused preventable deaths and must not be repeated in future pandemics.",
                "Pandemic preparedness should be funded by a permanent treaty-based international mechanism, not unpredictable discretionary contributions.",
                "Traditional and complementary medicine claims should be subject to the same evidence standards as other medical treatments.",
                "Universal health coverage is both achievable and necessary at all income levels — the evidence that it improves health outcomes is strong.",
                "All countries should ratify and implement the Pandemic Accord currently being negotiated under WHO auspices.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions: Asia-Pacific security, Taiwan, and the rules-based order",
            "description": "Can the world avoid great-power conflict and build a more stable international system?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are normative questions about **peace, sovereignty, and international law norms**. "
                "Further reading (optional) — UNCLOS, UN Charter Article 2(4), "
                "IISS Asia-Pacific security assessments, Carnegie Endowment for International Peace, "
                "SIPRI conflict data."
            ),
            "article_keywords": ["US China dialogue prevent escalation Taiwan", "UN Charter territorial integrity force prohibition", "economic interdependence war prevention research", "Asia Pacific multilateral security framework", "sanctions diplomacy geopolitical disputes effectiveness"],
            "seeds": [
                "Active dialogue and diplomacy between the US and China are essential to prevent accidental military escalation in the Asia-Pacific.",
                "The UN Charter's prohibition on changing borders or political status by force must apply equally to all states.",
                "Economic interdependence between major powers reduces but does not eliminate the risk of large-scale armed conflict.",
                "Regional security in the Asia-Pacific should be managed primarily through multilateral frameworks rather than bilateral arrangements.",
                "Broad economic sanctions are rarely effective tools for resolving geopolitical disputes and often harm civilian populations.",
                "Countries in territorial or political disputes should use international courts and arbitration rather than unilateral action.",
                "The five permanent members of the UN Security Council should voluntarily commit not to veto resolutions addressing mass atrocities.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions: International institutions, governance, and global cooperation",
            "description": "Are international institutions fit to address the world's greatest challenges?",
            "information_title": "How to read these statements",
            "information_body": (
                "These are **global governance questions** about international institutions, multilateralism, and legitimacy. "
                "Further reading (optional) — UN High-Level Advisory Board on Effective Multilateralism (2023), "
                "Dag Hammarskjöld Foundation, Freedom House global democracy data, "
                "Bertelsmann Transformation Index."
            ),
            "article_keywords": ["UN Security Council reform permanent membership", "international law compliance powerful states", "global challenges climate pandemic multilateralism", "International Court of Justice ICJ compliance", "multilateralism unilateralism effectiveness evidence"],
            "seeds": [
                "The UN Security Council's permanent membership should be reformed to reflect the current distribution of global power and population.",
                "International law is only effective when powerful states choose to follow it — this structural deficiency requires institutional reform.",
                "Global challenges like climate change and pandemics require stronger international institutions, not a retreat to national unilateralism.",
                "All countries, including powerful ones, should comply with International Court of Justice rulings.",
                "A just international order requires giving equal legal standing to all states, regardless of economic or military power.",
                "Multilateral institutions, despite their slowness and frustration, produce more durable outcomes than unilateral action by dominant powers.",
                "International organisations should be held to the same transparency and accountability standards they demand of member governments.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions: Migration, urbanisation, and social change in Asia",
            "description": "How rapidly urbanising societies manage diversity, inequality, mobility, and belonging.",
            "information_title": "How to read these statements",
            "information_body": (
                "Vote on **policy design** — urbanisation, social mobility, and what societies owe their members. "
                "Further reading (optional) — UN World Urbanization Prospects, World Bank GINI data, "
                "ILO migration statistics, OECD Social Mobility in East Asia report."
            ),
            "article_keywords": ["urbanisation economic development displacement", "social infrastructure cities parks libraries investment", "rural urban inequality Asia defining challenge", "internal migration rights equal treatment", "demographic decline family policy migration"],
            "seeds": [
                "Rapid urbanisation drives economic development but requires substantial public investment in social infrastructure to prevent social fragmentation.",
                "Cities should invest significantly more in social infrastructure — parks, libraries, community centres — not only transport and commercial development.",
                "Growing economic inequality between urban and rural areas is one of the defining social problems of the contemporary era.",
                "All people should have the right to move within their country and receive equal treatment regardless of origin.",
                "Social mobility in most countries is lower than public perception suggests and requires active, targeted policy intervention.",
                "Demographic decline is better addressed by improving conditions for families and workers than by restricting migration.",
                "All countries should ratify and implement the UN International Covenant on Economic, Social and Cultural Rights.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions: Education, opportunity, and preparing societies for the future",
            "description": "How can education systems reduce inequality and equip people for a rapidly changing world?",
            "information_title": "How to read these statements",
            "information_body": (
                "Focus on **access, system design, and what education is for** in a changing global economy. "
                "Further reading (optional) — UNESCO Education for All Global Monitoring Report, "
                "OECD PISA and Education at a Glance, "
                "World Bank human capital index, Brookings education research."
            ),
            "article_keywords": ["education intergenerational poverty reduction evidence", "high pressure exam system creativity innovation", "private tutoring inequality Korea China regulation", "early childhood education return on investment", "higher education public good funding model"],
            "seeds": [
                "Education is the most powerful policy tool for reducing intergenerational poverty and governments should fund it as a first-order priority.",
                "High-pressure examination systems do not produce the critical thinking and creative capacity that modern economies need.",
                "Private tutoring industries in high exam-pressure societies widen educational inequality and should be regulated.",
                "Access to quality early childhood education produces higher social returns than investment at secondary or tertiary level alone.",
                "Higher education should be primarily publicly funded as a social good — the evidence that graduate loan systems reduce access is strong.",
                "Schools should explicitly teach students how to evaluate information sources and identify disinformation.",
                "International student and academic exchange programmes should be expanded as a tool for building mutual understanding and reducing geopolitical risk.",
            ],
        },
    ]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_CURRICULUM_MAP = {
    "global": _curriculum_global,
    "uk":     _curriculum_uk,
    "us":     _curriculum_us,
    "nl":     _curriculum_nl,
    "ie":     _curriculum_ie,
    "de":     _curriculum_de,
    "fr":     _curriculum_fr,
    "ca":     _curriculum_ca,
    "sg":     _curriculum_sg,
    "jp":     _curriculum_jp,
    "cn":     _curriculum_cn,
}

if set(_CURRICULUM_MAP) != set(VALID_VARIANTS):
    raise RuntimeError(
        "_CURRICULUM_MAP keys must exactly match VARIANT_METADATA / VALID_VARIANTS "
        f"(curriculum={sorted(_CURRICULUM_MAP)}, metadata={sorted(VALID_VARIANTS)})"
    )


def get_curriculum(variant: str = "global") -> List[dict[str, Any]]:
    variant = (variant or "global").lower()
    fn = _CURRICULUM_MAP.get(variant, _curriculum_global)
    curriculum = fn()
    merge_reading_enrichment(curriculum, variant)
    return curriculum


# ---------------------------------------------------------------------------
# Slug / scope helpers — driven by VARIANT_METADATA
# ---------------------------------------------------------------------------

def _slug_for_variant(variant: str) -> str:
    meta = VARIANT_METADATA[variant]
    return (current_app.config.get(meta.config_env_key) or "").strip().lower() or meta.default_slug


def _scope_for_variant(variant: str) -> tuple[str, Optional[str]]:
    meta = VARIANT_METADATA[variant]
    return meta.geographic_scope, meta.country


def _display_name_for_variant(variant: str) -> str:
    return VARIANT_METADATA[variant].display_name


# ---------------------------------------------------------------------------
# Article attachment
# ---------------------------------------------------------------------------

def _attach_articles_for_discussion(discussion_id: int, keywords: List[str], country: Optional[str], limit: int = 3):
    if not keywords:
        return
    conditions = [NewsArticle.title.ilike(f"%{kw}%") for kw in keywords[:4]]
    q = (
        NewsArticle.query.join(NewsSource, NewsSource.id == NewsArticle.source_id)
        .filter(or_(*conditions))
        .filter(NewsSource.is_active.is_(True))
    )
    if country:
        q = q.filter(
            or_(
                NewsSource.country.ilike(country),
                NewsSource.country.is_(None),
            )
        )
    q = q.order_by(NewsSource.reputation_score.desc().nullslast(), NewsArticle.fetched_at.desc())
    articles = q.limit(limit * 3).all()
    seen: set[int] = set()
    added = 0
    for art in articles:
        if art.id in seen:
            continue
        exists = DiscussionSourceArticle.query.filter_by(
            discussion_id=discussion_id, article_id=art.id
        ).first()
        if exists:
            continue
        db.session.add(DiscussionSourceArticle(discussion_id=discussion_id, article_id=art.id))
        seen.add(art.id)
        added += 1
        if added >= limit:
            break


# ---------------------------------------------------------------------------
# Core seeder
# ---------------------------------------------------------------------------

def _pick_creator(creator_email: Optional[str]) -> User:
    if creator_email:
        u = User.query.filter_by(email=creator_email.strip()).first()
        if not u:
            raise ValueError(f"No user with email {creator_email!r}")
        return u
    u = User.query.filter_by(is_admin=True).order_by(User.id.asc()).first()
    if u:
        return u
    u = User.query.order_by(User.id.asc()).first()
    if not u:
        raise ValueError("No users in database; create a user first.")
    return u


def seed_guided_journey_programme(variant: str = "global", creator_email: Optional[str] = None) -> Programme:
    """
    Idempotent: creates the programme if missing; adds missing discussions per theme.
    Safe to re-run — will not delete any theme that already has votes.
    On discussions with zero votes, existing seed statements are replaced with the
    current curriculum so content can be updated by re-running the seeder.
    Each discussion receives exactly 7 seed statements to meet the minimum threshold
    for consensus analysis.
    """
    variant = (variant or "global").lower()
    if variant not in VALID_VARIANTS:
        raise ValueError(f"variant must be one of: {', '.join(sorted(VALID_VARIANTS))}")

    slug = _slug_for_variant(variant)
    gscope, country = _scope_for_variant(variant)
    curriculum = get_curriculum(variant)
    theme_names = [c["theme"] for c in curriculum]

    creator = _pick_creator(creator_email)
    programme = Programme.query.filter_by(slug=slug).first()
    if not programme:
        programme = Programme(
            slug=slug,
            name=_display_name_for_variant(variant),
            description=(
                "A guided journey through major civic questions — one theme at a time. "
                "Vote on concrete statements, then explore consensus and curated reading."
            ),
            creator_id=creator.id,
            company_profile_id=None,
            geographic_scope=gscope,
            country=country,
            themes=theme_names,
            phases=["Wave 1"],
            cohorts=[],
            visibility="public",
            status="active",
        )
        db.session.add(programme)
        db.session.flush()
    else:
        programme.themes = theme_names
        programme.geographic_scope = gscope
        programme.country = country

    phase = (programme.phases or ["Wave 1"])[0]

    for spec in curriculum:
        theme = spec["theme"]
        existing = (
            Discussion.query.filter_by(programme_id=programme.id, programme_theme=theme)
            .filter(Discussion.has_native_statements.is_(True))
            .first()
        )
        if existing:
            d = existing
            d.title = spec["title"]
            d.description = spec["description"]
            d.topic = spec["topic"]
            d.geographic_scope = gscope
            d.country = country or d.country
            d.information_title = spec.get("information_title")
            d.information_body = _normalize_information_body(spec.get("information_body"))
            d.programme_phase = phase
            d.information_links = list(spec.get("information_links", []))
        else:
            d = Discussion(
                title=spec["title"],
                description=spec["description"],
                topic=spec["topic"],
                geographic_scope=gscope,
                country=country,
                creator_id=creator.id,
                has_native_statements=True,
                embed_code=None,
                programme_id=programme.id,
                programme_theme=theme,
                programme_phase=phase,
                information_title=spec.get("information_title"),
                information_body=_normalize_information_body(spec.get("information_body")),
                information_links=list(spec.get("information_links", [])),
            )
            db.session.add(d)
            db.session.flush()

        has_any_votes = (
            db.session.query(StatementVote.id)
            .filter(StatementVote.discussion_id == d.id)
            .limit(1)
            .first()
        )
        if not has_any_votes:
            Statement.query.filter_by(discussion_id=d.id, is_seed=True).delete(synchronize_session=False)
            for content in spec["seeds"]:
                content = content.strip()
                if len(content) < 10:
                    continue
                db.session.add(
                    Statement(
                        discussion_id=d.id,
                        user_id=creator.id,
                        content=content[:500],
                        is_seed=True,
                        mod_status=1,
                        source="partner_provided",
                        seed_stance="neutral",
                    )
                )
        _attach_articles_for_discussion(d.id, spec.get("article_keywords") or [], country, limit=3)

    db.session.commit()
    try:
        from app.programmes.routes import invalidate_programme_summary_cache
        invalidate_programme_summary_cache(programme.id)
    except Exception:
        pass
    try:
        from app import cache
        cache.delete("homepage_journey_programmes")
    except Exception:
        pass
    return programme
