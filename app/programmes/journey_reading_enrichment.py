"""
Per-country optional reading for guided journey discussions.

Merged into curricula in get_curriculum() so every edition has:
  - Markdown links in information_body (primary sources, IOs, national statistics)
  - information_links: four vetted entry points mixing government, legislature,
    international organisations, and independent research / civic bodies.

Bodies are written to complement (not replace) each theme's framing; the global
vote-first preamble is still applied in seed_guided_journey_programme().
"""
from __future__ import annotations

from typing import Any, Dict, List

Link = Dict[str, str]
Pack = Dict[str, Any]


def _L(label: str, url: str) -> Link:
    return {"label": label, "url": url}


def _pack(body: str, a: Link, b: Link, c: Link, d: Link) -> Pack:
    return {"body": body, "links": [a, b, c, d]}


# ---------------------------------------------------------------------------
# United Kingdom
# ---------------------------------------------------------------------------
_UK: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "These questions concern **UK policy choices** — North Sea licensing, heat pumps, planning reform, and agricultural policy.\n\n"
        "**Optional references:** "
        "[Climate Change Committee](https://www.theccc.org.uk/) · "
        "[DESNZ — net zero & energy](https://www.gov.uk/government/organisations/department-for-energy-security-and-net-zero) · "
        "[National Grid ESO — Future Energy Scenarios](https://www.nationalgrideso.com/future-energy/future-energy-scenarios-fes) · "
        "[Met Office — UK climate projections](https://www.metoffice.gov.uk/research/approach/uk-climate-projections)",
        _L("Office for National Statistics", "https://www.ons.gov.uk/"),
        _L("UK Parliament — POST research", "https://post.parliament.uk/"),
        _L("Natural England", "https://www.gov.uk/government/organisations/natural-england"),
        _L("European Environment Agency (UK context)", "https://www.eea.europa.eu/en"),
    ),
    "AI & technology": _pack(
        "Consider the UK's position on **AI safety, online safety, and post-Brexit data regulation**.\n\n"
        "**Optional references:** "
        "[UK AI Safety Institute](https://www.gov.uk/government/organisations/ai-safety-institute) · "
        "[Online Safety Act 2023 (legislation.gov.uk)](https://www.legislation.gov.uk/ukpga/2023/50/contents/enacted) · "
        "[ICO — guide to AI & data protection](https://ico.org.uk/for-organisations/guide-to-data-protection/key-dp-themes/guidance-on-ai-and-data-protection/) · "
        "[EUR-Lex — EU AI Act (UK alignment context)](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689)",
        _L("UK Parliament — Science & Technology Committee", "https://committees.parliament.uk/committee/135/science-and-technology-committee/"),
        _L("Council of Europe — AI & human rights", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("Alan Turing Institute — policy & ethics", "https://www.turing.ac.uk/research/research-programmes/public-policy-programme"),
        _L("OECD.AI observatory", "https://oecd.ai/en"),
    ),
    "Economy & work": _pack(
        "Focus on **UK productivity, housing, fiscal policy, and regional inequality**.\n\n"
        "**Optional references:** "
        "[OBR — fiscal outlook](https://obr.uk/) · "
        "[IFS — publications](https://ifs.org.uk/publications) · "
        "[Resolution Foundation](https://www.resolutionfoundation.org/) · "
        "[ONS — regional economic indicators](https://www.ons.gov.uk/economy/economicoutputandproductivity/regionalaccounts)",
        _L("Bank of England — research", "https://www.bankofengland.co.uk/research"),
        _L("LSE Centre for Economic Performance", "https://www.lse.ac.uk/centre-for-economic-performance"),
        _L("UK Parliament — Treasury Committee", "https://committees.parliament.uk/committee/158/treasury-committee/"),
        _L("NIESR", "https://www.niesr.ac.uk/"),
    ),
    "Health & care": _pack(
        "Focus on **NHS structure, funding, access, and social care**.\n\n"
        "**Optional references:** "
        "[NHS England — statistics](https://www.england.nhs.uk/statistics/) · "
        "[Nuffield Trust](https://www.nuffieldtrust.org.uk/) · "
        "[The King's Fund](https://www.kingsfund.org.uk/) · "
        "[Health Foundation](https://www.health.org.uk/)",
        _L("Care Quality Commission", "https://www.cqc.org.uk/"),
        _L("NICE — guidance", "https://www.nice.org.uk/"),
        _L("UK Parliament — Health & Social Care Committee", "https://committees.parliament.uk/committee/81/health-and-social-care-committee/"),
        _L("WHO — European Region health systems", "https://www.who.int/europe/health-topics/health-systems"),
    ),
    "War, peace & security": _pack(
        "Normative questions about **UK force posture, alliances, and international law**.\n\n"
        "**Optional references:** "
        "[UK Ministry of Defence publications](https://www.gov.uk/government/organisations/ministry-of-defence) · "
        "[NATO — official texts](https://www.nato.int/cps/en/natohq/publications.htm) · "
        "[House of Commons Library — defence](https://commonslibrary.parliament.uk/topic/home-affairs/defence/) · "
        "[ICRC — international humanitarian law](https://www.icrc.org/en/war-and-law)",
        _L("IISS", "https://www.iiss.org/"),
        _L("RUSI", "https://rusi.org/"),
        _L("UN — Charter (full text)", "https://www.un.org/en/about-us/un-charter/full-text"),
        _L("European Council on Foreign Relations", "https://ecfr.eu/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **electoral systems, parliament, courts, and integrity**.\n\n"
        "**Optional references:** "
        "[Electoral Commission](https://www.electoralcommission.org.uk/) · "
        "[UCL Constitution Unit](https://constitution-unit.com/) · "
        "[UK Supreme Court judgments](https://www.supremecourt.uk/decided-cases) · "
        "[Venice Commission — opinions (Council of Europe)](https://www.venice.coe.int/)",
        _L("Electoral Reform Society", "https://www.electoral-reform.org.uk/"),
        _L("UK Parliament — Public Administration and Constitutional Affairs Committee (PACAC)", "https://committees.parliament.uk/committee/327/public-administration-and-constitutional-affairs-committee/"),
        _L("IDEA — global democracy data", "https://www.idea.int/"),
        _L("ACE — Electoral Knowledge Network", "https://aceproject.org/"),
    ),
    "Society & cohesion": _pack(
        "Vote on **policy design** — borders, asylum, integration, and anti-discrimination.\n\n"
        "**Optional references:** "
        "[Migration Advisory Committee](https://www.gov.uk/government/organisations/migration-advisory-committee) · "
        "[UK Home Office — immigration statistics](https://www.gov.uk/government/collections/immigration-system-statistics-year-ending) · "
        "[UNHCR — UK asylum facts](https://www.unhcr.org/uk/) · "
        "[EHRC — equality & human rights](https://www.equalityhumanrights.com/)",
        _L("ONS — migration statistics", "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration"),
        _L("IPPR", "https://www.ippr.org/"),
        _L("UK Parliament — Home Affairs Committee", "https://committees.parliament.uk/committee/83/home-affairs-committee/"),
        _L("Council of Europe — European Commission against Racism", "https://www.coe.int/en/web/european-commission-against-racism-and-intolerance"),
    ),
    "Education & future skills": _pack(
        "Focus on **access, funding, inspection, and parity across routes**.\n\n"
        "**Optional references:** "
        "[Department for Education](https://www.gov.uk/government/organisations/department-for-education) · "
        "[Ofsted](https://www.gov.uk/government/organisations/ofsted) · "
        "[IFS — education](https://ifs.org.uk/education) · "
        "[Education Policy Institute](https://epi.org.uk/)",
        _L("Sutton Trust", "https://www.suttontrust.com/"),
        _L("UCAS — data & analysis", "https://www.ucas.com/data-and-analysis"),
        _L("UK Parliament — Education Committee", "https://committees.parliament.uk/committee/203/education-committee/"),
        _L("OECD — Education at a Glance: UK", "https://www.oecd.org/education/education-at-a-glance/"),
    ),
}

# ---------------------------------------------------------------------------
# United States
# ---------------------------------------------------------------------------
_US: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **US federal climate policy**, EPA authority, and energy infrastructure.\n\n"
        "**Optional references:** "
        "[EPA — climate change](https://www.epa.gov/climate-change) · "
        "[Congressional Research Service reports (CRS)](https://www.congress.gov/crs-product/browse) · "
        "[NOAA Climate.gov](https://www.climate.gov/) · "
        "[EIA — energy data](https://www.eia.gov/)",
        _L("Resources for the Future", "https://www.rff.org/"),
        _L("National Academies — climate reports", "https://www.nationalacademies.org/topic/environment-and-environmental-studies/climate"),
        _L("CBO — climate-related economic analysis", "https://www.cbo.gov/topics/energy-and-natural-resources"),
        _L("UNFCCC — Paris Agreement", "https://unfccc.int/process-and-meetings/the-paris-agreement/the-paris-agreement"),
    ),
    "AI & technology": _pack(
        "Focus on **US federal tech policy** — antitrust, AI safety, Section 230, and research.\n\n"
        "**Optional references:** "
        "[FTC — competition & consumer protection](https://www.ftc.gov/) · "
        "[NIST — AI risk management framework](https://www.nist.gov/itl/ai-risk-management-framework) · "
        "[Congress.gov — AI legislation tracker](https://www.congress.gov/) · "
        "[GPO — US Code (e.g. 47 U.S.C. 230)](https://www.govinfo.gov/app/collection/uscode)",
        _L("GAO — technology assessments", "https://www.gao.gov/science-technology"),
        _L("EPIC — privacy & civil liberties", "https://epic.org/"),
        _L("Berkman Klein Center (Harvard)", "https://cyber.harvard.edu/"),
        _L("OECD.AI", "https://oecd.ai/en"),
    ),
    "Economy & work": _pack(
        "Structural questions on **taxes, wages, unions, and trade**.\n\n"
        "**Optional references:** "
        "[CBO](https://www.cbo.gov/) · "
        "[Bureau of Labor Statistics](https://www.bls.gov/) · "
        "[Census Bureau — income & poverty](https://www.census.gov/topics/income-poverty.html) · "
        "[Federal Reserve — economic research](https://www.federalreserve.gov/econres.htm)",
        _L("Economic Policy Institute", "https://www.epi.org/"),
        _L("Tax Policy Center", "https://www.taxpolicycenter.org/"),
        _L("ILO — US labour standards context", "https://www.ilo.org/global/lang--en/index.htm"),
        _L("World Bank — poverty & inequality data", "https://www.worldbank.org/en/topic/poverty"),
    ),
    "Health & care": _pack(
        "Focus on **coverage, cost, and public programmes**.\n\n"
        "**Optional references:** "
        "[CMS — Centers for Medicare & Medicaid Services](https://www.cms.gov/) · "
        "[HHS](https://www.hhs.gov/) · "
        "[CDC](https://www.cdc.gov/) · "
        "[Medicaid.gov](https://www.medicaid.gov/)",
        _L("Commonwealth Fund", "https://www.commonwealthfund.org/"),
        _L("KFF (Kaiser Family Foundation)", "https://www.kff.org/"),
        _L("NIH — research programmes", "https://www.nih.gov/"),
        _L("WHO — US health system comparisons", "https://www.who.int/data/gho/data/themes/topics/topic-details/GHO/universal-health-coverage"),
    ),
    "War, peace & security": _pack(
        "Questions on **US force posture, alliances, and war powers**.\n\n"
        "**Optional references:** "
        "[Department of Defense](https://www.defense.gov/) · "
        "[Congressional Research Service — defence](https://www.congress.gov/crs-product/browse?source=search&subject=National+Security) · "
        "[State Department](https://www.state.gov/) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en)",
        _L("SIPRI", "https://www.sipri.org/"),
        _L("Congressional Budget Office — defence", "https://www.cbo.gov/topics/national-security"),
        _L("ICRC — IHL databases", "https://ihl-databases.icrc.org/"),
        _L("United Nations Charter", "https://www.un.org/en/about-us/un-charter/full-text"),
    ),
    "Democracy & institutions": _pack(
        "Structural design — **elections, courts, money in politics**.\n\n"
        "**Optional references:** "
        "[Federal Election Commission](https://www.fec.gov/) · "
        "[Supreme Court of the United States](https://www.supremecourt.gov/) · "
        "[USA.gov — voting & elections](https://www.usa.gov/voting-and-elections) · "
        "[National Conference of State Legislatures](https://www.ncsl.org/)",
        _L("Brennan Center for Justice", "https://www.brennancenter.org/"),
        _L("Electoral Integrity Project", "https://www.electoralintegrityproject.com/"),
        _L("Campaign Legal Center", "https://campaignlegal.org/"),
        _L("V-Dem Institute", "https://www.v-dem.net/"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration, civil rights, and cohesion policy**.\n\n"
        "**Optional references:** "
        "[USCIS](https://www.uscis.gov/) · "
        "[DOJ Civil Rights Division](https://www.justice.gov/crt) · "
        "[Census — foreign-born population](https://www.census.gov/topics/population/foreign-born.html) · "
        "[UNHCR — resettlement data](https://www.unhcr.org/refugee-statistics)",
        _L("Migration Policy Institute", "https://www.migrationpolicy.org/"),
        _L("Pew Research Center", "https://www.pewresearch.org/topic/international-affairs/"),
        _L("National Academies — integration report", "https://www.nationalacademies.org/our-work/integration-of-immigrants-into-us-society-a-behavioral-economic-perspective"),
        _L("OHCHR — core human rights treaties", "https://www.ohchr.org/en/core-international-human-rights-instruments-and-their-monitoring-bodies"),
    ),
    "Education & future skills": _pack(
        "Focus on **funding equity, access, and standards**.\n\n"
        "**Optional references:** "
        "[Department of Education](https://www.ed.gov/) · "
        "[NCES — National Center for Education Statistics](https://nces.ed.gov/) · "
        "[Civil Rights Data Collection](https://ocrdata.ed.gov/) · "
        "[Global Partnership for Education](https://www.globalpartnership.org/)",
        _L("Education Trust", "https://edtrust.org/"),
        _L("Brookings — Brown Center on Education", "https://www.brookings.edu/brown-center-on-education-policy/"),
        _L("NAACP Legal Defense Fund — education equity", "https://www.naacpldf.org/"),
        _L("OECD — Education at a Glance", "https://www.oecd.org/education/education-at-a-glance/"),
    ),
}

# ---------------------------------------------------------------------------
# Netherlands
# ---------------------------------------------------------------------------
_NL: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **Dutch climate & energy policy**, North Sea wind, nitrogen rules, and EU alignment.\n\n"
        "**Optional references:** "
        "[Government.nl — climate](https://www.government.nl/topics/climate-change) · "
        "[KNMI — climate scenarios](https://www.knmi.nl/over-knmi/climate) · "
        "[PBL Netherlands Environmental Assessment Agency](https://www.pbl.nl/en) · "
        "[European Environment Agency](https://www.eea.europa.eu/en)",
        _L("Statistics Netherlands (CBS)", "https://www.cbs.nl/en-gb"),
        _L("House of Representatives — documents", "https://www.tweedekamer.nl/kamerstukken"),
        _L("CPB Netherlands Bureau for Economic Policy Analysis", "https://www.cpb.nl/en"),
        _L("UNFCCC — Paris Agreement", "https://unfccc.int/process-and-meetings/the-paris-agreement/the-paris-agreement"),
    ),
    "AI & technology": _pack(
        "Consider **EU digital rules**, national implementation, and public-sector AI use.\n\n"
        "**Optional references:** "
        "[Government.nl — artificial intelligence](https://www.government.nl/topics/artificial-intelligence) · "
        "[Dutch Data Protection Authority (AP)](https://autoriteitpersoonsgegevens.nl/en) · "
        "[EUR-Lex — EU AI Act](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689) · "
        "[Council of Europe — AI & human rights](https://www.coe.int/en/web/artificial-intelligence)",
        _L("Tweede Kamer — digital affairs committees", "https://www.tweedekamer.nl/"),
        _L("OECD.AI", "https://oecd.ai/en"),
        _L("European Data Protection Board", "https://edpb.europa.eu/edpb_en"),
        _L("NIST — AI RMF (international benchmark)", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ),
    "Economy & work": _pack(
        "Focus on **housing, pensions, labour markets, and euro-area spillovers**.\n\n"
        "**Optional references:** "
        "[CPB](https://www.cpb.nl/en) · "
        "[De Nederlandsche Bank (DNB)](https://www.dnb.nl/en/) · "
        "[CBS — economy](https://www.cbs.nl/en-gb/figures/detail/80505eng) · "
        "[Eurostat](https://ec.europa.eu/eurostat)",
        _L("SER — Social and Economic Council", "https://www.ser.nl/en"),
        _L("ILO — Netherlands profile", "https://www.ilo.org/countries/netherlands/lang--en/index.htm"),
        _L("European Commission — economic governance", "https://economy-finance.ec.europa.eu/economic-governance_en"),
        _L("World Bank — open data", "https://data.worldbank.org/"),
    ),
    "Health & care": _pack(
        "Focus on **long-term care financing, access, and EU health competences**.\n\n"
        "**Optional references:** "
        "[RIVM — National Institute for Public Health and the Environment](https://www.rivm.nl/en) · "
        "[Zorginstituut Nederland](https://www.zorginstituutnederland.nl/en) · "
        "[WHO Regional Office for Europe](https://www.who.int/europe) · "
        "[OECD — Health at a Glance: Europe](https://www.oecd.org/health/health-at-a-glance-europe.htm)",
        _L("Dutch Healthcare Authority (NZa)", "https://english.nza.nl/"),
        _L("Ministry of Health, Welfare and Sport", "https://www.government.nl/ministries/ministry-of-health-welfare-and-sport"),
        _L("Eurostat — health", "https://ec.europa.eu/eurostat/web/health"),
        _L("OECD — Health at a Glance: Europe", "https://www.oecd.org/health/health-at-a-glance-europe.htm"),
    ),
    "War, peace & security": _pack(
        "Normative questions on **NATO commitments, EU defence, and crisis deployment**.\n\n"
        "**Optional references:** "
        "[Ministry of Defence (Defensie.nl)](https://www.defensie.nl/english) · "
        "[NATO](https://www.nato.int/) · "
        "[House of Representatives — Defence committee](https://www.tweedekamer.nl/kamerleden/commissies) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en)",
        _L("Clingendael Institute", "https://www.clingendael.org/"),
        _L("ICRC — international humanitarian law", "https://www.icrc.org/en/war-and-law"),
        _L("UN Charter", "https://www.un.org/en/about-us/un-charter/full-text"),
        _L("SIPRI", "https://www.sipri.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **elections, coalition governance, courts**.\n\n"
        "**Optional references:** "
        "[Electoral Council (Kiesraad)](https://www.kiesraad.nl/en) · "
        "[House of Representatives](https://www.tweedekamer.nl/en) · "
        "[Council of State (Raad van State)](https://www.raadvanstate.nl/en) · "
        "[Venice Commission](https://www.venice.coe.int/)",
        _L("Dutch Electoral Council publications", "https://www.kiesraad.nl/en/news-and-publications"),
        _L("IDEA — Netherlands", "https://www.idea.int/data-tools/data/country-profiles"),
        _L("ACE — Electoral Knowledge Network", "https://aceproject.org/"),
        _L("European Commission — rule of law", "https://commission.europa.eu/topics/justice-and-fundamental-rights_en"),
    ),
    "Society & cohesion": _pack(
        "Vote on **asylum, integration, and anti-discrimination** policy design.\n\n"
        "**Optional references:** "
        "[IND — Immigration and Naturalisation Service](https://ind.nl/en) · "
        "[CBS — migration statistics](https://www.cbs.nl/en-gb/figures/subjects/society/population/migration) · "
        "[UNHCR — Netherlands](https://www.unhcr.org/nl/) · "
        "[Council of Europe — ECRI](https://www.coe.int/en/web/european-commission-against-racism-and-intolerance)",
        _L("Netherlands Institute for Human Rights", "https://www.mensenrechten.nl/english"),
        _L("EU Asylum Agency", "https://euaa.europa.eu/"),
        _L("OHCHR — core treaties", "https://www.ohchr.org/en/core-international-human-rights-instruments-and-their-monitoring-bodies"),
        _L("European Commission — migration & home affairs", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
    ),
    "Education & future skills": _pack(
        "Focus on **vocational pathways, teacher supply, and equity**.\n\n"
        "**Optional references:** "
        "[Ministry of Education, Culture and Science](https://www.government.nl/ministries/ministry-of-education-culture-and-science) · "
        "[DUO — student finance & data](https://duo.nl/particulier/) · "
        "[Education Inspectorate](https://english.onderwijsinspectie.nl/) · "
        "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/)",
        _L("Statistics Netherlands — education", "https://www.cbs.nl/en-gb/figures/subjects/education"),
        _L("European Commission — education & training", "https://education.ec.europa.eu/"),
        _L("UNESCO — education data", "https://uis.unesco.org/"),
        _L("Eurostat — education & training", "https://ec.europa.eu/eurostat/web/education-and-training"),
    ),
}

# ---------------------------------------------------------------------------
# Ireland
# ---------------------------------------------------------------------------
_IE: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **Irish climate targets**, agriculture emissions, and energy transition.\n\n"
        "**Optional references:** "
        "[gov.ie — climate action](https://www.gov.ie/en/policy-information/climate-action/) · "
        "[EPA Ireland — climate change](https://www.epa.ie/our-services/monitoring--assessment/climate-change/) · "
        "[SEAI — Sustainable Energy Authority](https://www.seai.ie/) · "
        "[Met Éireann — climate](https://www.met.ie/climate)",
        _L("Central Statistics Office — environment", "https://www.cso.ie/en/statistics/environment/"),
        _L("Oireachtas — climate legislation", "https://www.oireachtas.ie/en/"),
        _L("European Environment Agency", "https://www.eea.europa.eu/en"),
        _L("UNFCCC", "https://unfccc.int/"),
    ),
    "AI & technology": _pack(
        "Consider **EU digital law**, national data protection, and public-sector digitisation.\n\n"
        "**Optional references:** "
        "[Data Protection Commission (Ireland)](https://www.dataprotection.ie/) · "
        "[gov.ie — digital strategy](https://www.gov.ie/en/publication/digital-ireland/) · "
        "[EUR-Lex — EU AI Act](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689) · "
        "[European Data Protection Board](https://edpb.europa.eu/edpb_en)",
        _L("Oireachtas — committees", "https://www.oireachtas.ie/en/committees/"),
        _L("OECD.AI", "https://oecd.ai/en"),
        _L("Council of Europe — AI", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("NIST — AI RMF", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ),
    "Economy & work": _pack(
        "Focus on **housing, productivity, and EU economic ties**.\n\n"
        "**Optional references:** "
        "[Central Bank of Ireland — research](https://www.centralbank.ie/research) · "
        "[CSO — national accounts](https://www.cso.ie/en/statistics/nationalaccounts/) · "
        "[Department of Finance](https://www.gov.ie/en/organisation/department-of-finance/) · "
        "[Eurostat](https://ec.europa.eu/eurostat)",
        _L("ESRI — Economic & Social Research Institute", "https://www.esri.ie/"),
        _L("European Commission — Ireland economy", "https://economy-finance.ec.europa.eu/economic-surveillance-eu-member-states/ireland_en"),
        _L("OECD — Ireland economic surveys", "https://www.oecd.org/ireland/"),
        _L("ILO", "https://www.ilo.org/"),
    ),
    "Health & care": _pack(
        "Focus on **HSE capacity, Sláintecare reforms, and access**.\n\n"
        "**Optional references:** "
        "[HSE — Health Service Executive](https://www.hse.ie/eng/) · "
        "[Department of Health](https://www.gov.ie/en/organisation/department-of-health/) · "
        "[HIQA](https://www.hiqa.ie/) · "
        "[WHO Europe](https://www.who.int/europe)",
        _L("Health Research Board", "https://www.hrb.ie/"),
        _L("Oireachtas — Health committee", "https://www.oireachtas.ie/en/committees/32/health/"),
        _L("Eurostat — health", "https://ec.europa.eu/eurostat/web/health"),
        _L("OECD — Health at a Glance: Europe", "https://www.oecd.org/health/health-at-a-glance-europe.htm"),
    ),
    "War, peace & security": _pack(
        "Questions on **neutrality tradition, UN peacekeeping, and collective security**.\n\n"
        "**Optional references:** "
        "[Defence Forces Ireland](https://www.military.ie/en/) · "
        "[Department of Foreign Affairs](https://www.dfa.ie/) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en) · "
        "[NATO (partnership context)](https://www.nato.int/cps/en/natohq/topics_49212.htm)",
        _L("ICRC", "https://www.icrc.org/"),
        _L("Oireachtas — Foreign affairs & defence", "https://www.oireachtas.ie/en/committees/33/foreign-affairs-and-defence/"),
        _L("UN Charter", "https://www.un.org/en/about-us/un-charter/full-text"),
        _L("IISS", "https://www.iiss.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **Dáil, Seanad, courts, and integrity**.\n\n"
        "**Optional references:** "
        "[Electoral Commission Ireland](https://www.electoralcommission.ie/) · "
        "[Oireachtas](https://www.oireachtas.ie/en/) · "
        "[Courts Service](https://www.courts.ie/) · "
        "[Venice Commission](https://www.venice.coe.int/)",
        _L("Standards in Public Office Commission", "https://www.sipo.ie/"),
        _L("IDEA", "https://www.idea.int/"),
        _L("Council of Europe — GRECO", "https://www.coe.int/en/web/greco"),
        _L("European Commission — rule of law", "https://commission.europa.eu/topics/justice-and-fundamental-rights_en"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration, integration, and equality** frameworks.\n\n"
        "**Optional references:** "
        "[Irish Naturalisation and Immigration Service](https://www.irishimmigration.ie/) · "
        "[CSO — population & migration](https://www.cso.ie/en/statistics/population/) · "
        "[UNHCR — Ireland](https://www.unhcr.org/ie/) · "
        "[Irish Human Rights and Equality Commission](https://www.ihrec.ie/)",
        _L("European Commission — migration & home affairs", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("Oireachtas — Justice committee", "https://www.oireachtas.ie/en/committees/9/justice/"),
        _L("EU Asylum Agency", "https://euaa.europa.eu/"),
    ),
    "Education & future skills": _pack(
        "Focus on **funding, access, and tertiary pathways**.\n\n"
        "**Optional references:** "
        "[Department of Education](https://www.gov.ie/en/organisation/department-of-education/) · "
        "[Higher Education Authority](https://hea.ie/) · "
        "[CSO — education](https://www.cso.ie/en/statistics/education/) · "
        "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/)",
        _L("Education Policy Institute (international comparator)", "https://epi.org.uk/"),
        _L("Eurostat — education", "https://ec.europa.eu/eurostat/web/education-and-training"),
        _L("UNESCO UIS", "https://uis.unesco.org/"),
        _L("European Commission — education", "https://education.ec.europa.eu/"),
    ),
}

# ---------------------------------------------------------------------------
# Germany
# ---------------------------------------------------------------------------
_DE: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **Energiewende**, industry transition, and EU climate law.\n\n"
        "**Optional references:** "
        "[BMUV — Federal Ministry for the Environment](https://www.bmuv.de/en) · "
        "[Umweltbundesamt (UBA)](https://www.umweltbundesamt.de/en) · "
        "[IPCC](https://www.ipcc.ch/) · "
        "[Destatis — environment](https://www.destatis.de/EN/Themes/Society-Environment/Environment/_node.html)",
        _L("German Environment Agency — climate", "https://www.umweltbundesamt.de/en/topics/climate-energy"),
        _L("Bundestag — Environment Committee", "https://www.bundestag.de/en/committees/a21"),
        _L("European Environment Agency", "https://www.eea.europa.eu/en"),
        _L("UNFCCC", "https://unfccc.int/"),
    ),
    "AI & technology": _pack(
        "Consider **EU AI Act implementation**, research policy, and fundamental rights.\n\n"
        "**Optional references:** "
        "[Federal Government — AI strategy overview](https://www.bundesregierung.de/breg-en/chancellor-artificial-intelligence-2359410) · "
        "[BfDI — Federal Commissioner for Data Protection](https://www.bfdi.bund.de/EN/Home/home_node.html) · "
        "[EUR-Lex — EU AI Act](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689) · "
        "[BSI — Federal Office for Information Security](https://www.bsi.bund.de/EN/Themen/Unternehmen-und-Organisationen/Informationen-und-Empfehlungen/Kuenstliche-Intelligenz/kuenstliche-intelligenz_node.html)",
        _L("Bundestag — Digital committee", "https://www.bundestag.de/en/committees/a14"),
        _L("OECD.AI", "https://oecd.ai/en"),
        _L("Council of Europe — AI", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("ENISA — EU cybersecurity agency", "https://www.enisa.europa.eu/"),
    ),
    "Economy & work": _pack(
        "Structural questions on **industry, energy prices, demographics, and federal finances**.\n\n"
        "**Optional references:** "
        "[Deutsche Bundesbank — research](https://www.bundesbank.de/en/research) · "
        "[Destatis](https://www.destatis.de/EN/Home/_node.html) · "
        "[Federal Ministry of Finance](https://www.bundesfinanzministerium.de/Web/EN/home/home.html) · "
        "[Eurostat](https://ec.europa.eu/eurostat)",
        _L("ifo Institute", "https://www.ifo.de/en"),
        _L("DIW Berlin", "https://www.diw.de/en"),
        _L("European Commission — Germany", "https://economy-finance.ec.europa.eu/economic-surveillance-eu-member-states/germany_en"),
        _L("IMF — Germany", "https://www.imf.org/en/Countries/DEU"),
    ),
    "Health & care": _pack(
        "Focus on **statutory health insurance, hospital capacity, and digital health**.\n\n"
        "**Optional references:** "
        "[Federal Ministry of Health (BMG)](https://www.bundesgesundheitsministerium.de/en.html) · "
        "[Robert Koch Institute (RKI)](https://www.rki.de/EN/Home/homepage_node.html) · "
        "[G-BA — Federal Joint Committee](https://www.g-ba.de/english/) · "
        "[WHO Europe](https://www.who.int/europe)",
        _L("Bundestag — Health committee", "https://www.bundestag.de/en/committees/a18"),
        _L("Eurostat — health", "https://ec.europa.eu/eurostat/web/health"),
        _L("OECD — Health at a Glance: Europe", "https://www.oecd.org/health/health-at-a-glance-europe.htm"),
        _L("European Observatory on Health Systems and Policies", "https://eurohealthobservatory.who.int/"),
    ),
    "War, peace & security": _pack(
        "Normative questions on **Zeitenwende**, NATO, and crisis response.\n\n"
        "**Optional references:** "
        "[Federal Ministry of Defence](https://www.bmvg.de/en) · "
        "[NATO](https://www.nato.int/) · "
        "[Bundestag — Defence Committee](https://www.bundestag.de/en/committees/a06) · "
        "[UN Charter](https://www.un.org/en/about-us/un-charter/full-text)",
        _L("SWP — German Institute for International and Security Affairs", "https://www.swp-berlin.org/en/"),
        _L("ICRC", "https://www.icrc.org/"),
        _L("SIPRI", "https://www.sipri.org/"),
        _L("UN Peacekeeping", "https://peacekeeping.un.org/en"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **Bundestag, Bundesrat, Federal Constitutional Court**.\n\n"
        "**Optional references:** "
        "[Federal Returning Officer](https://www.bundeswahlleiter.de/en/) · "
        "[Bundestag](https://www.bundestag.de/en) · "
        "[Federal Constitutional Court (BVerfG)](https://www.bundesverfassungsgericht.de/SharedDocs/Startseite/EN/Home/home_node.html) · "
        "[Venice Commission](https://www.venice.coe.int/)",
        _L("IDEA", "https://www.idea.int/"),
        _L("OSCE/ODIHR election reports", "https://www.osce.org/odihr/elections"),
        _L("Council of Europe — GRECO", "https://www.coe.int/en/web/greco"),
        _L("ACE Project", "https://aceproject.org/"),
    ),
    "Society & cohesion": _pack(
        "Vote on **migration integration, citizenship, and anti-discrimination**.\n\n"
        "**Optional references:** "
        "[BAMF — Federal Office for Migration and Refugees](https://www.bamf.de/EN/Home/home_node.html) · "
        "[Destatis — migration](https://www.destatis.de/EN/Themes/Society-Environment/Population/Migration-Integration/_node.html) · "
        "[UNHCR Germany](https://www.unhcr.org/de/) · "
        "[Federal Anti-Discrimination Agency](https://www.antidiskriminierungsstelle.de/en)",
        _L("European Commission — migration & home affairs", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("EU Fundamental Rights Agency", "https://fra.europa.eu/en"),
        _L("Council of Europe — ECRI", "https://www.coe.int/en/web/european-commission-against-racism-and-intolerance"),
    ),
    "Education & future skills": _pack(
        "Focus on **vocational (dual) training, digital skills, and equity**.\n\n"
        "**Optional references:** "
        "[Federal Ministry of Education and Research (BMBF)](https://www.bmbf.de/bmbf/en/home/home_node.html) · "
        "[KMK — Standing Conference of Ministers](https://www.kmk.org/kmk/information-in-english.html) · "
        "[Destatis — education](https://www.destatis.de/EN/Themes/Society-Environment/Education-Research-Culture/Education/_node.html) · "
        "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/)",
        _L("Eurostat — education", "https://ec.europa.eu/eurostat/web/education-and-training"),
        _L("UNESCO UIS", "https://uis.unesco.org/"),
        _L("European Commission — education", "https://education.ec.europa.eu/"),
        _L("CEDEFOP — vocational education & training", "https://www.cedefop.europa.eu/en"),
    ),
}

# ---------------------------------------------------------------------------
# France
# ---------------------------------------------------------------------------
_FR: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **French climate planning**, nuclear-renewables mix, and EU law.\n\n"
        "**Optional references:** "
        "[Ministère de la Transition écologique](https://www.ecologie.gouv.fr/) · "
        "[ADEME](https://www.ademe.fr/en) · "
        "[Météo-France — climate](https://meteofrance.com/climat) · "
        "[IPCC](https://www.ipcc.ch/)",
        _L("INSEE — environment statistics", "https://www.insee.fr/en/metadonnees/source/serie/2220"),
        _L("Assemblée nationale — environment texts", "https://www.assemblee-nationale.fr/dyn/les-commissions"),
        _L("European Environment Agency", "https://www.eea.europa.eu/en"),
        _L("UNFCCC", "https://unfccc.int/"),
    ),
    "AI & technology": _pack(
        "Consider **EU digital sovereignty**, CNIL enforcement, and sector regulation.\n\n"
        "**Optional references:** "
        "[CNIL](https://www.cnil.fr/en) · "
        "[ANSSI](https://www.ssi.gouv.fr/en/) · "
        "[EUR-Lex — EU AI Act](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX:32024R1689) · "
        "[Commission nationale du débat public](https://www.debatpublic.fr/en)",
        _L("Assemblée nationale — digital committee work", "https://www.assemblee-nationale.fr/dyn/les-commissions"),
        _L("OECD.AI", "https://oecd.ai/en"),
        _L("Council of Europe — AI", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("EDPB", "https://edpb.europa.eu/edpb_en"),
    ),
    "Economy & work": _pack(
        "Structural questions on **pensions, labour law, debt, and euro-area policy**.\n\n"
        "**Optional references:** "
        "[INSEE](https://www.insee.fr/en/home) · "
        "[Banque de France — research](https://www.banque-france.fr/en/statistics) · "
        "[Cour des comptes](https://www.ccomptes.fr/en) · "
        "[Eurostat](https://ec.europa.eu/eurostat)",
        _L("French Treasury (Direction générale du Trésor) — reports", "https://www.tresor.economie.gouv.fr/"),
        _L("OECD — France economic surveys", "https://www.oecd.org/france/"),
        _L("European Commission — France", "https://economy-finance.ec.europa.eu/economic-surveillance-eu-member-states/france_en"),
        _L("ILO", "https://www.ilo.org/"),
    ),
    "Health & care": _pack(
        "Focus on **access, hospital financing, and prevention**.\n\n"
        "**Optional references:** "
        "[Ministère de la Santé et de la Prévention](https://sante.gouv.fr/) · "
        "[HAS — Haute Autorité de santé](https://www.has-sante.fr/) · "
        "[DREES — statistics](https://drees.solidarites-sante.gouv.fr/etudes-et-statistiques/publications/) · "
        "[WHO Europe](https://www.who.int/europe)",
        _L("Santé publique France", "https://www.santepubliquefrance.fr/en"),
        _L("Eurostat — health", "https://ec.europa.eu/eurostat/web/health"),
        _L("OECD — Health at a Glance: Europe", "https://www.oecd.org/health/health-at-a-glance-europe.htm"),
        _L("European Observatory on Health Systems and Policies", "https://eurohealthobservatory.who.int/"),
    ),
    "War, peace & security": _pack(
        "Questions on **EU defence initiatives, NATO, and crisis deployment**.\n\n"
        "**Optional references:** "
        "[Ministère des Armées](https://www.defense.gouv.fr/english) · "
        "[NATO](https://www.nato.int/) · "
        "[Assemblée nationale — Defence committee](https://www.assemblee-nationale.fr/dyn/les-commissions) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en)",
        _L("IFRI", "https://www.ifri.org/en"),
        _L("ICRC", "https://www.icrc.org/"),
        _L("UN Charter", "https://www.un.org/en/about-us/un-charter/full-text"),
        _L("SIPRI", "https://www.sipri.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **Fifth Republic institutions, elections, and oversight**.\n\n"
        "**Optional references:** "
        "[Conseil constitutionnel](https://www.conseil-constitutionnel.fr/english) · "
        "[Assemblée nationale](https://www.assemblee-nationale.fr/en) · "
        "[Conseil d'État](https://english.conseil-etat.fr/) · "
        "[Venice Commission](https://www.venice.coe.int/)",
        _L("Commission nationale de l'informatique et des libertés (see CNIL)", "https://www.cnil.fr/en"),
        _L("IDEA", "https://www.idea.int/"),
        _L("OSCE/ODIHR", "https://www.osce.org/odihr/elections"),
        _L("European Commission — rule of law", "https://commission.europa.eu/topics/justice-and-fundamental-rights_en"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration, integration, and non-discrimination**.\n\n"
        "**Optional references:** "
        "[Ministère de l'Intérieur — immigration & asylum](https://www.interieur.gouv.fr/Actualites/L-actu-du-Ministere/Immigration-et-asile) · "
        "[OFII](https://www.ofii.fr/en/) · "
        "[UNHCR France](https://www.unhcr.org/fr-fr) · "
        "[Défenseur des droits](https://www.defenseurdesdroits.fr/en)",
        _L("INSEE — population & migration", "https://www.insee.fr/en/statistics/2011547"),
        _L("European Commission — migration & home affairs", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("Council of Europe — ECRI", "https://www.coe.int/en/web/european-commission-against-racism-and-intolerance"),
    ),
    "Education & future skills": _pack(
        "Focus on **teacher recruitment, regional gaps, and vocational routes**.\n\n"
        "**Optional references:** "
        "[Ministère de l'Éducation nationale](https://www.education.gouv.fr/en) · "
        "[DEPP — statistics](https://www.education.gouv.fr/la-depu-une-direction-pour-le-succes-de-tous-les-eleves-4297) · "
        "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/) · "
        "[UNESCO UIS](https://uis.unesco.org/)",
        _L("Conseil supérieur des programmes", "https://www.education.gouv.fr/le-csp-11406"),
        _L("Eurostat — education", "https://ec.europa.eu/eurostat/web/education-and-training"),
        _L("European Commission — education", "https://education.ec.europa.eu/"),
        _L("CEDEFOP", "https://www.cedefop.europa.eu/en"),
    ),
}

# ---------------------------------------------------------------------------
# Canada
# ---------------------------------------------------------------------------
_CA: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **federal–provincial climate policy**, carbon pricing, and energy transitions.\n\n"
        "**Optional references:** "
        "[Environment and Climate Change Canada](https://www.canada.ca/en/environment-climate-change.html) · "
        "[Natural Resources Canada — energy](https://www.nrcan.gc.ca/energy) · "
        "[IPCC](https://www.ipcc.ch/) · "
        "[Statistics Canada — environment](https://www.statcan.gc.ca/en/subjects-start/environment)",
        _L("Parliament of Canada — LEGISinfo", "https://www.parl.ca/LegisInfo/en/laws-by-parliament"),
        _L("Office of the Parliamentary Budget Officer", "https://www.pbo-dpb.ca/en"),
        _L("UNFCCC", "https://unfccc.int/"),
        _L("International Energy Agency — Canada", "https://www.iea.org/countries/canada"),
    ),
    "AI & technology": _pack(
        "Focus on **privacy law (PIPEDA), AI governance, and competition**.\n\n"
        "**Optional references:** "
        "[ISED — Innovation, Science and Economic Development](https://ised-isde.canada.ca/site/ised/en) · "
        "[Office of the Privacy Commissioner](https://www.priv.gc.ca/en/) · "
        "[Treasury Board Directive on Automated Decision-Making](https://www.canada.ca/en/government/system/digital-government/digital-government-modernization/automated-decision-making.html) · "
        "[OECD.AI](https://oecd.ai/en)",
        _L("CIRA — Canadian Internet Policy", "https://www.cira.ca/"),
        _L("EUR-Lex — EU AI Act (comparative context)", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689"),
        _L("NIST — AI RMF", "https://www.nist.gov/itl/ai-risk-management-framework"),
        _L("Council of Europe — AI", "https://www.coe.int/en/web/artificial-intelligence"),
    ),
    "Economy & work": _pack(
        "Structural questions on **housing, productivity, and trade**.\n\n"
        "**Optional references:** "
        "[Department of Finance Canada](https://www.canada.ca/en/department-finance.html) · "
        "[Bank of Canada — research](https://www.bankofcanada.ca/research/) · "
        "[Statistics Canada — labour & income](https://www.statcan.gc.ca/en/subjects-start/labour) · "
        "[Parliamentary Budget Officer — reports](https://www.pbo-dpb.ca/en)",
        _L("International Monetary Fund — Canada", "https://www.imf.org/en/Countries/CAN"),
        _L("OECD — Canada", "https://www.oecd.org/canada/"),
        _L("ILO", "https://www.ilo.org/"),
        _L("World Bank — open data", "https://data.worldbank.org/country/canada"),
    ),
    "Health & care": _pack(
        "Focus on **federal funding, provincial delivery, and access**.\n\n"
        "**Optional references:** "
        "[Health Canada](https://www.canada.ca/en/health-canada.html) · "
        "[Public Health Agency of Canada](https://www.canada.ca/en/public-health.html) · "
        "[CIHI — Canadian Institute for Health Information](https://www.cihi.ca/en) · "
        "[WHO](https://www.who.int/)",
        _L("Canadian Medical Association — health policy resources", "https://www.cma.ca/"),
        _L("Parliament of Canada — Health committee", "https://www.ourcommons.ca/Committees/en/HESA"),
        _L("OECD — Health at a Glance", "https://www.oecd.org/health/health-at-a-glance.htm"),
        _L("Commonwealth Fund — international comparisons", "https://www.commonwealthfund.org/international-health-policy-center"),
    ),
    "War, peace & security": _pack(
        "Questions on **alliances, peacekeeping, and defence procurement**.\n\n"
        "**Optional references:** "
        "[National Defence](https://www.canada.ca/en/department-national-defence.html) · "
        "[Global Affairs Canada](https://www.international.gc.ca/) · "
        "[NATO](https://www.nato.int/) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en)",
        _L("Parliament of Canada — National Defence committee", "https://www.ourcommons.ca/Committees/en/NDDN"),
        _L("ICRC", "https://www.icrc.org/"),
        _L("UN Charter", "https://www.un.org/en/about-us/un-charter/full-text"),
        _L("SIPRI", "https://www.sipri.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **elections, courts, Charter rights**.\n\n"
        "**Optional references:** "
        "[Elections Canada](https://www.elections.ca/) · "
        "[Parliament of Canada](https://www.parl.ca/) · "
        "[Supreme Court of Canada judgments](https://www.scc-csc.ca/case-dossier/index-eng.aspx) · "
        "[Commissioner of Canada Elections](https://www.cef-cfe.gc.ca/index-eng.html)",
        _L("Canadian Judicial Council", "https://cjc-ccm.ca/en"),
        _L("IDEA", "https://www.idea.int/"),
        _L("OSCE/ODIHR", "https://www.osce.org/odihr/elections"),
        _L("Venice Commission", "https://www.venice.coe.int/"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration levels, settlement, and human rights**.\n\n"
        "**Optional references:** "
        "[IRCC — Immigration, Refugees and Citizenship Canada](https://www.canada.ca/en/immigration-refugees-citizenship.html) · "
        "[Statistics Canada — immigration](https://www.statcan.gc.ca/en/subjects-start/immigration_and_ethnocultural_diversity) · "
        "[UNHCR Canada](https://www.unhcr.org/ca/) · "
        "[Canadian Human Rights Commission](https://www.chrc-ccdp.gc.ca/en)",
        _L("Parliament of Canada — Citizenship and Immigration committee", "https://www.ourcommons.ca/Committees/en/CIMM"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("European Commission — migration (comparative)", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
        _L("Migration Policy Institute", "https://www.migrationpolicy.org/"),
    ),
    "Education & future skills": _pack(
        "Focus on **Indigenous education equity, funding, and PSE access**.\n\n"
        "**Optional references:** "
        "[Indigenous Services Canada — education](https://www.sac-isc.gc.ca/eng/1100100033682/1534957527982) · "
        "[CMEC — Council of Ministers of Education](https://www.cmec.ca/) · "
        "[Statistics Canada — education](https://www.statcan.gc.ca/en/subjects-start/education_training_and_learning) · "
        "[OECD — Education at a Glance](https://www.oecd.org/education/education-at-a-glance/)",
        _L("Parliament of Canada — Indigenous and Northern Affairs committee", "https://www.ourcommons.ca/Committees/en/INAN"),
        _L("UNESCO UIS", "https://uis.unesco.org/"),
        _L("Eurostat — education (comparative)", "https://ec.europa.eu/eurostat/web/education-and-training"),
        _L("Education International — research hub", "https://www.ei-ie.org/en/issue/detail/169/research"),
    ),
}

# ---------------------------------------------------------------------------
# Singapore
# ---------------------------------------------------------------------------
_SG: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **city-state constraints**, regional haze, and low-carbon transition.\n\n"
        "**Optional references:** "
        "[National Environment Agency (NEA)](https://www.nea.gov.sg/) · "
        "[MSE — Ministry of Sustainability and the Environment](https://www.mse.gov.sg/) · "
        "[IPCC](https://www.ipcc.ch/) · "
        "[UNFCCC](https://unfccc.int/)",
        _L("Singapore Department of Statistics", "https://www.singstat.gov.sg/"),
        _L("Energy Market Authority", "https://www.ema.gov.sg/"),
        _L("IEA — Singapore", "https://www.iea.org/countries/singapore"),
        _L("ASEAN", "https://asean.org/"),
    ),
    "AI & technology": _pack(
        "Consider **model AI governance**, personal data protection, and digital economy rules.\n\n"
        "**Optional references:** "
        "[IMDA — Infocomm Media Development Authority](https://www.imda.gov.sg/) · "
        "[PDPC — Personal Data Protection Commission](https://www.pdpc.gov.sg/) · "
        "[Smart Nation Singapore](https://www.smartnation.gov.sg/) · "
        "[OECD.AI](https://oecd.ai/en)",
        _L("Parliament of Singapore — bills & debates", "https://www.parliament.gov.sg/"),
        _L("UNESCO — AI ethics recommendation", "https://www.unesco.org/en/artificial-intelligence/recommendation-ethics"),
        _L("Council of Europe — AI (regional comparator)", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("NIST — AI RMF", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ),
    "Economy & work": _pack(
        "Structural questions on **openness, productivity, and inequality**.\n\n"
        "**Optional references:** "
        "[MTI — Ministry of Trade and Industry](https://www.mti.gov.sg/) · "
        "[Monetary Authority of Singapore (MAS)](https://www.mas.gov.sg/) · "
        "[SingStat](https://www.singstat.gov.sg/) · "
        "[World Bank — Singapore](https://data.worldbank.org/country/singapore)",
        _L("ILO", "https://www.ilo.org/"),
        _L("OECD — Singapore", "https://www.oecd.org/singapore/"),
        _L("IMF — Singapore", "https://www.imf.org/en/Countries/SGP"),
        _L("WTO", "https://www.wto.org/"),
    ),
    "Health & care": _pack(
        "Focus on **Medisave/Medishield design, ageing, and surge capacity**.\n\n"
        "**Optional references:** "
        "[MOH — Ministry of Health](https://www.moh.gov.sg/) · "
        "[Health Promotion Board](https://www.hpb.gov.sg/) · "
        "[WHO Western Pacific Regional Office](https://www.who.int/westernpacific) · "
        "[OECD — Health at a Glance: Asia/Pacific](https://www.oecd.org/health/health-at-a-glance-asia-pacific-23150130.htm)",
        _L("SingStat — health statistics", "https://www.singstat.gov.sg/find-data/search-by-theme/health"),
        _L("National Centre for Infectious Diseases", "https://www.ncid.sg/"),
        _L("Parliament of Singapore", "https://www.parliament.gov.sg/"),
        _L("World Bank — health expenditure data", "https://data.worldbank.org/indicator/SH.XPD.CHEX.GD.ZS"),
    ),
    "War, peace & security": _pack(
        "Questions on **defence posture, maritime security, and multilateralism**.\n\n"
        "**Optional references:** "
        "[MINDEF Singapore](https://www.mindef.gov.sg/) · "
        "[MFA — Ministry of Foreign Affairs](https://www.mfa.gov.sg/) · "
        "[UN Charter](https://www.un.org/en/about-us/un-charter/full-text) · "
        "[ASEAN](https://asean.org/)",
        _L("IISS", "https://www.iiss.org/"),
        _L("UN Peacekeeping", "https://peacekeeping.un.org/en"),
        _L("ICRC", "https://www.icrc.org/"),
        _L("SIPRI", "https://www.sipri.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional context — **election law, parliament, and integrity mechanisms**.\n\n"
        "**Optional references:** "
        "[Elections Department Singapore](https://www.eld.gov.sg/) · "
        "[Parliament of Singapore](https://www.parliament.gov.sg/) · "
        "[Attorney-General's Chambers — statutes](https://www.agc.gov.sg/) · "
        "[UN Human Rights — treaty body documents](https://tbinternet.ohchr.org/_layouts/15/TreatyBodyExternal/Treaty.aspx)",
        _L("IDEA — Singapore profile", "https://www.idea.int/data-tools/data/country-profiles"),
        _L("ASEAN Intergovernmental Commission on Human Rights", "https://aichr.org/"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("Commonwealth Parliamentary Association", "https://www.cpahq.org/"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration, integration, and anti-discrimination**.\n\n"
        "**Optional references:** "
        "[ICA — Immigration & Checkpoints Authority](https://www.ica.gov.sg/) · "
        "[MHA — Ministry of Home Affairs](https://www.mha.gov.sg/) · "
        "[UNHCR — regional office](https://www.unhcr.org/asia) · "
        "[Tripartite Alliance for Fair Employment Practices](https://www.tafep.sg/)",
        _L("SingStat — population", "https://www.singstat.gov.sg/find-data/search-by-theme/population"),
        _L("ILO", "https://www.ilo.org/"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("European Commission — migration (comparative)", "https://home-affairs.ec.europa.eu/policies/migration-and-asylum_en"),
    ),
    "Education & future skills": _pack(
        "Focus on **streaming reform, tertiary pathways, and skillsFuture**.\n\n"
        "**Optional references:** "
        "[MOE — Ministry of Education](https://www.moe.gov.sg/) · "
        "[SkillsFuture Singapore](https://www.skillsfuture.gov.sg/) · "
        "[OECD — PISA](https://www.oecd.org/pisa/) · "
        "[UNESCO UIS](https://uis.unesco.org/)",
        _L("SingStat — education", "https://www.singstat.gov.sg/find-data/search-by-theme/education"),
        _L("OECD — Education at a Glance", "https://www.oecd.org/education/education-at-a-glance/"),
        _L("World Bank — education statistics", "https://data.worldbank.org/topic/education"),
        _L("International Association for the Evaluation of Educational Achievement", "https://www.iea.nl/"),
    ),
}

# ---------------------------------------------------------------------------
# Japan
# ---------------------------------------------------------------------------
_JP: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **GX (green transformation), grid investment, and regional climate risk**.\n\n"
        "**Optional references:** "
        "[Ministry of the Environment, Japan](https://www.env.go.jp/en/) · "
        "[Agency for Natural Resources and Energy (METI)](https://www.enecho.meti.go.jp/en/) · "
        "[Japan Meteorological Agency — climate monitoring](https://www.data.jma.go.jp/gmd/jma/index.html) · "
        "[IPCC](https://www.ipcc.ch/)",
        _L("e-Stat — official statistics of Japan", "https://www.e-stat.go.jp/en"),
        _L("National Diet Library — research guides", "https://www.ndl.go.jp/en/"),
        _L("UNFCCC", "https://unfccc.int/"),
        _L("IEA — Japan", "https://www.iea.org/countries/japan"),
    ),
    "AI & technology": _pack(
        "Consider **AI safety, copyright, and public-sector digitisation**.\n\n"
        "**Optional references:** "
        "[Digital Agency of Japan](https://www.digital.go.jp/en) · "
        "[MIC — Ministry of Internal Affairs and Communications](https://www.soumu.go.jp/main_sosiki/joho_tsusin/eng/index.html) · "
        "[Personal Information Protection Commission (PPC)](https://www.ppc.go.jp/en/) · "
        "[OECD.AI](https://oecd.ai/en)",
        _L("National Institute of Informatics — research", "https://www.nii.ac.jp/en/"),
        _L("EUR-Lex — EU AI Act (comparative)", "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689"),
        _L("Council of Europe — AI", "https://www.coe.int/en/web/artificial-intelligence"),
        _L("NIST — AI RMF", "https://www.nist.gov/itl/ai-risk-management-framework"),
    ),
    "Economy & work": _pack(
        "Structural questions on **demographics, productivity, and monetary policy**.\n\n"
        "**Optional references:** "
        "[Cabinet Office, Japan — statistics](https://www.e-stat.go.jp/en/statistics-by-government-organization/cabinet-office) · "
        "[Bank of Japan — research](https://www.boj.or.jp/en/research/index.htm/) · "
        "[e-Stat](https://www.e-stat.go.jp/en) · "
        "[OECD — Japan](https://www.oecd.org/japan/)",
        _L("IMF — Japan", "https://www.imf.org/en/Countries/JPN"),
        _L("ILO", "https://www.ilo.org/"),
        _L("World Bank — Japan", "https://data.worldbank.org/country/japan"),
        _L("WTO — Japan trade policy reviews", "https://www.wto.org/english/tratop_e/tpr_e/tp_rep_e.htm"),
    ),
    "Health & care": _pack(
        "Focus on **universal coverage design, ageing, and surge planning**.\n\n"
        "**Optional references:** "
        "[MHLW — Ministry of Health, Labour and Welfare](https://www.mhlw.go.jp/english/) · "
        "[WHO Western Pacific](https://www.who.int/westernpacific) · "
        "[National Institute of Public Health (Japan)](https://www.niph.go.jp/english/index.html) · "
        "[OECD — Health at a Glance: Asia/Pacific](https://www.oecd.org/health/health-at-a-glance-asia-pacific-23150130.htm)",
        _L("e-Stat — health", "https://www.e-stat.go.jp/en/statistics/health"),
        _L("National Diet Library", "https://www.ndl.go.jp/en/"),
        _L("OECD — Japan health policy", "https://www.oecd.org/health/"),
        _L("World Bank — health expenditure", "https://data.worldbank.org/indicator/SH.XPD.CHEX.GD.ZS?locations=JP"),
    ),
    "War, peace & security": _pack(
        "Normative questions on **collective self-defence, alliances, and peacekeeping**.\n\n"
        "**Optional references:** "
        "[Ministry of Defense, Japan](https://www.mod.go.jp/en/) · "
        "[Ministry of Foreign Affairs of Japan](https://www.mofa.go.jp/) · "
        "[UN Charter](https://www.un.org/en/about-us/un-charter/full-text) · "
        "[UN Peacekeeping](https://peacekeeping.un.org/en)",
        _L("National Diet Library — security collections", "https://www.ndl.go.jp/en/"),
        _L("ICRC", "https://www.icrc.org/"),
        _L("SIPRI", "https://www.sipri.org/"),
        _L("IISS", "https://www.iiss.org/"),
    ),
    "Democracy & institutions": _pack(
        "Institutional design — **Diet, Cabinet, courts, and election administration**.\n\n"
        "**Optional references:** "
        "[Ministry of Internal Affairs and Communications — elections](https://www.soumu.go.jp/main_sosiki/senkyo/index.html) · "
        "[The Constitution of Japan (National Diet Library guide)](https://www.ndl.go.jp/constitution/e/index.html) · "
        "[Supreme Court of Japan](https://www.courts.go.jp/english/) · "
        "[Venice Commission](https://www.venice.coe.int/)",
        _L("IDEA", "https://www.idea.int/"),
        _L("OSCE/ODIHR (methodological comparator)", "https://www.osce.org/odihr/elections"),
        _L("Council of Europe — democracy support", "https://www.coe.int/en/web/portal/democracy"),
        _L("UN Human Rights — Japan reviews", "https://www.ohchr.org/en/hr-bodies/upr/pages/jpindex.aspx"),
    ),
    "Society & cohesion": _pack(
        "Vote on **immigration pathways, integration, and non-discrimination**.\n\n"
        "**Optional references:** "
        "[Immigration Services Agency of Japan](https://www.isa.go.jp/en/) · "
        "[MOFA — human rights diplomacy](https://www.mofa.go.jp/policy/human/) · "
        "[UNHCR Japan](https://www.unhcr.org/jp/) · "
        "[Ministry of Justice — English site](https://www.moj.go.jp/ENGLISH/index.html)",
        _L("e-Stat — population", "https://www.e-stat.go.jp/en/statistics/population"),
        _L("OHCHR", "https://www.ohchr.org/"),
        _L("ILO — migration statistics", "https://www.ilo.org/global/topics/labour-migration/lang--en/index.htm"),
        _L("Council of Europe — ECRI (regional comparator)", "https://www.coe.int/en/web/european-commission-against-racism-and-intolerance"),
    ),
    "Education & future skills": _pack(
        "Focus on **higher-ed reform, regional disparities, and lifelong learning**.\n\n"
        "**Optional references:** "
        "[MEXT — Ministry of Education, Culture, Sports, Science and Technology](https://www.mext.go.jp/en/) · "
        "[OECD — PISA](https://www.oecd.org/pisa/) · "
        "[UNESCO UIS](https://uis.unesco.org/) · "
        "[National Institute for Educational Policy Research](https://www.nier.go.jp/English/index.html)",
        _L("e-Stat — education", "https://www.e-stat.go.jp/en/statistics/education"),
        _L("National Diet Library — education policy", "https://www.ndl.go.jp/en/"),
        _L("World Bank — education data", "https://data.worldbank.org/topic/education"),
        _L("OECD — Education at a Glance", "https://www.oecd.org/education/education-at-a-glance/"),
    ),
}

# ---------------------------------------------------------------------------
# China (official + UN / multilateral comparators)
# ---------------------------------------------------------------------------
_CN: Dict[str, Pack] = {
    "Climate & planet": _pack(
        "Focus on **national climate targets**, energy mix, and air-quality co-benefits.\n\n"
        "**Optional references:** "
        "[Ministry of Ecology and Environment (English)](https://english.mee.gov.cn/) · "
        "[National Bureau of Statistics — energy & environment indicators](https://www.stats.gov.cn/english/) · "
        "[UNFCCC — national communications](https://unfccc.int/process-and-meetings/transparency-and-reporting/reporting-and-review-under-the-convention) · "
        "[IPCC](https://www.ipcc.ch/)",
        _L("World Bank — China climate & development", "https://www.worldbank.org/en/country/china"),
        _L("IEA — China", "https://www.iea.org/countries/china"),
        _L("WHO — air quality & health", "https://www.who.int/teams/environment-climate-change-and-health/air-quality-and-health"),
        _L("UN Environment Programme", "https://www.unep.org/"),
    ),
    "AI & technology": _pack(
        "Consider **algorithmic governance, data security, and global technical standards**.\n\n"
        "**Optional references:** "
        "[Cyberspace Administration of China (CAC) — English portal](https://english.cac.gov.cn/) · "
        "[MIIT — Ministry of Industry and Information Technology](https://english.miit.gov.cn/) · "
        "[ITU — AI standards work](https://www.itu.int/en/ITU-T/ai/Pages/default.aspx) · "
        "[ISO/IEC JTC 1/SC 42 — artificial intelligence](https://www.iso.org/committee/6794475.html)",
        _L("UNESCO — AI ethics recommendation", "https://www.unesco.org/en/artificial-intelligence/recommendation-ethics"),
        _L("OECD.AI", "https://oecd.ai/en"),
        _L("IEEE Standards Association — ethics & AI standards", "https://standards.ieee.org/industry-connections/activities/ieee-global-initiative-on-ethics-of-autonomous-and-intelligent-systems/"),
        _L("Council of Europe — AI (regional comparator)", "https://www.coe.int/en/web/artificial-intelligence"),
    ),
    "Economy & work": _pack(
        "Structural questions on **industrial policy, urbanisation, and demographic transition**.\n\n"
        "**Optional references:** "
        "[National Bureau of Statistics](https://www.stats.gov.cn/english/) · "
        "[State Council — policy documents (English)](https://english.www.gov.cn/policies/) · "
        "[People's Bank of China — statistics & research](https://www.pbc.gov.cn/en/3688110/3688172/index.html) · "
        "[IMF — China](https://www.imf.org/en/Countries/CHN)",
        _L("World Bank — China overview", "https://www.worldbank.org/en/country/china/overview"),
        _L("OECD — China economic surveys", "https://www.oecd.org/china/"),
        _L("WTO — trade policy reviews", "https://www.wto.org/english/tratop_e/tpr_e/tp_rep_e.htm"),
        _L("ILO — China country office", "https://www.ilo.org/beijing/lang--en/index.htm"),
    ),
    "Health & care": _pack(
        "Focus on **coverage expansion, ageing, and public health capacity**.\n\n"
        "**Optional references:** "
        "[National Health Commission (English)](https://en.nhc.gov.cn/) · "
        "[WHO China country office](https://www.who.int/countries/china) · "
        "[UNICEF China — health & child wellbeing](https://www.unicef.cn/en) · "
        "[World Bank — China health reform (publication)](https://www.worldbank.org/en/topic/health/publication/china-health-reform-experiences-and-global-significance)",
        _L("National Bureau of Statistics — health & social statistics", "https://www.stats.gov.cn/english/"),
        _L("OECD — Health at a Glance: Asia/Pacific", "https://www.oecd.org/health/health-at-a-glance-asia-pacific-23150130.htm"),
        _L("Global Burden of Disease — IHME", "https://www.healthdata.org/research-analysis/gbd"),
        _L("UN — SDG 3 data hub", "https://unstats.un.org/sdgs/reporting/Tier"),
    ),
    "War, peace & security": _pack(
        "Normative questions on **defence modernisation, UN peacekeeping contributions, and maritime security**.\n\n"
        "**Optional references:** "
        "[Ministry of National Defense (English)](https://eng.mod.gov.cn/) · "
        "[Ministry of Foreign Affairs of the People's Republic of China](https://www.fmprc.gov.cn/eng/) · "
        "[UN Peacekeeping — troop contributors](https://peacekeeping.un.org/en/troop-and-police-contributors) · "
        "[UN Charter](https://www.un.org/en/about-us/un-charter/full-text)",
        _L("UN Office for Disarmament Affairs", "https://www.un.org/disarmament/"),
        _L("ICRC — international humanitarian law", "https://www.icrc.org/en/war-and-law"),
        _L("SIPRI", "https://www.sipri.org/"),
        _L("IISS", "https://www.iiss.org/"),
    ),
    "Democracy & institutions": _pack(
        "This theme invites reflection on **institutions, law, and participation** — consult official texts alongside independent comparative sources.\n\n"
        "**Optional references:** "
        "[NPC — National People's Congress (English)](https://www.npc.gov.cn/englishnpc/) · "
        "[State Council — rule of law & governance white papers](https://english.www.gov.cn/archive/whitepaper/) · "
        "[UN OHCHR — treaty bodies & UPR](https://www.ohchr.org/en/human-rights-bodies) · "
        "[Worldwide Governance Indicators (World Bank)](https://www.worldbank.org/en/publication/worldwide-governance-indicators)",
        _L("IDEA — global democracy data", "https://www.idea.int/"),
        _L("Venice Commission — comparative opinions", "https://www.venice.coe.int/"),
        _L("UN Human Rights — special procedures", "https://www.ohchr.org/en/hr-bodies/sp/country-mandates"),
        _L("OECD — Government at a Glance (comparative)", "https://www.oecd.org/gov/government-at-a-glance.htm"),
    ),
    "Society & cohesion": _pack(
        "Vote on **policy design** for mobility, integration, and equality before the law.\n\n"
        "**Optional references:** "
        "[National Immigration Administration (English)](https://www.nia.gov.cn/menunew/n741480/n741481/index.html) · "
        "[UNHCR — China operations](https://www.unhcr.org/cn/) · "
        "[OHCHR — core treaties](https://www.ohchr.org/en/core-international-human-rights-instruments-and-their-monitoring-bodies) · "
        "[UN — gender equality (SDG 5)](https://www.un.org/sustainabledevelopment/gender-equality/)",
        _L("National Bureau of Statistics — population", "https://www.stats.gov.cn/english/"),
        _L("ILO — labour migration", "https://www.ilo.org/global/topics/labour-migration/lang--en/index.htm"),
        _L("UN Women — China", "https://www.unwomen.org/en/where-we-are/asia-and-the-pacific"),
        _L("UNDP — China human development reports", "https://www.undp.org/china"),
    ),
    "Education & future skills": _pack(
        "Focus on **access, quality, and vocational/higher-education pathways**.\n\n"
        "**Optional references:** "
        "[Ministry of Education (English)](https://en.moe.gov.cn/) · "
        "[National Bureau of Statistics — education indicators](https://www.stats.gov.cn/english/) · "
        "[UNESCO UIS](https://uis.unesco.org/) · "
        "[OECD — Education at a Glance (comparative)](https://www.oecd.org/education/education-at-a-glance/)",
        _L("World Bank — education in China", "https://www.worldbank.org/en/topic/education/publication/chinas-education-development-and-policy-1978-2018-a-review-and-assessment"),
        _L("UNICEF China — education equity", "https://www.unicef.cn/en/what-we-do/13-education"),
        _L("IEA — international education studies", "https://www.iea.nl/"),
        _L("UN — SDG 4 quality education", "https://www.un.org/sustainabledevelopment/education/"),
    ),
}

READING_PACKS: Dict[str, Dict[str, Pack]] = {
    "uk": _UK,
    "us": _US,
    "nl": _NL,
    "ie": _IE,
    "de": _DE,
    "fr": _FR,
    "ca": _CA,
    "sg": _SG,
    "jp": _JP,
    "cn": _CN,
}


def merge_reading_enrichment(curriculum: List[dict[str, Any]], variant: str) -> None:
    """Overlay optional reading bodies and links for country editions."""
    if variant == "global":
        return
    packs = READING_PACKS.get(variant)
    if not packs:
        return
    for spec in curriculum:
        theme = spec.get("theme")
        if theme in packs:
            spec["information_body"] = packs[theme]["body"]
            spec["information_links"] = [dict(link) for link in packs[theme]["links"]]
