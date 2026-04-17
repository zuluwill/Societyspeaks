"""
Seed data for guided flagship programmes — one per major audience country.

Each variant has GENUINELY DISTINCT statements reflecting that country's specific
institutions, debates, and political context. The global variant covers universal
big questions; country variants anchor each theme in local reality.

Variant keys and slugs: app/programmes/journey_variants.py (add env keys in config.py when adding variants).

Run via:
  flask seed-guided-journey --all-variants
  flask seed-guided-journey --variant global
  flask seed-guided-journey --variant uk
  # … see journey_variants.VALID_VARIANTS
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
from app.programmes.journey_variants import VALID_VARIANTS, VARIANT_METADATA


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
            "description": "How should humanity respond to environmental limits and climate risk?",
            "information_title": "Before you vote",
            "information_body": "These statements are about **collective choices** — policy, technology, and fairness — not personal guilt.",
            "article_keywords": ["climate", "carbon", "energy", "COP"],
            "seeds": [
                "Rich countries should pay significantly more toward global climate adaptation than poorer nations.",
                "Nuclear power should be a major part of decarbonising electricity this decade.",
                "Governments should ban new fossil-fuel car sales sooner, even if it raises short-term costs.",
                "Carbon taxes are fairer than complex regulations for reducing emissions.",
                "Protecting biodiversity is as urgent as cutting greenhouse gases.",
                "Individual lifestyle change matters less than systemic policy change for the climate.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions: Artificial intelligence, automation, and governance",
            "description": "Who should control powerful AI systems, and what must be regulated?",
            "information_title": "Before you vote",
            "information_body": "Focus on **governance and trade-offs**: safety, innovation, jobs, and democratic oversight.",
            "article_keywords": ["artificial intelligence", "AI regulation", "automation", "tech policy"],
            "seeds": [
                "Advanced AI systems should require a government licence before wide public deployment.",
                "Open-source release of the largest AI models does more public good than harm.",
                "Companies building frontier AI should be legally liable for serious harms their systems cause.",
                "Automating jobs with AI is acceptable if redistribution and retraining are publicly funded.",
                "Democratic governments should slow AI deployment if safety is uncertain, even if rivals do not.",
                "Personal data should not be used to train general AI models without clear opt-in consent.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions: Prosperity, inequality, and the future of work",
            "description": "Taxation, markets, and who bears the costs of economic change.",
            "information_title": "Before you vote",
            "information_body": "These questions concern **systems**, not any one person's spending habits.",
            "article_keywords": ["economy", "inequality", "taxation", "workers rights"],
            "seeds": [
                "Wealth taxes on the very rich are a fair way to fund public services.",
                "A universal basic income is better than targeted benefits for reducing poverty.",
                "Stronger unions improve outcomes for most workers, not only their members.",
                "Free trade agreements should be rejected when they weaken labour or environmental standards.",
                "Housing costs are mainly a supply problem that upzoning and planning reform can fix.",
                "High inflation is a bigger long-term threat to society than high unemployment.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions: Health systems, prevention, and access",
            "description": "How societies should fund and prioritise care.",
            "information_title": "Before you vote",
            "information_body": "Vote on **public policy** angles — access, funding, prevention — not personal medical choices.",
            "article_keywords": ["healthcare", "public health", "health system", "mental health"],
            "seeds": [
                "Healthcare should be funded primarily through taxation rather than private insurance.",
                "Governments should restrict junk-food advertising to reduce obesity.",
                "Longer healthy life expectancy matters more as a policy goal than maximising GDP growth.",
                "Medical innovation should be incentivised even if it temporarily raises drug prices.",
                "Mental health services deserve equal funding to physical health services.",
                "Pandemic preparedness should be funded continuously, not only after emergencies begin.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions: War, intervention, and international security",
            "description": "When force is justified and how alliances should work.",
            "information_title": "Before you vote",
            "information_body": "These are **normative** questions about legitimacy and risk; reasonable people disagree sharply.",
            "article_keywords": ["NATO", "Ukraine", "war", "defence spending", "security"],
            "seeds": [
                "Military alliances like NATO reduce the overall risk of large-scale war.",
                "Humanitarian military intervention can be justified even without UN Security Council approval.",
                "Countries should spend more on defence given current geopolitical instability.",
                "Economic sanctions are preferable to military force for changing authoritarian state behaviour.",
                "Nuclear deterrence remains necessary for great-power peace in our lifetime.",
                "Neutral countries should still supply defensive aid when democracies are invaded.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions: Democracy, rights, and political institutions",
            "description": "Representation, limits on power, and civic trust.",
            "information_title": "Before you vote",
            "information_body": "Interpret statements as **design choices** for institutions, not party loyalty.",
            "article_keywords": ["democracy", "elections", "parliament", "rights", "institutions"],
            "seeds": [
                "Proportional representation is fairer than first-past-the-post for national elections.",
                "Strong judicial review is essential even when it slows majoritarian change.",
                "Social media platforms should be legally required to curb viral election misinformation.",
                "Term limits for heads of government strengthen democracy more than they weaken experience.",
                "Compulsory voting improves democratic legitimacy.",
                "Corporate lobbying should be much more tightly restricted than it is today.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions: Migration, identity, and social trust",
            "description": "Pluralism, borders, and what we owe each other.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy and ethics**; avoid interpreting statements as attacks on individuals.",
            "article_keywords": ["migration", "immigration", "refugees", "social cohesion"],
            "seeds": [
                "Economic migration should be easier than it is in most rich countries today.",
                "Refugees fleeing war should be protected even when host communities face housing pressure.",
                "Multiculturalism strengthens societies more than it fragments them.",
                "National identity still matters for democratic solidarity in large diverse states.",
                "Hate-speech laws should protect minorities even when they limit some political speech.",
                "Reducing inequality does more for social cohesion than restricting immigration.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions: Education, skills, and opportunity",
            "description": "What every generation should learn — and who pays.",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, curriculum, and funding models**.",
            "article_keywords": ["education", "schools", "university tuition", "vocational training"],
            "seeds": [
                "Higher education tuition should be largely publicly funded through general taxation.",
                "Standardised testing does more harm than good for student learning outcomes.",
                "Vocational pathways deserve equal prestige to academic university routes.",
                "National curricula should require climate literacy and digital skills for all students.",
                "Private schools widen inequality and should be phased down, not expanded.",
                "Teacher pay should rise significantly even if class sizes stay the same.",
            ],
        },
    ]


def _curriculum_uk() -> List[dict[str, Any]]:
    """UK-specific big questions anchored in British institutions and current debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for the UK: Energy, net zero, and environmental policy",
            "description": "Should Britain lead on climate action or prioritise energy security first?",
            "information_title": "Before you vote",
            "information_body": "These questions concern UK **policy choices** — North Sea licensing, heat pumps, planning — not individual habits.",
            "article_keywords": ["North Sea oil", "net zero", "heat pump", "UK climate", "energy security"],
            "seeds": [
                "The UK should not issue new North Sea oil and gas licences given our net-zero 2050 commitment.",
                "Heat pump grants should be large enough to make them the default choice for UK home heating.",
                "Planning rules should be relaxed to fast-track onshore wind farms in England.",
                "The UK's climate leadership is undermined when it expands Heathrow while cutting rail investment.",
                "British farmers should be paid to restore peatlands even when it reduces agricultural output.",
                "Net zero should not be delayed even if the transition raises household energy bills.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the UK: AI regulation, data, and digital governance",
            "description": "Can Britain lead on responsible AI without stifling its tech sector?",
            "information_title": "Before you vote",
            "information_body": "Consider the UK's **post-Brexit positioning** — autonomous regulator vs alignment with EU AI Act.",
            "article_keywords": ["UK AI regulation", "ARIA", "ICO", "Online Safety Act", "tech regulation"],
            "seeds": [
                "The UK should adopt binding AI safety rules aligned with the EU AI Act rather than a lighter-touch approach.",
                "ARIA's public investment in frontier AI research is a good use of taxpayer money.",
                "The Online Safety Act goes too far in restricting legal but harmful online content.",
                "Requiring social media age verification is worth the privacy trade-offs.",
                "UK data protection rules post-Brexit should remain as strong as the EU's GDPR.",
                "The government should use public procurement to favour UK-built AI tools over US alternatives.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the UK: Growth, inequality, and the cost of living",
            "description": "Stagnant wages, housing costs, and who should bear the burden of recovery.",
            "information_title": "Before you vote",
            "information_body": "These are questions about **economic design choices**, not individual budgeting.",
            "article_keywords": ["UK economy", "cost of living", "National Living Wage", "housing", "austerity"],
            "seeds": [
                "Austerity since 2010 has done more long-term damage to the UK economy than it saved.",
                "The National Living Wage should rise to £15 an hour within this parliament.",
                "Cutting inheritance tax is a lower priority than fixing the NHS and schools.",
                "The UK should rejoin the EU single market for goods to improve trade.",
                "London's dominance of the UK economy is a structural problem that needs active redistribution.",
                "Britain's housing crisis is primarily caused by the planning system, not land banking.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the UK: Saving the NHS",
            "description": "Waiting lists, funding models, and whether the NHS can survive without reform.",
            "information_title": "Before you vote",
            "information_body": "Focus on **NHS structure, funding, and access** — not personal health choices.",
            "article_keywords": ["NHS", "waiting lists", "social care", "NHS reform", "GP"],
            "seeds": [
                "The NHS should remain free at the point of use for everyone, funded by general taxation.",
                "NHS waiting lists should be cleared by expanding use of private providers paid by the state.",
                "Social care for the elderly should be fully funded by the state, not left to individuals.",
                "NHS staff pay has fallen so far behind that a major pay rise is justified even if it requires tax rises.",
                "GPs should offer same-day appointments as a right, funded by ending some elective hospital care.",
                "Patients should be able to pay to top up NHS care without losing their NHS entitlement.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the UK: Defence, NATO, and Britain's place in the world",
            "description": "Trident, Ukraine, and what post-Brexit Britain owes to international security.",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **force, alliances, and nuclear deterrence**.",
            "article_keywords": ["Trident", "NATO UK", "Ukraine UK", "UK defence spending", "AUKUS"],
            "seeds": [
                "The UK should renew Trident even though the cost could fund years of NHS investment.",
                "Britain should commit to spending 2.5% of GDP on defence as a floor, not a target.",
                "The UK has a special obligation to support Ukraine given its role in the Budapest Memorandum.",
                "AUKUS is a strategic mistake that alienates the EU and risks conflict with China.",
                "UK foreign aid should be restored to 0.7% of GNI as a legal obligation.",
                "Post-Brexit Britain punches below its weight diplomatically and needs to re-engage with Europe.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the UK: Parliament, voting, and constitutional reform",
            "description": "Lords reform, electoral systems, and the erosion of democratic norms.",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design** questions — not about any party's current position.",
            "article_keywords": ["House of Lords reform", "proportional representation UK", "Supreme Court", "UK constitution"],
            "seeds": [
                "First-past-the-post should be replaced with proportional representation for UK general elections.",
                "The House of Lords should be replaced by an elected second chamber.",
                "The Supreme Court's power to strike down government actions should be strengthened, not weakened.",
                "Prime Ministers should be limited to two terms in office.",
                "Voter ID requirements do more harm to legitimate voting than they prevent fraud.",
                "Recall elections for MPs should be triggered by a public petition, not just a parliamentary vote.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the UK: Immigration, identity, and community",
            "description": "What the UK owes newcomers, and what it takes to build a cohesive society.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design**, not individual people's choices or worth.",
            "article_keywords": ["UK immigration", "asylum seekers UK", "Channel crossings", "integration UK"],
            "seeds": [
                "The UK's target of reducing net migration to the tens of thousands is neither achievable nor desirable.",
                "Asylum seekers should be allowed to work while their claims are assessed.",
                "Offshore processing of asylum claims, as under the Rwanda scheme, is ethically unacceptable.",
                "The UK's diversity is a strength that benefits everyone, not just recent arrivals.",
                "Communities facing rapid demographic change should receive additional public investment.",
                "British citizenship tests should assess civic values, not historical trivia.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the UK: Schools, universities, and preparing for work",
            "description": "RAAC schools, tuition fees, and whether the system delivers for everyone.",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, funding models, and what we teach** — not individual school performance.",
            "article_keywords": ["UK education", "university tuition fees", "apprenticeships UK", "OFSTED", "grammar schools"],
            "seeds": [
                "University tuition fees should be abolished and higher education funded by general taxation.",
                "Grammar schools should be phased out because they entrench advantage rather than expand it.",
                "Apprenticeships should be funded at the same per-student level as university places.",
                "OFSTED inspection is too high-stakes and should be replaced with school improvement support.",
                "Teachers are significantly underpaid relative to other graduate professions in the UK.",
                "Religious schools that select pupils on faith grounds should not receive state funding.",
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
            "description": "Can the US lead on climate while protecting jobs and energy independence?",
            "information_title": "Before you vote",
            "information_body": "Focus on **federal policy choices** — the IRA, EPA authority, fossil fuels — not personal choices.",
            "article_keywords": ["US climate policy", "Inflation Reduction Act", "EPA", "fracking", "fossil fuels USA"],
            "seeds": [
                "The Inflation Reduction Act's climate investments should be protected even if other spending is cut.",
                "The EPA should have broad authority to regulate carbon emissions without additional Congressional action.",
                "The US should rejoin and fully fund international climate agreements.",
                "New federal permits for LNG export terminals should be blocked given the climate emergency.",
                "Agricultural subsidies should shift toward regenerative farming and away from commodity monocultures.",
                "States should not be allowed to block federal clean energy infrastructure on their territory.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the US: Big Tech, AI, and the digital economy",
            "description": "Section 230, antitrust, and whether Washington can govern Silicon Valley.",
            "information_title": "Before you vote",
            "information_body": "Focus on **federal regulation and trade-offs** between innovation, safety, and democratic accountability.",
            "article_keywords": ["Section 230", "Big Tech antitrust", "AI safety USA", "FTC tech", "social media regulation"],
            "seeds": [
                "Section 230 liability protections for social media platforms should be significantly narrowed.",
                "Breaking up Amazon, Google, or Meta would improve competition and benefit consumers.",
                "The US needs a federal AI safety agency with power to halt dangerous deployments.",
                "AI companies should be required to pay workers displaced by automation a transition fund.",
                "Americans' data should not be sold to foreign governments or companies without consent.",
                "The US should lead on setting global AI governance standards rather than defer to the EU.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the US: The economy, taxes, and who gets ahead",
            "description": "Minimum wage, student debt, and whether the American Dream still works.",
            "information_title": "Before you vote",
            "information_body": "These are **systemic policy questions** — not about individual hard work or personal responsibility.",
            "article_keywords": ["federal minimum wage", "student debt forgiveness", "US inequality", "carried interest", "tax reform USA"],
            "seeds": [
                "The federal minimum wage should be raised to $15 an hour and indexed to inflation.",
                "Student loan debt should be broadly cancelled as a matter of economic and racial justice.",
                "The carried interest loophole for hedge funds should be closed immediately.",
                "The United States needs a wealth tax on fortunes above $50 million.",
                "Right-to-work laws that weaken unions should be repealed at the federal level.",
                "US trade deals should include enforceable labour and environmental standards for trading partners.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the US: Healthcare, insurance, and who gets covered",
            "description": "Medicare, the ACA, and why the US spends more and gets less than peers.",
            "information_title": "Before you vote",
            "information_body": "Focus on **coverage, cost, and system design** — not individual health choices.",
            "article_keywords": ["Medicare for All", "ACA Obamacare", "insulin prices USA", "US healthcare cost", "Medicaid"],
            "seeds": [
                "The US should move to a single-payer Medicare for All system to cover everyone.",
                "Drug prices should be capped by the federal government as they are in most other rich countries.",
                "Medicaid expansion should be mandatory for all states, not optional.",
                "Mental health parity laws should be strictly enforced so insurers cannot deny mental health claims.",
                "Employer-based health insurance ties workers to jobs in a way that harms economic mobility.",
                "Reproductive healthcare, including abortion, should be covered by all federally funded health plans.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the US: Military, alliances, and America's global role",
            "description": "NATO burden-sharing, Pentagon spending, and whether US power stabilises the world.",
            "information_title": "Before you vote",
            "information_body": "These are questions about the **costs and legitimacy of American military power**.",
            "article_keywords": ["NATO USA", "Pentagon budget", "Ukraine US aid", "US military spending", "isolationism"],
            "seeds": [
                "The US should reduce the Pentagon budget and reinvest in diplomacy and foreign aid.",
                "America has a binding moral obligation to continue supporting Ukraine militarily.",
                "NATO allies that do not meet the 2% GDP defence spending target should face reduced US commitments.",
                "The US should maintain a significant military presence in Europe for the foreseeable future.",
                "Congress should reassert its war powers and require authorisation for any new military action.",
                "US arms sales to authoritarian governments undermine American values and should be restricted.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the US: Democracy, voting rights, and institutional reform",
            "description": "The Electoral College, the filibuster, and whether US democracy needs reform.",
            "information_title": "Before you vote",
            "information_body": "Interpret these as **structural design questions** — not partisan claims.",
            "article_keywords": ["Electoral College reform", "filibuster", "Supreme Court term limits", "gerrymandering", "voting rights USA"],
            "seeds": [
                "The Electoral College should be replaced by a national popular vote for the presidency.",
                "The Senate filibuster should be eliminated so majority rule can function in Congress.",
                "Supreme Court justices should serve 18-year terms with staggered appointments.",
                "Independent redistricting commissions should be required in every state to end gerrymandering.",
                "Federal automatic voter registration should be the law to maximise participation.",
                "The Citizens United decision should be overturned by constitutional amendment.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the US: Immigration, identity, and the American promise",
            "description": "Border policy, DACA, and what it means to be American today.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design**, not the character or worth of individuals.",
            "article_keywords": ["US immigration reform", "DACA", "border policy USA", "affirmative action", "gun control"],
            "seeds": [
                "DACA recipients should be given a clear path to permanent legal status and citizenship.",
                "Undocumented immigrants who have lived in the US for more than five years should have a pathway to residency.",
                "Race-conscious college admissions policies can be justified as reparative tools for historical exclusion.",
                "Federal universal background check legislation for all gun purchases should be passed.",
                "The US should accept more refugees and asylum seekers — the current caps are too low.",
                "Police reform, not defunding, is the right response to systemic racial disparities in law enforcement.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the US: Schools, colleges, and the skills gap",
            "description": "School choice, student debt, and whether American education serves everyone.",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, funding equity, and what is taught** — not individual school or college performance.",
            "article_keywords": ["school choice USA", "student debt USA", "teacher pay USA", "standardised tests USA"],
            "seeds": [
                "Public school funding should not vary by local property tax revenues — it creates unjust inequality.",
                "Voucher programmes for private schools divert needed funding from the public school system.",
                "The SAT and ACT should be dropped from college admissions as they disadvantage lower-income students.",
                "Trade and vocational programmes should be funded at the same level as college-prep curricula.",
                "Teacher pay should be set nationally at a competitive professional rate, not left to local districts.",
                "Critical race history should be taught in K-12 schools — understanding the past is not indoctrination.",
            ],
        },
    ]


def _curriculum_nl() -> List[dict[str, Any]]:
    """Netherlands-specific big questions grounded in Dutch political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Grote vragen voor Nederland: Stikstof, energie en klimaat",
            "description": "Hoe balanceert Nederland klimaatdoelen met de belangen van boeren en industrie?",
            "information_title": "Before you vote",
            "information_body": "These questions concern **Dutch policy choices** — nitrogen rules, Groningen gas, and delta adaptation.",
            "article_keywords": ["Netherlands nitrogen", "stikstof", "Groningen gas", "Dutch climate", "energy transition Netherlands"],
            "seeds": [
                "The Netherlands must cut livestock numbers significantly to meet nitrogen emission targets, even at cost to farmers.",
                "Groningen gas extraction should have been phased out faster, regardless of energy supply concerns.",
                "Dutch water management expertise gives the Netherlands a special obligation to fund global sea-level adaptation.",
                "The Netherlands should close all coal power stations before 2030 even if electricity prices rise.",
                "Dutch pension funds should be required to fully divest from fossil fuel companies.",
                "Nuclear energy should be expanded in the Netherlands as part of the clean energy transition.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for the Netherlands: ASML, AI governance, and digital sovereignty",
            "description": "Can the Netherlands shape global tech policy from its unique position as home to ASML?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Dutch tech policy**, ASML export controls, and EU digital regulation.",
            "article_keywords": ["ASML export controls", "Netherlands AI", "Dutch tech sector", "EU digital sovereignty", "chip war"],
            "seeds": [
                "The Dutch government was right to restrict ASML chip technology exports to China under US pressure.",
                "The EU AI Act is good for Dutch businesses in the long run even if short-term compliance is costly.",
                "The Netherlands should invest more in domestic AI research to reduce dependence on US and Chinese platforms.",
                "Privacy regulators like the Dutch DPA should have larger budgets to enforce GDPR against Big Tech.",
                "ASML's success shows the Netherlands should prioritise deep-tech industry over financial services.",
                "Digital identity systems for citizens should use open-source software under public control.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for the Netherlands: Housing, flex work, and the Dutch economy",
            "description": "The housing crisis, flex contracts, and whether Dutch prosperity is distributed fairly.",
            "information_title": "Before you vote",
            "information_body": "Focus on **structural economic policy** — housing, flex work, pensions — not individual circumstances.",
            "article_keywords": ["Netherlands housing crisis", "flex workers Netherlands", "Dutch pension reform", "woningmarkt"],
            "seeds": [
                "The Dutch government should intervene directly in the housing market by building at least 100,000 homes per year.",
                "Zero-hours and flex contracts should be restricted so more workers get permanent employment.",
                "The new Dutch pension system (moving to defined contribution) is fairer for younger workers.",
                "The Netherlands benefits too much from its tax treaty network and should close loopholes used by multinationals.",
                "The wage gap between permanent and temporary workers doing the same job should be illegal.",
                "Dutch homeowners receive too many tax subsidies (hypotheekrenteaftrek) at the expense of renters.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for the Netherlands: Zorg, eigen risico, and public health",
            "description": "Is the Dutch insurance-based healthcare system still working for everyone?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Dutch healthcare access, the eigen risico (deductible), and long-term care**.",
            "article_keywords": ["Dutch healthcare", "eigen risico", "zorgverzekering", "elderly care Netherlands"],
            "seeds": [
                "The eigen risico (compulsory health deductible) should be abolished because it stops people seeking care.",
                "Elderly care in the Netherlands is chronically underfunded and needs a major increase in spending.",
                "Mental health waiting times in the Netherlands are unacceptably long and need urgent investment.",
                "The Dutch compulsory health insurance model is fairer than a fully public NHS-style system.",
                "Preventive public health measures — like sugar taxes — are worth the infringement on personal choice.",
                "GP shortages in rural areas of the Netherlands are a serious equity problem the government must address.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for the Netherlands: Defence, Ukraine, and Dutch foreign policy",
            "description": "F-35s to Ukraine, NATO obligations, and MH17 — where should the Netherlands stand?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **alliances, military support, and international justice**.",
            "article_keywords": ["Netherlands Ukraine F-35", "Netherlands NATO", "MH17", "Dutch defence spending"],
            "seeds": [
                "The Netherlands was right to transfer F-16 fighter jets to Ukraine.",
                "The Netherlands should reach NATO's 2% GDP defence spending target within this decade.",
                "The MH17 verdict and damages claim against Russia should be pursued through all available international mechanisms.",
                "Dutch special forces involvement in conflicts should require explicit parliamentary authorisation.",
                "The Netherlands should push within the EU for a common European defence force to reduce reliance on the US.",
                "Development aid should not be cut to fund higher defence spending.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for the Netherlands: Democracy, coalitions, and the rise of populism",
            "description": "Long kabinetsformaties, PVV's rise, and what the Dutch political system needs.",
            "information_title": "Before you vote",
            "information_body": "Focus on **institutional design** — the formation process, media freedom, and civic trust.",
            "article_keywords": ["Netherlands elections", "PVV Wilders", "kabinetsformatie", "Dutch democracy", "proportional representation"],
            "seeds": [
                "The Netherlands' proportional representation system produces better policy outcomes than majoritarian alternatives.",
                "Coalition formation (formatie) taking months undermines democratic accountability and needs time limits.",
                "Public broadcasters like NPO need stronger independence guarantees against political interference.",
                "The Dutch constitution should include explicit protection for the rule of law against parliamentary majorities.",
                "Municipalities should have more financial autonomy from the national government.",
                "Mandatory civic education at secondary school level would improve democratic participation.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for the Netherlands: Immigration, integration, and Dutch identity",
            "description": "Asylum system pressure, integration policy, and what Dutchness means today.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design**, not on people's backgrounds or worth.",
            "article_keywords": ["Netherlands asylum policy", "integration Netherlands", "Dutch identity", "COA asylum"],
            "seeds": [
                "The Netherlands must accept its legal obligations under EU asylum rules even when numbers are high.",
                "Integration programmes should be mandatory, well-funded, and focused on language and employment.",
                "The Dutch housing crisis is caused by policy failures, not by immigration.",
                "Discrimination in the Dutch labour and housing market must be actively countered by law enforcement.",
                "Municipalities should have the right to distribute asylum seekers across the country equitably.",
                "Dutch civic identity should be based on shared democratic values, not on ethnic heritage.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for the Netherlands: MBO, HBO, and preparing for a changing economy",
            "description": "Skills shortages, MBO prestige, and whether Dutch education is fit for the future.",
            "information_title": "Before you vote",
            "information_body": "Focus on **system design and access** — the MBO-HBO-WO ladder, teacher pay, and early selection.",
            "article_keywords": ["Dutch education MBO", "Netherlands teacher shortage", "early selection Netherlands", "onderwijs"],
            "seeds": [
                "Early selection at age 12 for secondary school tracks (vmbo/havo/vwo) is too young and reinforces inequality.",
                "MBO graduates contribute as much to the Dutch economy as university graduates and should be treated as equal.",
                "Teacher shortages in the Netherlands are the result of wages falling behind other graduate professions.",
                "The Netherlands should invest more in early childhood education to close disadvantage gaps before age 5.",
                "Student finance (studielening) should be replaced with a grant for students from lower-income families.",
                "Dutch schools should teach civic literacy and media literacy as core subjects from primary school.",
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
            "description": "Can Ireland meet its climate targets while protecting rural livelihoods?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Irish policy choices** — ag-sector methane, peat bogs, and planning reform.",
            "article_keywords": ["Ireland climate", "Irish farming emissions", "peat bogs Ireland", "renewable energy Ireland"],
            "seeds": [
                "Ireland must reduce cattle and dairy herd sizes to meet legally binding climate targets.",
                "Peat bog restoration should be prioritised over agricultural use even when this displaces farmers.",
                "Planning for large-scale wind and solar farms in Ireland should be fast-tracked significantly.",
                "Ireland's per-capita emissions are among Europe's highest and this requires urgent, uncomfortable policy change.",
                "Community benefit funds from wind farms should go directly to local residents, not just local authorities.",
                "Ireland should invest in offshore wind at the scale needed to become a net exporter of clean energy.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Ireland: Tech multinationals, data centres, and digital policy",
            "description": "Is Ireland's dependence on US tech FDI a strength or a structural vulnerability?",
            "information_title": "Before you vote",
            "information_body": "Consider Ireland's role as **European headquarters** for US tech giants and as home to the DPC.",
            "article_keywords": ["Ireland tech sector", "Data Protection Commission", "data centres Ireland", "FDI Ireland tech"],
            "seeds": [
                "Ireland relies too heavily on US tech multinationals and needs to diversify its economic base.",
                "The Data Protection Commission needs significantly more resources to enforce GDPR against Big Tech.",
                "New data centres in Ireland should not be permitted while the electricity grid is under such strain.",
                "Ireland benefits enormously from tech FDI and should actively compete to retain these companies.",
                "Irish universities should invest more in AI and computer science to build domestic tech capacity.",
                "Tech companies' low effective tax rates in Ireland are unfair to other countries and should end.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Ireland: Housing, cost of living, and the Irish economy",
            "description": "Ireland's housing emergency, reliance on FDI taxes, and the cost of living crisis.",
            "information_title": "Before you vote",
            "information_body": "These are **structural questions** about Ireland's economy — housing, tax base, and wages.",
            "article_keywords": ["Ireland housing crisis", "Irish cost of living", "short-term lets Ireland", "Airbnb Ireland"],
            "seeds": [
                "The state should directly build social and affordable housing at scale rather than relying on the private market.",
                "Short-term rental platforms like Airbnb should be heavily restricted in areas with housing shortages.",
                "Ireland should begin reducing its dependence on corporate tax revenues by broadening the tax base.",
                "The minimum wage in Ireland should rise to a true living wage that covers rent in major cities.",
                "Planning permission for high-density housing near transport should be granted automatically by default.",
                "Remote working rights should be enshrined in law to reduce pressure on Dublin's housing market.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Ireland: Sláintecare, the two-tier system, and mental health",
            "description": "Can Ireland build the universal health system it voted for?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Sláintecare implementation, waiting lists, and the public-private divide** in Irish healthcare.",
            "article_keywords": ["Sláintecare", "Ireland healthcare", "Irish mental health services", "HSE reform"],
            "seeds": [
                "Sláintecare should be implemented fully, even if it requires significant tax increases.",
                "Private health insurance in Ireland gives those who can afford it unfair priority access to public hospital beds.",
                "Mental health spending in Ireland is too low as a share of the health budget and should be doubled.",
                "GP fees should be abolished for all, not just medical card holders, to reduce inequity.",
                "Consultants with private practices should not be permitted to hold public hospital contracts.",
                "The HSE is too large and centralised and should be replaced with regional health authorities.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Ireland: Neutrality, defence, and Ireland's role in the world",
            "description": "Should Ireland maintain military neutrality or take more responsibility for European security?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **Irish neutrality, UN peacekeeping, and European defence**.",
            "article_keywords": ["Irish neutrality", "Ireland defence", "Ireland UN peacekeeping", "Irish military", "EU defence"],
            "seeds": [
                "Irish military neutrality is outdated and should be replaced by full NATO membership.",
                "Ireland should increase defence spending significantly even if it requires new taxes.",
                "Irish neutrality should be enshrined in the constitution to prevent future governments abandoning it.",
                "Ireland should continue to take a strong pro-Palestinian position at the UN, even at diplomatic cost.",
                "EU mutual defence commitments already effectively end Irish neutrality in practice.",
                "Ireland should expand its UN peacekeeping contributions as an expression of its foreign policy values.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Ireland: The Dáil, Citizens' Assemblies, and Irish democracy",
            "description": "Electoral reform, Citizens' Assemblies, and restoring trust in Irish politics.",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design questions** — not about any party's current record.",
            "article_keywords": ["Ireland electoral reform", "Citizens Assembly Ireland", "Dáil reform", "Irish politics"],
            "seeds": [
                "Ireland's Citizens' Assemblies have been a genuine democratic innovation and should be used more often.",
                "Dáil sitting hours should be extended and reformed so TDs spend more time scrutinising legislation.",
                "Ireland should consider moving to a unicameral parliament by abolishing the Seanad.",
                "Political donations from corporations and property developers should be banned entirely.",
                "Voting should be extended to Irish citizens abroad for Dáil elections.",
                "Lowering the voting age to 16 in all elections, not just referendums, would strengthen democracy.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Ireland: Immigration, identity, and modern Irish society",
            "description": "Ireland's rapidly changing demographics and what it means to belong.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy and values**, not on people's backgrounds or choices.",
            "article_keywords": ["Ireland immigration", "direct provision Ireland", "homelessness Ireland", "Irish identity"],
            "seeds": [
                "Direct provision for asylum seekers should be abolished and replaced with community housing.",
                "Ireland's economic success depends on continued immigration and the state should say so clearly.",
                "Anti-immigration rhetoric in Irish politics is a serious threat to social cohesion.",
                "The Irish state has a duty to formally apologise and pay reparations for institutional abuse survivors.",
                "Homelessness in Ireland is a political failure, not an inevitable consequence of market forces.",
                "Ireland should make it easier for Irish diaspora to return and contribute to the economy.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Ireland: CAO, apprenticeships, and the future of Irish education",
            "description": "The points race, teacher pay, and whether Irish education delivers for all.",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, the CAO system, and skills** — not individual school performance.",
            "article_keywords": ["CAO Ireland", "Ireland teacher pay", "apprenticeships Ireland", "Irish schools"],
            "seeds": [
                "The CAO points race puts too much pressure on teenagers and should be reformed significantly.",
                "Teacher pay in Ireland is too low relative to other graduate professions and must rise.",
                "Apprenticeships and post-Leaving Cert courses should be funded and respected equally to degrees.",
                "Irish schools should teach personal finance, civic education, and media literacy as core subjects.",
                "Religious bodies should have no role in admissions criteria for state-funded schools.",
                "Third-level fees should be abolished and replaced with a graduate contribution via the tax system.",
            ],
        },
    ]


def _curriculum_de() -> List[dict[str, Any]]:
    """Germany-specific big questions grounded in German political debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Große Fragen für Deutschland: Energiewende, Kohleausstieg und Klimapolitik",
            "description": "Was kostet die Energiewende — und wer soll dafür bezahlen?",
            "information_title": "Before you vote",
            "information_body": "Focus on **German energy policy choices** — the nuclear phase-out, coal exit, and Energiewende costs.",
            "article_keywords": ["Energiewende", "Germany coal", "German nuclear", "Kohleausstieg", "German climate policy"],
            "seeds": [
                "Germany's decision to phase out nuclear power after Fukushima was a serious mistake for the climate.",
                "The Kohleausstieg (coal phase-out) should be accelerated to 2030 rather than delayed.",
                "Germany's Energiewende is a model for other countries despite its costs and implementation problems.",
                "German households and industry pay too much for electricity due to green energy surcharges.",
                "Germany should invest heavily in green hydrogen to decarbonise its industrial base.",
                "Autobahn speed limits should be introduced — Germany is the only major country without them.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Germany: Digitalisation, AI, and the Mittelstand",
            "description": "Can Germany's traditional industrial strengths survive the digital revolution?",
            "information_title": "Before you vote",
            "information_body": "Focus on **German digital policy**, GDPR origins, and the EU AI Act's impact on German industry.",
            "article_keywords": ["Germany digitalisation", "Mittelstand AI", "German tech policy", "EU AI Act Germany"],
            "seeds": [
                "Germany's Mittelstand is falling dangerously behind in digitalisation and the government must intervene.",
                "Germany's strong data protection tradition (rooted in GDPR) should not be weakened to attract tech investment.",
                "Germany needs a national AI strategy that competes with the US and China, not just regulation.",
                "German manufacturing should embrace AI-driven automation even though it will reduce some jobs.",
                "Germany should lead in developing European sovereign cloud infrastructure independent of US companies.",
                "Public services in Germany are too analogue — digital government must become a national priority.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Germany: Growth, Kurzarbeit, and the German economic model",
            "description": "Is the German social market economy still fit for purpose?",
            "information_title": "Before you vote",
            "information_body": "Focus on **structural economic questions** — the debt brake, Mindestlohn, and industrial subsidies.",
            "article_keywords": ["Schuldenbremse", "Kurzarbeit", "Mindestlohn Germany", "German economy stagnation"],
            "seeds": [
                "The Schuldenbremse (debt brake) should be reformed to allow investment in infrastructure and green transition.",
                "Germany's Kurzarbeit scheme should be made permanent as a model for protecting workers in downturns.",
                "The Mindestlohn (minimum wage) should rise to €15 and be indexed to living costs.",
                "Germany's economic model is too dependent on car exports and must diversify urgently.",
                "German industrial subsidies for the car sector have delayed necessary transformation.",
                "Eastern Germany still has structural economic disadvantages that require targeted federal support.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Germany: The two-tier health system and care for an aging society",
            "description": "Is Germany's dual public-private health insurance system fair?",
            "information_title": "Before you vote",
            "information_body": "Focus on **GKV vs PKV, Pflegereform, and care workforce** issues in Germany.",
            "article_keywords": ["GKV PKV Germany", "German healthcare reform", "Pflegereform", "elderly care Germany"],
            "seeds": [
                "Germany should merge statutory (GKV) and private (PKV) health insurance into a single system.",
                "Long-term care insurance (Pflegeversicherung) contributions are too low and must rise significantly.",
                "Care workers in Germany are underpaid and understaffed — this is a systemic failure.",
                "Higher earners should not be able to opt out of the statutory health insurance system.",
                "Germany's hospital system has too many beds and needs consolidation to improve quality.",
                "Mental health waiting times in Germany are too long and are a public health crisis.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Germany: Zeitenwende, Ukraine, and German security policy",
            "description": "Has Germany turned the page on pacifism? What does the Zeitenwende really mean?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **German rearmament, Russia policy, and European security**.",
            "article_keywords": ["Zeitenwende Germany", "Bundeswehr", "Germany Ukraine weapons", "NATO Germany", "German pacifism"],
            "seeds": [
                "Germany's post-WWII pacifist culture has been a liability for European security and must change.",
                "Germany should reach NATO's 2% defence spending target by 2025 at the latest.",
                "Germany made a serious strategic error in its dependence on Russian gas under Nord Stream.",
                "Germany should supply Taurus cruise missiles to Ukraine as quickly as possible.",
                "German reunification lessons show that engaging authoritarian states can work — the Russia policy was not simply naive.",
                "Germany should take a leading role in building a genuinely autonomous European defence capability.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Germany: Democracy, the AfD, and German political institutions",
            "description": "How should Germany respond to the rise of the AfD and democratic backsliding?",
            "information_title": "Before you vote",
            "information_body": "Focus on **institutional design** — the Basic Law, party bans, and democratic resilience.",
            "article_keywords": ["AfD Germany ban", "German Basic Law", "Verfassungsschutz", "CDU SPD coalition"],
            "seeds": [
                "The AfD should be banned under Article 21 of the Basic Law if it is shown to be anti-constitutional.",
                "Germany's 5% electoral threshold prevents fragmentation but excludes legitimate minority voices.",
                "The Bundestag is too large and should be reformed to reduce the number of MPs significantly.",
                "Germany's firewall against coalition with the AfD is necessary to defend democratic norms.",
                "The Federal Constitutional Court's independence must be protected against parliamentary majorities.",
                "Germany needs stronger lobbying transparency laws to reduce corporate influence on legislation.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Germany: Migration, integration, and German identity",
            "description": "From Willkommenskultur to Messer-Debatte — where is Germany's migration policy heading?",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design and values** — not on the character of individuals.",
            "article_keywords": ["Germany migration", "German integration policy", "Willkommenskultur", "asylum Germany"],
            "seeds": [
                "Germany's 2015 Willkommenskultur was the right moral and practical response to the refugee crisis.",
                "Integration programmes in Germany need much more funding and must be completed before status is granted.",
                "Germany needs significantly more skilled migration to sustain its economy and fund its pensions.",
                "Deportations of failed asylum seekers to countries like Afghanistan should not be carried out.",
                "Germany's migration debate has been captured by the right and the government must reframe it.",
                "Anti-discrimination laws in Germany need stronger enforcement — the gap between law and practice is too wide.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Germany: Bildung, Gymnasium, and skills for the future",
            "description": "Does the German education system still serve children from all backgrounds equally?",
            "information_title": "Before you vote",
            "information_body": "Focus on **system design and equity** — early selection, Gymnasium prestige, and Bildungsföderalismus.",
            "article_keywords": ["German education Gymnasium", "Fachhochschule prestige", "early selection Germany", "teacher pay Germany"],
            "seeds": [
                "Germany's early selection at age 10 for Gymnasium/Realschule/Hauptschule tracks harms children from lower-income families.",
                "The German dual vocational training system (Ausbildung) is undervalued compared to academic routes.",
                "Germany's Bildungsföderalismus (16 different state school systems) creates unacceptable inequality.",
                "Teacher pay in Germany should be set at a national level and raised for all states.",
                "German universities suffer from underfunding and the reintroduction of tuition fees should be discussed.",
                "All German children should have access to full-day schooling (Ganztagsschule) as a right.",
            ],
        },
    ]


def _curriculum_fr() -> List[dict[str, Any]]:
    """France-specific big questions grounded in French political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Grandes questions pour la France : Nucléaire, climat et transition énergétique",
            "description": "La France peut-elle mener l'Europe sur le nucléaire tout en tenant ses objectifs climatiques ?",
            "information_title": "Before you vote",
            "information_body": "Focus on **French energy choices** — nuclear expansion, REPowerEU, and agricultural emissions.",
            "article_keywords": ["France nuclear energy", "French climate policy", "EDF", "French agriculture emissions", "COP France"],
            "seeds": [
                "France was right to maintain and expand nuclear power as the backbone of a low-carbon electricity grid.",
                "France's agricultural sector must reduce methane emissions even though this threatens traditional farming.",
                "French households should be required to insulate their homes to reduce energy consumption.",
                "EDF's renationalisation was necessary to protect French energy sovereignty.",
                "France should use its nuclear expertise to help other EU countries decarbonise rather than discouraging nuclear.",
                "French farmers' protests should not delay necessary environmental reforms in agriculture.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for France: IA, tech sovereignty, and La French Tech",
            "description": "Can France build a world-class AI sector while defending European digital sovereignty?",
            "information_title": "Before you vote",
            "information_body": "Focus on **French tech policy**, the French Tech ecosystem, CNIL, and EU AI governance.",
            "article_keywords": ["French Tech AI", "CNIL France", "Mistral AI", "French digital sovereignty", "GAFAM France"],
            "seeds": [
                "France should invest significantly more in AI champions like Mistral to challenge US and Chinese dominance.",
                "The CNIL needs a larger budget and stronger enforcement powers to hold Big Tech accountable.",
                "France's approach to banning TikTok on government devices should be extended to more official contexts.",
                "French cultural exception policies should be extended to AI-generated content and digital platforms.",
                "France should lead Europe in demanding that AI training data respect copyright and pay creators.",
                "EU digital sovereignty is best achieved through common European standards, not national protectionism.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for France: Retraites, 35 heures, and the French economic model",
            "description": "Macron's pension reform, la semaine des 35 heures, and who pays for France's social model.",
            "information_title": "Before you vote",
            "information_body": "These are **structural policy questions** about the French economic and social model.",
            "article_keywords": ["French pension reform", "35 heures France", "French unemployment", "CDI CDD France"],
            "seeds": [
                "Raising the French retirement age to 64 was economically necessary even though socially painful.",
                "The 35-hour working week has protected French workers without the economic damage critics predicted.",
                "France's labour code is too rigid and makes companies reluctant to hire on permanent (CDI) contracts.",
                "The French state is too large as a share of GDP and needs structural reform, not just efficiency savings.",
                "France needs to invest more in vocational training to reduce youth unemployment.",
                "High French youth unemployment is primarily a supply-side problem that requires labour market reform.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for France: Sécurité Sociale, déserts médicaux, and French healthcare",
            "description": "Is France's acclaimed healthcare system still delivering for everyone?",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, funding, and the désertification médicale** affecting rural France.",
            "article_keywords": ["France Sécurité Sociale", "déserts médicaux", "French health system", "hospital reform France"],
            "seeds": [
                "France's universal health coverage model is one of its greatest social achievements and must be protected.",
                "Médecins déserts (areas with too few GPs) in rural France are a public health emergency requiring urgent action.",
                "Private clinics should not receive public subsidies while the public hospital system is underfunded.",
                "Mental health services in France are severely underfunded relative to other European countries.",
                "France should introduce a sugar tax on processed food to address rising rates of obesity.",
                "Waiting times in French accident and emergency departments have become unacceptably long.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for France: Nucléaire, Françafrique, and l'autonomie stratégique",
            "description": "France's nuclear deterrent, Africa policy, and the case for EU strategic autonomy.",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **French military power and European defence**.",
            "article_keywords": ["French nuclear deterrent", "Françafrique", "EU strategic autonomy Macron", "France NATO"],
            "seeds": [
                "France's independent nuclear deterrent is a cornerstone of European security that should be maintained.",
                "France's post-colonial military presence in Africa has done more harm than good and should end.",
                "Macron's push for EU strategic autonomy is correct — Europe cannot rely on the US indefinitely.",
                "France should contribute more military equipment to Ukraine rather than seeking a negotiated ceasefire.",
                "France's permanent UN Security Council seat gives it special responsibilities it has not always met.",
                "European defence should be funded collectively through EU bonds, not just by national defence budgets.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for France: La Ve République, les gilets jaunes, and French democracy",
            "description": "Is the Fifth Republic's strong presidency a strength or a democratic weakness?",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design questions** — the Fifth Republic, referenda, and the National Assembly.",
            "article_keywords": ["Fifth Republic France", "gilets jaunes", "French electoral reform", "Rassemblement National"],
            "seeds": [
                "The Fifth Republic gives the President too much power and should be reformed toward a parliamentary model.",
                "The gilets jaunes movement exposed legitimate grievances about economic inequality that have not been addressed.",
                "France should introduce proportional representation for National Assembly elections.",
                "Using article 49.3 to bypass parliament on major legislation undermines democratic legitimacy.",
                "The rise of the Rassemblement National reflects a failure of mainstream parties to address real concerns.",
                "Citizens' assemblies, as used for the Climate Convention, should become a regular part of French democracy.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for France: Laïcité, immigration, and French cohesion",
            "description": "The headscarf, les banlieues, and what French republicanism means in practice.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design and values** — not on individuals' religious or cultural choices.",
            "article_keywords": ["French laïcité", "France immigration", "banlieues France", "French integration"],
            "seeds": [
                "Laïcité as enforced in France goes too far in restricting religious expression in public life.",
                "France's banlieues reflect decades of structural economic exclusion that cannot be solved by policing.",
                "France receives too many migrants to integrate well — the pace of arrivals should slow.",
                "Discrimination in hiring and housing against French citizens of immigrant background is a serious ongoing injustice.",
                "France's model of republican integration — demanding assimilation over multiculturalism — has broadly worked.",
                "Affirmative action (discrimination positive) targeting disadvantaged zones should be expanded in France.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for France: Grandes écoles, le bac, and French education",
            "description": "Does French elite education perpetuate privilege more than it creates opportunity?",
            "information_title": "Before you vote",
            "information_body": "Focus on **access and system design** — the grandes écoles, baccalauréat reform, and lycée professionnel.",
            "article_keywords": ["grandes écoles France", "French baccalaureate reform", "lycée professionnel", "French teacher pay"],
            "seeds": [
                "The grandes écoles system perpetuates elite privilege and should be merged into or opened up through universities.",
                "Parcoursup's opaque algorithms make university entrance less fair than the previous system.",
                "Lycée professionnel students receive a second-class education and should have the same resources as academic tracks.",
                "The French baccalauréat is still the best single credential for assessing secondary achievement.",
                "Teacher pay in France has fallen too far behind and must be raised significantly.",
                "Philosophy as a compulsory bac subject is a genuine strength of French education that should be retained.",
            ],
        },
    ]


def _curriculum_ca() -> List[dict[str, Any]]:
    """Canada-specific big questions grounded in Canadian political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Canada: Oil sands, carbon tax, and climate leadership",
            "description": "Can Canada claim climate leadership while expanding oil sands production?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Canadian policy choices** — Trans Mountain, the carbon price, and Indigenous land rights.",
            "article_keywords": ["Canada carbon tax", "oil sands Alberta", "Trans Mountain pipeline", "Canada climate policy"],
            "seeds": [
                "Canada cannot credibly claim climate leadership while expanding oil sands production.",
                "The federal carbon price is the right policy instrument even when it is politically unpopular.",
                "Trans Mountain pipeline expansion should have been cancelled on environmental and Indigenous rights grounds.",
                "Canada should be a global leader in protecting its boreal forests as a carbon sink.",
                "Federal and provincial climate policies are too poorly coordinated to achieve Canada's Paris commitments.",
                "Clean electricity should be 100% of Canada's grid by 2035 — this is achievable and necessary.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Canada: AI leadership, Bill C-11, and the digital economy",
            "description": "Is Canada doing enough to keep its AI talent and shape digital regulation?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Canadian tech policy** — AI research leadership, the Online Streaming Act (C-11), and data governance.",
            "article_keywords": ["Canada AI policy", "Bill C-11 CRTC", "Canadian tech sector", "brain drain Canada"],
            "seeds": [
                "Canada is losing too much AI research talent to the US and needs major investment to retain it.",
                "Bill C-11 (Online Streaming Act) is a legitimate attempt to fund Canadian content in the digital age.",
                "Canada needs a comprehensive federal AI regulatory framework to protect citizens from algorithmic harm.",
                "Canadian data privacy law (PIPEDA) is outdated and needs to be strengthened to match GDPR standards.",
                "Public investment in computing infrastructure for AI research should be treated as strategic national infrastructure.",
                "Canada should develop its own sovereign cloud capacity rather than relying entirely on US providers.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Canada: Housing, wages, and the Canadian dream",
            "description": "Toronto and Vancouver housing costs, temporary foreign workers, and generational inequality.",
            "information_title": "Before you vote",
            "information_body": "Focus on **structural policy** — housing supply, wages, and what Canada owes to workers.",
            "article_keywords": ["Canada housing crisis", "Toronto Vancouver housing", "Canadian wages", "temporary workers Canada"],
            "seeds": [
                "The federal government should take a much more active role in building affordable housing, not just funding provinces.",
                "Zoning reform to allow high-density housing near transit should be mandatory for cities receiving federal funding.",
                "Canada's temporary foreign worker programmes are being misused to undercut wages for Canadian workers.",
                "The federal minimum wage should apply across all industries and rise to $20 an hour.",
                "Canada's immigration levels are too high relative to housing supply and infrastructure capacity.",
                "Generational inequality in housing wealth is one of the defining challenges of Canadian society today.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Canada: Wait times, pharmacare, and the future of Medicare",
            "description": "Is Canadian universal healthcare still delivering on its promise?",
            "information_title": "Before you vote",
            "information_body": "Focus on **system design** — wait times, provincial jurisdiction, pharmacare, and dental care.",
            "article_keywords": ["Canada healthcare wait times", "pharmacare Canada", "provincial health transfers", "dental care Canada"],
            "seeds": [
                "Canada's universal healthcare system is chronically underfunded and needs major new public investment.",
                "A national pharmacare programme covering all Canadians is long overdue and affordable.",
                "Provincial health transfers from the federal government should be increased significantly with strings attached.",
                "The two-tier option of private surgical clinics alongside the public system violates the Canada Health Act.",
                "Canada's mental health system is so underfunded that it constitutes a public health emergency.",
                "Dental care and vision care should be included in universal public coverage as in most comparable countries.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Canada: NATO, Arctic sovereignty, and Canadian defence",
            "description": "NORAD modernisation, the 2% NATO target, and Arctic security.",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **Canadian military obligations and Arctic sovereignty**.",
            "article_keywords": ["Canada NATO 2%", "NORAD modernisation", "Arctic sovereignty Canada", "Canada Ukraine"],
            "seeds": [
                "Canada should meet NATO's 2% of GDP defence spending commitment rather than free-riding on allies.",
                "NORAD modernisation is essential for Canadian sovereignty and should be funded without delay.",
                "Canada has a special obligation to assert Arctic sovereignty given climate-driven ice melt.",
                "Canada should increase its military support to Ukraine significantly.",
                "Canadian defence spending is not just an obligation to NATO but a necessary investment in Canadian sovereignty.",
                "Canada should build more of its own defence equipment rather than relying entirely on US procurement.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Canada: Electoral reform, Senate, and Canadian democracy",
            "description": "FPTP vs proportional representation, Senate reform, and trust in Canadian institutions.",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design questions** — not claims about any party's record.",
            "article_keywords": ["Canada electoral reform", "Senate reform Canada", "proportional representation Canada", "Canadian politics"],
            "seeds": [
                "Canada should replace first-past-the-post with proportional representation as was promised in 2015.",
                "The Senate should be abolished or replaced with an elected body representing provinces.",
                "Supreme Court justices should be confirmed by a parliamentary committee rather than appointed by the PM alone.",
                "The power of the Prime Minister's Office is excessive and Parliament should claw back more authority.",
                "Municipal governments need more financial autonomy and tax powers to address urban challenges.",
                "Canada needs mandatory lobbying transparency so citizens can see who is influencing federal decisions.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Canada: Reconciliation, immigration, and Canadian identity",
            "description": "Truth and Reconciliation, immigration levels, and what it means to be Canadian.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy and values** — not on individual people's backgrounds.",
            "article_keywords": ["Indigenous reconciliation Canada", "residential schools Canada", "Canada immigration levels"],
            "seeds": [
                "Canada has a legal and moral obligation to implement all 94 Truth and Reconciliation Commission calls to action.",
                "Residential school survivors and their families are owed meaningful reparations, not just apologies.",
                "Canada's current immigration levels are higher than the country can realistically integrate well.",
                "Anti-Asian and anti-Muslim racism in Canada is a serious ongoing problem that requires active policy responses.",
                "French-English bilingualism is a genuine strength of Canada that should be actively promoted, not merely preserved.",
                "Indigenous nations should have genuine self-determination over lands within their traditional territories.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Canada: Universities, trades, and learning for a changing economy",
            "description": "Student debt, the trades shortage, and whether Canadian education serves everyone.",
            "information_title": "Before you vote",
            "information_body": "Focus on **access and system design** — tuition, apprenticeships, and provincial jurisdiction.",
            "article_keywords": ["Canada student debt", "trades shortage Canada", "Canada education system", "French immersion access"],
            "seeds": [
                "University tuition in Canada is too high and should be significantly reduced through federal transfers.",
                "Skilled trades are underfunded and undervalued in Canada — this needs to change urgently.",
                "Federal student loan forgiveness programmes should be expanded significantly.",
                "French immersion access should be universal in English Canada, not dependent on lottery or geography.",
                "Indigenous language education should be fully funded by the federal government as part of reconciliation.",
                "Canada needs a national school nutrition programme — the last G7 country without one.",
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
            "description": "Can Singapore lead on sustainability while relying on imports for almost everything?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Singapore's Green Plan**, energy imports, and regional deforestation.",
            "article_keywords": ["Singapore Green Plan", "haze Singapore", "Singapore carbon tax", "Singapore solar energy"],
            "seeds": [
                "Singapore's carbon tax is too low to drive real business change and should be raised significantly.",
                "Singapore should refuse palm oil from suppliers that engage in deforestation regardless of trade costs.",
                "As a small island state, Singapore should be doing more to lead global climate diplomacy in ASEAN.",
                "Singapore's Green Plan 2030 targets are too modest given the country's wealth and capabilities.",
                "Singapore should invest in regional clean energy imports even if this creates some supply dependency.",
                "Reducing Singapore's reliance on natural gas for electricity generation should be accelerated.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Singapore: Smart Nation, fintech, and digital governance",
            "description": "Is Singapore's Smart Nation programme the right model for digital government?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Smart Nation, the PDPA, fintech regulation, and surveillance trade-offs**.",
            "article_keywords": ["Singapore Smart Nation", "PDPA Singapore", "Singapore fintech", "digital identity Singapore"],
            "seeds": [
                "Singapore's Smart Nation programme collects too much personal data and needs stronger privacy protections.",
                "Singapore's fintech regulatory sandbox is a global model that balances innovation with consumer protection.",
                "Singapore should enact a stronger digital personal data protection law aligned with GDPR standards.",
                "Facial recognition technology in public spaces by government agencies requires parliamentary oversight.",
                "Singapore's digital identity system (Singpass) should be extended to more government and private services.",
                "Singapore risks over-relying on US and Chinese tech giants for critical national digital infrastructure.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Singapore: HDB, foreign workers, and the Singapore social compact",
            "description": "Housing, foreign labour policy, and whether Singapore's growth model still works for everyone.",
            "information_title": "Before you vote",
            "information_body": "Focus on **structural policy** — HDB affordability, foreign worker levies, and the CPF system.",
            "article_keywords": ["HDB Singapore", "foreign workers Singapore levy", "CPF Singapore", "cost of living Singapore"],
            "seeds": [
                "HDB flats are too expensive for young Singaporeans entering the property market today.",
                "Singapore relies too heavily on low-wage foreign workers in ways that undercut wages for Singaporeans.",
                "The CPF system is a strong model for retirement savings that should be expanded, not weakened.",
                "Singapore needs a more progressive tax structure where the wealthy contribute more.",
                "Singapore's inequality, while lower than many cities, is high for its level of development.",
                "The government should more actively regulate the cost of living, not just manage it through subsidies.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Singapore: MediShield, eldercare, and an aging population",
            "description": "Can Singapore's 3M health financing model sustain an aging society?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Medisave, MediShield Life, ElderShield, and long-term care access**.",
            "article_keywords": ["MediShield Singapore", "Singapore eldercare", "aging population Singapore", "mental health Singapore"],
            "seeds": [
                "MediShield Life premiums are too high for lower and middle-income Singaporeans.",
                "Singapore needs a significantly larger public investment in eldercare as the population ages.",
                "Mental health services in Singapore are underfunded and carry too much social stigma.",
                "Singapore's 3M (Medisave, MediShield, Medifund) framework is fundamentally sound but needs updating.",
                "Long hospital waiting times indicate that Singapore needs more public hospital beds and staff.",
                "Caregivers — disproportionately women — need financial support from the state for their work.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Singapore: Regional security, FPDA, and navigating great-power rivalry",
            "description": "How should Singapore manage US-China competition without choosing sides?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **Singapore's strategic position and defence policy**.",
            "article_keywords": ["Singapore defence", "Five Power Defence", "US China Singapore", "South China Sea Singapore", "conscription Singapore"],
            "seeds": [
                "Singapore should continue its policy of not taking sides between the US and China even under pressure.",
                "National Service (conscription) remains essential for Singapore's defence and deterrence.",
                "Singapore should invest more in cybersecurity and non-military security given the nature of modern threats.",
                "The Five Power Defence Arrangements remain relevant to Singapore's security needs.",
                "Singapore's defence spending is appropriate given the regional security environment.",
                "Singapore should play a more active role in facilitating dialogue between US and China in Southeast Asia.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Singapore: GRC system, press freedom, and political openness",
            "description": "Is Singapore's political system becoming more or less open?",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design questions** about Singapore's political structures.",
            "article_keywords": ["GRC Singapore", "Singapore press freedom", "PAP Singapore", "ISA Singapore", "Workers Party"],
            "seeds": [
                "The Group Representation Constituency (GRC) system should be abolished as it advantages the ruling party.",
                "Singapore's press freedom ranking is too low for a country of its wealth and should be a national concern.",
                "The Internal Security Act should be repealed — indefinite detention without trial has no place in modern Singapore.",
                "A stronger opposition in parliament would make Singapore's government more accountable and effective.",
                "Defamation laws should not be used against political critics and journalists.",
                "Singapore needs a Freedom of Information Act to improve government transparency.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Singapore: Race harmony, foreign talent, and Singaporean identity",
            "description": "CMIO identity categories, foreign talent policy, and what Singaporean means today.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design**, not on individuals' backgrounds.",
            "article_keywords": ["Singapore racial harmony", "foreign talent Singapore", "CMIO race Singapore", "LGBTQ Singapore 377A"],
            "seeds": [
                "Singapore's government-defined CMIO (Chinese/Malay/Indian/Other) racial framework is outdated and should be reformed.",
                "The repeal of Section 377A was the right decision for an inclusive Singapore.",
                "Foreign talent in Singapore has contributed enormously to its success and is not a threat to Singaporeans.",
                "More should be done to address discrimination against Malay and Indian Singaporeans in employment.",
                "Singapore's social cohesion is one of its greatest assets and requires ongoing active investment.",
                "Singapore should make it easier for long-term residents to access permanent residency and citizenship.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Singapore: PSLE, SkillsFuture, and the tuition arms race",
            "description": "Is Singapore's education system breeding excellence or anxiety?",
            "information_title": "Before you vote",
            "information_body": "Focus on **PSLE reform, tuition industry, SkillsFuture, and what education is for**.",
            "article_keywords": ["PSLE Singapore", "tuition industry Singapore", "SkillsFuture", "Singapore education reform"],
            "seeds": [
                "The pressure of the PSLE on 12-year-olds is causing serious harm to children's wellbeing.",
                "The private tuition industry in Singapore widens inequality and should be regulated.",
                "SkillsFuture credits have not been effective enough and need a complete redesign.",
                "Singapore's school system still places too much emphasis on academic achievement over character and skills.",
                "University places should be expanded significantly given Singapore's knowledge-economy needs.",
                "Schools should teach financial literacy and civic education as core subjects from secondary school.",
            ],
        },
    ]


def _curriculum_jp() -> List[dict[str, Any]]:
    """Japan-specific big questions grounded in Japanese political and social debates."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions for Japan: Nuclear restarts, coal, and Japan's climate commitments",
            "description": "After Fukushima, can Japan build a credible path to carbon neutrality?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Japanese energy choices** — nuclear restarts, coal dependency, and offshore wind.",
            "article_keywords": ["Japan nuclear restart", "Japan coal power", "Japan climate policy", "Japan carbon neutral 2050"],
            "seeds": [
                "Japan was right to restart nuclear power plants as part of its decarbonisation strategy after the energy crisis.",
                "Japan's continued construction of new coal power plants undermines its own climate commitments.",
                "Japan should invest in offshore wind at a scale comparable to its investment in automotive manufacturing.",
                "Japan's 2050 carbon neutrality target requires policies far more ambitious than those currently in place.",
                "The Fukushima disaster should not be allowed to prevent a rational assessment of nuclear power's role.",
                "Japan's island geography gives it enormous potential for tidal and wave energy that is being underexploited.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions for Japan: AI strategy, robotics, and digital transformation",
            "description": "Can Japan lead in AI and robotics while addressing its digital government failures?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Japan's AI strategy**, My Number digital ID system, and manufacturing automation.",
            "article_keywords": ["Japan AI strategy", "Japan digital transformation", "My Number Japan", "Japan semiconductor TSMC"],
            "seeds": [
                "Japan's investment in attracting TSMC semiconductor production strengthens its strategic position significantly.",
                "Japan's My Number digital identity system should be accelerated despite privacy concerns.",
                "Japan needs to fundamentally reform its government IT systems, which are decades behind other advanced economies.",
                "Japan's strength in robotics means it is well-placed to lead on AI for manufacturing automation.",
                "Japan should adopt GDPR-equivalent data protection standards to participate fully in global digital trade.",
                "Japan's tech sector needs more immigration to address skill shortages, particularly in software engineering.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions for Japan: Deflation, wages, and Kishida's 'new capitalism'",
            "description": "Japan's lost decades, wage stagnation, and whether Abenomics worked.",
            "information_title": "Before you vote",
            "information_body": "Focus on **Japanese economic structure** — wage growth, women's participation, and corporate governance.",
            "article_keywords": ["Japan wage growth", "Abenomics", "Japan deflation", "women workforce Japan", "Japan corporate governance"],
            "seeds": [
                "Japan's corporations hold too much cash and should be required to either invest it or return it to shareholders.",
                "Japanese women's labour force participation rates are held back by structural discrimination that requires legal reform.",
                "Japan's minimum wage should be raised to ¥1,500 per hour nationally to end chronic deflation.",
                "Abenomics failed to address the structural causes of Japan's economic stagnation.",
                "Japan needs significant corporate governance reform to make its companies more internationally competitive.",
                "Japan's reliance on regular employment systems (seishain) entrenches inequality between permanent and temporary workers.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions for Japan: An aging society, universal healthcare, and end-of-life care",
            "description": "How can Japan sustain its world-class healthcare system as it ages faster than anywhere on earth?",
            "information_title": "Before you vote",
            "information_body": "Focus on **Japan's universal health insurance, aging population costs, and workforce**.",
            "article_keywords": ["Japan universal health insurance", "aging population Japan", "Japan mental health", "healthcare workforce Japan"],
            "seeds": [
                "Japan's universal health insurance system is one of its greatest social achievements and must be protected.",
                "Japan needs to train and retain significantly more doctors and nurses to meet future care demands.",
                "Japan's mental health system is underfunded and highly stigmatised — this must change.",
                "Japan should expand end-of-life care options, including greater access to palliative care outside hospitals.",
                "Healthcare premiums for Japan's aging population should be cross-subsidised more from general income taxes.",
                "Japan should accept more foreign healthcare workers to address its severe staff shortage.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions for Japan: The pacifist constitution, Taiwan, and Japanese rearmament",
            "description": "Should Japan revise Article 9 of its constitution and take on greater defence responsibilities?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **Japan's security posture and Article 9 of the constitution**.",
            "article_keywords": ["Japan Article 9 constitution", "Japan Taiwan Strait", "Japan defence spending", "Quad Japan", "Japan rearmament"],
            "seeds": [
                "Japan should formally revise Article 9 of its constitution to reflect its actual defence posture.",
                "Japan doubling defence spending to 2% of GDP is a necessary and overdue response to regional threats.",
                "Japan should make explicit security commitments to Taiwan given its strategic importance.",
                "The Quad (US, Japan, India, Australia) is an important counterbalance to Chinese military expansion.",
                "Japan's pacifist tradition, even if constitutionally revised, remains an important part of its global identity.",
                "Japan should develop stronger bilateral defence cooperation with South Korea despite historical tensions.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions for Japan: LDP dominance, women in parliament, and political reform",
            "description": "One-party dominance, corruption scandals, and Japan's democratic deficit.",
            "information_title": "Before you vote",
            "information_body": "These are **institutional design questions** about Japanese democracy.",
            "article_keywords": ["LDP Japan dominance", "Japan political reform", "women parliament Japan", "Japan corruption politics"],
            "seeds": [
                "Japan's near-permanent LDP dominance undermines effective democratic accountability.",
                "Japan's proportion of women in parliament is among the lowest in the OECD — this must change through active policy.",
                "The relationship between the LDP and Nippon Kaigi religious nationalism is a threat to Japan's secular democracy.",
                "Japan's electoral system creates rural-urban vote weight imbalances that should be corrected by the courts.",
                "Japan's opaque political funding system (seiji shikin) needs comprehensive transparency reform.",
                "Japan should make it easier for citizens to recall politicians and hold referendums at the national level.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions for Japan: Immigration, the birth rate, and the loneliness epidemic",
            "description": "Japan's demographic crisis, resistance to immigration, and social isolation.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design** — immigration, social supports, and what Japan's future looks like.",
            "article_keywords": ["Japan immigration", "Japan birth rate", "Japan loneliness", "hikikomori", "Japan population decline"],
            "seeds": [
                "Japan must accept significantly more permanent immigration to sustain its economy and pensions.",
                "Japan's childcare and parental leave policies are still not enabling women to have children and careers.",
                "Hikikomori (social withdrawal) and the loneliness epidemic require active government intervention.",
                "Discrimination against foreign residents and naturalised citizens must be actively combated by law.",
                "Japan should allow dual nationality — its current ban is economically and socially harmful.",
                "Same-sex partnership rights should be legally recognised nationally, not left to individual municipalities.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions for Japan: Juken, the Gaokao-equivalent pressure, and education reform",
            "description": "Is Japan's exam-driven education system fit for a creative, innovative economy?",
            "information_title": "Before you vote",
            "information_body": "Focus on **system design** — entrance exam pressure, English education, and university reform.",
            "article_keywords": ["Japan entrance exams", "Japanese education reform", "English education Japan", "juken culture"],
            "seeds": [
                "Japan's university entrance exam culture (juken) creates damaging levels of stress without improving outcomes.",
                "English language education in Japan must be reformed fundamentally — rote grammar does not produce fluent speakers.",
                "Japan's universities need significant reform to become more internationally competitive.",
                "Juku (private tutoring schools) widen inequality and the system should be reformed so they are less necessary.",
                "Japan needs more liberal arts education that builds critical thinking, not just technical specialisation.",
                "Japanese schools should actively teach students about the country's wartime history in a balanced way.",
            ],
        },
    ]


def _curriculum_cn() -> List[dict[str, Any]]:
    """China/Asia-Pacific big questions covering international debates relevant to Chinese audiences."""
    return [
        {
            "theme": "Climate & planet",
            "topic": "Environment",
            "title": "Big questions: China, Asia, and global climate responsibility",
            "description": "How should the world's largest emitter balance development goals with climate commitments?",
            "information_title": "Before you vote",
            "information_body": "Focus on **global climate choices** where China's decisions have major international consequences.",
            "article_keywords": ["China climate policy", "China carbon neutral 2060", "Belt Road green", "China coal overseas"],
            "seeds": [
                "China's 2060 carbon neutrality commitment is ambitious and deserves international support.",
                "China's Belt and Road Initiative should stop financing overseas coal power plants entirely.",
                "Rich developed countries have a greater historical responsibility for climate change than China.",
                "China's expansion of renewable energy capacity is one of the most important developments in global climate action.",
                "Developing countries should not be pressured to decarbonise as fast as wealthy nations that industrialised first.",
                "Climate change cooperation between the US and China should continue even during periods of strategic rivalry.",
            ],
        },
        {
            "theme": "AI & technology",
            "topic": "Technology",
            "title": "Big questions: AI governance, data sovereignty, and the global tech order",
            "description": "How should the world govern AI and protect digital rights?",
            "information_title": "Before you vote",
            "information_body": "Focus on **global AI governance choices** and competing regulatory models.",
            "article_keywords": ["AI governance global", "data sovereignty", "technology regulation China", "AI safety standards"],
            "seeds": [
                "Countries should have the right to require that citizens' data is stored and processed domestically.",
                "Artificial intelligence decisions affecting people's lives should be explainable and open to appeal.",
                "Global AI safety standards should be agreed through the UN rather than set by any single country or bloc.",
                "Technology decoupling between the US and China makes everyone less safe from AI risks.",
                "Open-source AI development benefits all countries by preventing monopolies by a few powerful actors.",
                "International cooperation on AI safety research should continue regardless of geopolitical tensions.",
            ],
        },
        {
            "theme": "Economy & work",
            "topic": "Economy",
            "title": "Big questions: Trade, development, and global economic fairness",
            "description": "Is the global economic order fair to developing countries?",
            "information_title": "Before you vote",
            "information_body": "Focus on **trade rules, development finance, and global economic equity**.",
            "article_keywords": ["China trade policy", "Belt Road Initiative", "global development finance", "WTO reform"],
            "seeds": [
                "The WTO rules need fundamental reform to better serve the interests of developing countries.",
                "Belt and Road Initiative loans should include stronger debt sustainability protections for recipient countries.",
                "Trade tariffs between the US and China are ultimately paid by ordinary consumers in both countries.",
                "Developing countries should have the right to protect domestic industries while they build capacity.",
                "Global supply chain reliance on any single country is a systemic risk that all nations should reduce.",
                "International financial institutions like the IMF and World Bank should give more voice to developing nations.",
            ],
        },
        {
            "theme": "Health & care",
            "topic": "Healthcare",
            "title": "Big questions: Global health, pandemic lessons, and healthcare equity",
            "description": "What did the world learn from COVID and are we better prepared?",
            "information_title": "Before you vote",
            "information_body": "Focus on **global health preparedness, vaccine equity, and international cooperation**.",
            "article_keywords": ["global pandemic preparedness", "vaccine equity", "WHO reform", "public health China"],
            "seeds": [
                "Vaccine patents should be waived during pandemics so that all countries can manufacture doses.",
                "The WHO needs stronger powers to investigate outbreaks quickly without member state obstruction.",
                "Rich countries' vaccine nationalism during COVID caused preventable deaths globally.",
                "Pandemic preparedness should be funded by a permanent international mechanism, not charity.",
                "Traditional and complementary medicine should be evaluated by the same evidence standards as other treatments.",
                "All countries should invest in universal health coverage regardless of their income level.",
            ],
        },
        {
            "theme": "War, peace & security",
            "topic": "Geopolitics",
            "title": "Big questions: Asia-Pacific security, Taiwan, and the rules-based order",
            "description": "Can the world avoid great-power conflict and build a more stable international system?",
            "information_title": "Before you vote",
            "information_body": "These are normative questions about **peace, sovereignty, and international norms**.",
            "article_keywords": ["Taiwan Strait stability", "South China Sea", "US China rivalry", "Asia Pacific security"],
            "seeds": [
                "Dialogue and diplomacy between the US and China are essential to avoid accidental military escalation.",
                "The UN Charter's prohibition on changing borders by force must apply equally to all countries.",
                "Economic interdependence between major powers makes large-scale conflict less likely than in past eras.",
                "Regional security in Asia-Pacific should be managed through multilateral frameworks, not bilateral deals.",
                "Sanctions and tariffs are not effective tools for resolving geopolitical disputes in the long run.",
                "Countries in dispute should use international courts and arbitration rather than unilateral action.",
            ],
        },
        {
            "theme": "Democracy & institutions",
            "topic": "Politics",
            "title": "Big questions: International institutions, governance, and global cooperation",
            "description": "Are international institutions fit to address the world's challenges?",
            "information_title": "Before you vote",
            "information_body": "These are **global governance questions** about international institutions and cooperation.",
            "article_keywords": ["UN reform", "multilateralism", "global governance", "international law"],
            "seeds": [
                "The UN Security Council's permanent membership needs to be reformed to reflect today's global power.",
                "International law is only effective when powerful countries choose to follow it — this is a structural problem.",
                "Global challenges like climate change and pandemics require stronger international institutions, not weaker ones.",
                "Countries should comply with international court decisions even when they lose.",
                "A just international order should give equal legal standing to all states regardless of their power.",
                "Multilateralism works better than unilateralism even when it is slower and more frustrating.",
            ],
        },
        {
            "theme": "Society & cohesion",
            "topic": "Society",
            "title": "Big questions: Migration, urbanisation, and social change in Asia",
            "description": "How rapidly urbanising societies manage diversity, inequality, and belonging.",
            "information_title": "Before you vote",
            "information_body": "Vote on **policy design** — urbanisation, social mobility, and what societies owe their members.",
            "article_keywords": ["urbanisation Asia", "social mobility", "inequality Asia", "migration Asia"],
            "seeds": [
                "Rapid urbanisation is good for economic development even when it disrupts traditional communities.",
                "Cities should invest more in social infrastructure — parks, libraries, community centres — not just transport.",
                "Greater economic inequality between urban and rural areas is one of the defining problems of our era.",
                "All people should have the right to move within their country and be treated equally regardless of origin.",
                "Social mobility in most countries is lower than people believe and requires active policy intervention.",
                "Demographic decline is better addressed by improving conditions for families than by restricting migration.",
            ],
        },
        {
            "theme": "Education & future skills",
            "topic": "Education",
            "title": "Big questions: Education, opportunity, and preparing societies for the future",
            "description": "How can education systems reduce inequality and equip people for a changing world?",
            "information_title": "Before you vote",
            "information_body": "Focus on **access, system design, and what education is for** in a changing global economy.",
            "article_keywords": ["education inequality global", "skills future economy", "higher education access"],
            "seeds": [
                "Education is the most powerful tool for reducing intergenerational poverty and governments should fund it generously.",
                "High-pressure examination systems do not produce the creative and critical thinkers modern economies need.",
                "Private tutoring industries in high-exam-pressure societies widen inequality and should be regulated.",
                "Access to quality early childhood education is as important as secondary and tertiary education.",
                "Higher education should be a public good funded primarily by the state, not primarily by students.",
                "Schools should explicitly teach students how to identify misinformation and think critically about sources.",
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
    return fn()


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
            d.information_body = spec.get("information_body")
            d.programme_phase = phase
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
                information_body=spec.get("information_body"),
                information_links=[],
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
