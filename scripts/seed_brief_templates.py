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

    'policy-monitoring': """<p style="margin: 0 0 8px 0; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #1e3a8a;">WHAT CHANGED</p>
<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #1e3a8a; padding-bottom: 12px;">This Week in Policy</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">FCA Publishes Final Consumer Duty Guidance</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">The Financial Conduct Authority released final guidance on Consumer Duty implementation for financial services firms. Key requirements include enhanced product governance, clear fair value assessments, and improved customer support standards.</p>
<div style="background-color: #eff6ff; border-left: 4px solid #1e40af; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #1e3a8a; text-transform: uppercase;">Why It Matters</p>
<p style="margin: 0; font-size: 14px; color: #1e40af; line-height: 1.6;">Firms must evidence compliance by April 2026. Non-compliance risks enforcement action and reputational damage.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: FCA, Financial Times</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">LEGISLATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Digital Markets Act Enforcement Begins</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">European Commission commenced enforcement proceedings against designated gatekeepers. Initial focus areas include interoperability requirements and self-preferencing in search results.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: European Commission</p>
</div>

<div style="background-color: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #92400e;">What to Watch</p>
<ul style="margin: 0; padding: 0 0 0 20px; color: #78350f; line-height: 1.7;">
<li>Treasury Select Committee hearing on crypto regulation (Tuesday)</li>
<li>ESMA consultation on ESG fund naming closes (Friday)</li>
</ul>
</div>""",

    'sector-intelligence': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #4f46e5; padding-bottom: 12px;">Industry Intelligence</h2>

<div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #4f46e5;">Key Takeaways</p>
<ul style="margin: 0; padding: 0 0 0 20px; color: #1f2937; line-height: 1.8;">
<li>Sector M&A activity up 23% QoQ, driven by consolidation among mid-market players</li>
<li>Three new regulatory consultations opened affecting core operations</li>
<li>Competitor XYZ announced strategic pivot toward AI-enabled services</li>
</ul>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #4f46e5;">MARKET MOVEMENT</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Private Equity Continues Sector Consolidation</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Blackstone completed its acquisition of ServiceCorp for $2.4B, marking the third major PE transaction in the sector this quarter. Deal multiples averaging 12x EBITDA suggest continued confidence in recurring revenue models.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Reuters, Private Equity News</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">COMPETITOR WATCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">IndustryLeader Inc. Expands European Operations</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Announced new offices in Frankfurt and Amsterdam, with plans to hire 200 staff by Q3. European revenue now represents 28% of total, up from 19% in 2024.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Company Press Release, Bloomberg</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">RESEARCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">McKinsey Report: AI Adoption Reshaping Sector Economics</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">New analysis suggests early AI adopters achieving 15-20% cost reductions in core operations. Report highlights data infrastructure as the primary barrier for mid-market firms.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: McKinsey Global Institute</p>
</div>""",

    'internal-research': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #475569; padding-bottom: 12px;">Research Synthesis</h2>

<div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
<p style="margin: 0 0 12px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">Documents Analyzed</p>
<p style="margin: 0 0 4px 0; font-size: 14px; color: #64748b;">12 internal reports, 3 external studies, 2 strategy documents</p>
<p style="margin: 0; font-size: 14px; color: #64748b;">Period: Q4 2025</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">EMERGING THEME</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Customer Retention Declining in Mid-Market Segment</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Multiple reports identify a consistent pattern: mid-market customer churn increased to 18% (up from 12% in 2024). Primary drivers cited include pricing pressure and feature gaps compared to enterprise tier.</p>
<div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 12px 16px; margin-top: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #991b1b; text-transform: uppercase;">Gap Identified</p>
<p style="margin: 0; font-size: 14px; color: #b91c1c; line-height: 1.6;">No current initiative addresses mid-market retention specifically. This appears to be a strategic blind spot.</p>
</div>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">CONSENSUS VIEW</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">AI Integration Timeline More Aggressive Than Planned</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Both strategy documents and recent team retrospectives suggest the original 24-month AI roadmap should be compressed to 12-18 months. Competitive pressure cited as primary driver.</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">OPEN QUESTIONS</p>
<ul style="margin: 0; padding: 0 0 0 20px; color: #4b5563; line-height: 1.8;">
<li>What is the ROI threshold for mid-market retention investment?</li>
<li>Should AI acceleration be resourced from existing budget or require new allocation?</li>
<li>Which competitor moves require immediate response vs. monitoring?</li>
</ul>
</div>""",

    'thought-leadership': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #b45309; padding-bottom: 12px;">Weekly Perspective</h2>

<div style="border-left: 4px solid #b45309; padding-left: 20px; margin-bottom: 24px;">
<p style="margin: 0 0 8px 0; font-family: Georgia, serif; font-size: 20px; font-style: italic; line-height: 1.5; color: #1f2937;">"The most significant regulatory shift in a decade requires measured analysis, not reactive commentary."</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">AI Governance Frameworks: What the Evidence Actually Shows</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Analysis of 47 published AI governance frameworks across jurisdictions reveals three distinct approaches: prescriptive regulation (EU model), principles-based guidance (UK approach), and sector-specific rules (US pattern). Each presents different compliance implications for multinational organizations.</p>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Key finding: Organizations operating across all three jurisdictions face an estimated 340% increase in compliance documentation requirements compared to single-jurisdiction operations.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Based on analysis by our regulatory affairs team, January 2026</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Supply Chain Resilience: Lessons from Recent Disruptions</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">The Red Sea shipping disruptions offer concrete data on supply chain resilience strategies. Companies with diversified routing options experienced 12% cost increases; those without saw 34% increases. This validates pre-pandemic recommendations on multi-source strategies.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Internal analysis of 200+ supply chain partners</p>
</div>

<div style="background-color: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #92400e;">Suitable for External Publication</p>
<p style="margin: 0; font-size: 14px; color: #78350f; line-height: 1.6;">This content has been reviewed and is appropriate for sharing on company blog, LinkedIn, or industry publications. All claims are cited and fact-checked.</p>
</div>""",

    'crypto-digital-assets': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #c2410c; padding-bottom: 12px;">Crypto & Digital Assets</h2>

<div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; display: flex; justify-content: space-between;">
<div style="text-align: center; padding-right: 20px; border-right: 1px solid #e5e7eb;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">$97,420</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">BTC (+2.3%)</p>
</div>
<div style="text-align: center; padding: 0 20px; border-right: 1px solid #e5e7eb;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">$3,245</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">ETH (+1.8%)</p>
</div>
<div style="text-align: center; padding-left: 20px;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">$2.1T</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">Total Market Cap</p>
</div>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">SEC Approves First Spot Ethereum ETFs</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Following extended review, the SEC approved applications from BlackRock, Fidelity, and Grayscale for spot Ethereum ETFs. Trading begins next week, with analysts projecting $5-8B inflows in the first quarter.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: SEC Filing, Bloomberg</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">INFRASTRUCTURE</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Ethereum Layer 2 Activity Reaches All-Time High</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Combined TVL across Arbitrum, Optimism, and Base exceeded $35B. Transaction costs on mainnet driving continued migration to L2 solutions. Base alone processed 2M daily transactions, surpassing Ethereum mainnet.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: L2Beat, Dune Analytics</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">RISK</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Major Exchange Reports Security Incident</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Bybit disclosed unauthorized access affecting customer data (not funds). Investigation ongoing with regulatory notification completed. No asset impact confirmed, but trading volumes dropped 15% in 24 hours.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Bybit Statement, CoinDesk</p>
</div>""",

    'trending-topics': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #be123c; padding-bottom: 12px;">What's Trending</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#1</span>
<span style="display: inline-block; background-color: #fef2f2; color: #be123c; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">VIRAL</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Documentary "The Great Unraveling" Sparks Global Debate</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">The new Netflix documentary examining social media's impact on democracy has generated 50M+ views in its first week. Political figures across the spectrum have responded, with some calling for platform regulation reform.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: Twitter/X, Reddit, LinkedIn | Sentiment: Mixed</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#2</span>
<span style="display: inline-block; background-color: #eff6ff; color: #1e40af; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">BREAKING</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Major Tech Layoffs Signal Industry Recalibration</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Google, Microsoft, and Meta announced combined workforce reductions of 12,000 roles. Focus on AI efficiency cited as primary driver. Tech worker sentiment on social platforms shows frustration but also resilience.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: LinkedIn, Hacker News, Blind | Sentiment: Negative</p>
</div>

<div style="margin-bottom: 24px;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#3</span>
<span style="display: inline-block; background-color: #ecfdf5; color: #059669; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">FEEL GOOD</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Community Response to Storm Damage Inspires Millions</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Volunteer coordination efforts in storm-affected regions have gone viral, with #NeighborsHelping garnering 2M+ posts. Local businesses organizing supply chains and housing solutions. Strong positive engagement across platforms.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: Instagram, TikTok, Facebook | Sentiment: Positive</p>
</div>""",

    'health-science-medicine': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #047857; padding-bottom: 12px;">Health, Science & Medicine</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #047857;">BREAKTHROUGH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Phase 3 Trial Success for Alzheimer's Prevention Drug</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Eli Lilly announced positive results from its preventive Alzheimer's drug trial. The treatment showed 35% reduction in cognitive decline among high-risk participants over 24 months. FDA fast-track designation expected.</p>
<div style="background-color: #ecfdf5; border-left: 4px solid #047857; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #065f46; text-transform: uppercase;">What This Means</p>
<p style="margin: 0; font-size: 14px; color: #047857; line-height: 1.6;">If approved, this would be the first preventive treatment for Alzheimer's, potentially benefiting millions of at-risk individuals.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: NEJM, Eli Lilly Press Release</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">RESEARCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Long COVID Study Reveals Immune System Patterns</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Yale researchers identified distinct immune signatures in long COVID patients that persist 18+ months post-infection. Findings suggest targeted immunomodulatory treatments may be effective. Clinical trials planned for Q3 2026.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Nature Medicine, Yale School of Medicine</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">PUBLIC HEALTH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">WHO Updates Global Antimicrobial Resistance Strategy</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">New WHO guidelines recommend reduced antibiotic prescriptions for common conditions and increased investment in alternative treatments. Member nations have 18 months to update national action plans.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: WHO, The Lancet</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">TECHNOLOGY</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">AI Diagnostic Tool Outperforms Radiologists in Early Cancer Detection</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Google DeepMind's latest medical imaging AI achieved 94.5% accuracy in early-stage lung cancer detection, compared to 87% for experienced radiologists. NHS pilot program expanding to 50 additional hospitals.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Nature Communications, NHS England</p>
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
        'default_accent_color': '#1e40af',
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
        'default_accent_color': '#7c3aed',
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
        'default_accent_color': '#047857',
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
        'default_accent_color': '#0f766e',
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
        'default_accent_color': '#1e3a8a',
        'sample_output': SAMPLE_OUTPUTS.get('policy-monitoring', ''),
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
        'default_accent_color': '#4f46e5',
        'sample_output': SAMPLE_OUTPUTS.get('sector-intelligence', ''),
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
        'default_accent_color': '#475569',
        'sample_output': SAMPLE_OUTPUTS.get('internal-research', ''),
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
        'default_accent_color': '#b45309',
        'sample_output': SAMPLE_OUTPUTS.get('thought-leadership', ''),
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
        'default_accent_color': '#c2410c',
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
        'default_accent_color': '#c2410c',
        'sample_output': SAMPLE_OUTPUTS.get('crypto-digital-assets', ''),
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
        'default_accent_color': '#be123c',
        'sample_output': SAMPLE_OUTPUTS.get('trending-topics', ''),
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
        'default_accent_color': '#047857',
        'sample_output': SAMPLE_OUTPUTS.get('health-science-medicine', ''),
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
