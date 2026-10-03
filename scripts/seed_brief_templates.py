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
    'politics-public-policy': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #1e40af; padding-bottom: 12px;">What Changed This Week</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Automated Decisions Rulebook Sets Compliance Timeline</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A national digital standards authority published detailed guidance on its new rulebook for automated decision systems, setting deadlines for high-risk uses. Organisations in scope will need to complete risk assessments within nine months, with full compliance required within two years.</p>
<div style="background-color: #eff6ff; border-left: 4px solid #1e40af; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #1e3a8a; text-transform: uppercase;">What This Means</p>
<p style="margin: 0; font-size: 14px; color: #1e40af; line-height: 1.6;">Organisations using automated tools for hiring, credit scoring or public services should begin compliance audits now.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Office for Digital Standards, The Civic Ledger</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">FUNDING</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Rural Broadband Funding Allocations Released</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A national infrastructure ministry announced a multi-billion programme for broadband expansion in rural areas. Grants will be distributed through regional authorities, with applications opening next quarter.</p>
<div style="background-color: #ecfdf5; border-left: 4px solid #059669; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #065f46; text-transform: uppercase;">Next Steps</p>
<p style="margin: 0; font-size: 14px; color: #047857; line-height: 1.6;">Regional authorities have 60 days to submit delivery plans.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Ministry of Infrastructure, Harbourside Press Agency</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">LEGISLATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Data Protection Bill Clears Final Reading</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A data protection bill passed its final reading in the upper chamber. Key changes include simplified consent for research purposes and new rules for international data transfers.</p>
<p style="margin: 0 0 8px 0; font-size: 14px; color: #6b7280;"><strong>Timeline:</strong> Royal Assent expected within 6 weeks.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Parliamentary record, The Westbrook Review</p>
</div>""",

    'technology-ai-regulation': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #7c3aed; padding-bottom: 12px;">Tech & AI Update</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">PRODUCT LAUNCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Larkspur Labs Releases New Model API with Tighter Safety Controls</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Larkspur Labs, a large model lab, launched its latest model with stronger code generation and reasoning. The release adds mandatory content filtering for enterprise customers and improved rate limiting, with input pricing cut for high-volume users.</p>
<div style="background-color: #f5f3ff; border-left: 4px solid #7c3aed; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #5b21b6; text-transform: uppercase;">Key Details</p>
<p style="margin: 0; font-size: 14px; color: #6d28d9; line-height: 1.6;">Longer context window. API documentation updated with new tool-calling patterns.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Larkspur Labs blog, The Circuit Review</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Standards Body Updates AI Risk Management Framework</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">The Harbourside Standards Board released a revised AI risk management framework, adding specific guidance for generative AI systems. New sections cover prompt injection prevention and output validation.</p>
<div style="background-color: #eff6ff; border-left: 4px solid #1e40af; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #1e3a8a; text-transform: uppercase;">Action Required</p>
<p style="margin: 0; font-size: 14px; color: #1e40af; line-height: 1.6;">Review updated governance profiles if operating AI systems in regulated industries.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Harbourside Standards Board, The Circuit Review</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">ENTERPRISE</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Coding Assistant Adds Enterprise Compliance Features</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Brightwell, a developer tools company, added enterprise features to its coding assistant, including code provenance tracking, licence compliance checks and audit logs. The update also brings organisation-wide policy controls for code suggestions.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Brightwell blog, Stackline Weekly</p>
</div>""",

    'economy-markets': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #059669; padding-bottom: 12px;">Economic Trends This Week</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">INFLATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Inflation Continues Gradual Decline</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Consumer price data showed headline inflation edging down for a third month. Core inflation (excluding food and energy) remains elevated. Housing costs continue to be the main source of stickiness.</p>
<div style="background-color: #fef2f2; border-left: 4px solid #dc2626; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #991b1b; text-transform: uppercase;">What This Means</p>
<p style="margin: 0; font-size: 14px; color: #b91c1c; line-height: 1.6;">Gradual easing, but slower than the central bank projected. Markets are pricing in one more rate cut within six months.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: National Statistics Office, The Ledger Review</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">MANUFACTURING</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Manufacturing Shows Signs of Stabilising</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">The regional purchasing managers' index rose to 48.2, still in contraction territory but the highest reading in eight months. The two largest economies improved modestly, while smaller southern economies remained stronger.</p>
<div style="background-color: #ecfdf5; border-left: 4px solid #059669; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #065f46; text-transform: uppercase;">Context</p>
<p style="margin: 0; font-size: 14px; color: #047857; line-height: 1.6;">Readings below 50 indicate contraction. The current trajectory suggests a possible return to expansion within two quarters.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Calder Economic Surveys, The Ledger Review</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">LABOUR MARKET</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Jobs Data Shows Mixed Signals</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Weekly jobless claims held steady. Unemployment ticked up slightly, while annual wage growth moderated. Labour market conditions remain tight by historical standards but are gradually normalising.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: National Statistics Office, Harbourside Press Agency</p>
</div>""",

    'climate-energy-planet': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #0f766e; padding-bottom: 12px;">Climate & Energy Update</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">POLICY</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Carbon Border Levy Enters Full Implementation</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A major trading bloc's carbon border levy now requires importers of steel, cement, aluminium and fertilisers to declare full carbon content. Companies must buy certificates matching embedded emissions within six months.</p>
<div style="background-color: #f0fdfa; border-left: 4px solid #0f766e; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #115e59; text-transform: uppercase;">What This Means</p>
<p style="margin: 0; font-size: 14px; color: #0f766e; line-height: 1.6;">Affects supply chains with significant manufacturing outside the bloc. Many companies are restructuring procurement.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Bloc trade secretariat, The Carbon Desk</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">RENEWABLES</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Renewable Capacity Additions Set New Record</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">An international energy research body says new renewable capacity is on track for a record year, up about a quarter on last year. Solar accounts for most additions, with grid connection becoming the main constraint.</p>
<div style="background-color: #fef3c7; border-left: 4px solid #d97706; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #92400e; text-transform: uppercase;">Key Challenge</p>
<p style="margin: 0; font-size: 14px; color: #b45309; line-height: 1.6;">Grid investment is lagging well behind growth in generation.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Global Energy Outlook Council, The Carbon Desk</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">TECHNOLOGY</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Battery Storage Costs Continue Decline</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Lithium-ion battery pack prices fell again, down about an eighth on a year ago. Sodium-ion alternatives are gaining ground for stationary storage, with several utility-scale projects announced.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Voltmark Research, Grid Notes</p>
</div>""",

    'sport-state-of-play': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #c2410c; padding-bottom: 12px;">Sport - What Matters</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #c2410c;">FOOTBALL</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Coastal League Title Race Tightens</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Kingsmere United moved within two points of leaders Redwater Rovers after a 3-1 win against Hollin Athletic. Brackenford Town's draw away keeps them in contention, four points behind with a game in hand. Key fixture: Kingsmere vs Redwater next Saturday.</p>
<div style="background-color: #fff7ed; border-left: 4px solid #c2410c; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #9a3412; text-transform: uppercase;">Current Standings</p>
<p style="margin: 0; font-size: 14px; color: #c2410c; line-height: 1.6;">Redwater 58pts | Kingsmere 56pts | Brackenford 54pts (1 game in hand)</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Coastal League, The Touchline Review</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">TENNIS</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Meridian Open Finals Preview</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Tomas Velde faces Arun Castell in the men's final after both came through tough semi-finals. The women's final pits Lena Moravec against Ines Okafor in a rematch of last year's final.</p>
<div style="background-color: #ecfdf5; border-left: 4px solid #059669; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #065f46; text-transform: uppercase;">Head-to-Head</p>
<p style="margin: 0; font-size: 14px; color: #047857; line-height: 1.6;">Castell leads 5-4 overall, but Velde won their last hard-court meeting.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Meridian Open, The Baseline</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">RUGBY</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Western Cup Round 2 Results</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Holders Saltmarsh maintained their title defence with a 28-17 home win over Greyfield. Thornmere beat Calder Vale away, while Wrenhaven secured their first win of the campaign. Saltmarsh and Thornmere remain unbeaten after two rounds.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Western Cup, The Touchline Review</p>
</div>""",

    'policy-monitoring': """<p style="margin: 0 0 8px 0; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase; color: #1e3a8a;">WHAT CHANGED</p>
<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #1e3a8a; padding-bottom: 12px;">This Week in Policy</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Financial Regulator Publishes Final Consumer Duty Guidance</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A national financial conduct regulator released final guidance on its consumer duty rules for financial services firms. Key requirements include stronger product governance, clear fair value assessments and better customer support standards.</p>
<div style="background-color: #eff6ff; border-left: 4px solid #1e40af; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #1e3a8a; text-transform: uppercase;">Why It Matters</p>
<p style="margin: 0; font-size: 14px; color: #1e40af; line-height: 1.6;">Firms must evidence compliance within six months. Non-compliance risks enforcement action and reputational damage.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Conduct regulator, The Westbrook Review</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">LEGISLATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Platform Competition Rules Enforcement Begins</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A competition authority opened enforcement proceedings against designated large platforms. Initial focus areas include interoperability requirements and self-preferencing in search results.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Competition and Markets Board</p>
</div>

<div style="background-color: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #92400e;">What to Watch</p>
<ul style="margin: 0; padding: 0 0 0 20px; color: #78350f; line-height: 1.7;">
<li>Parliamentary finance committee hearing on crypto regulation (Tuesday)</li>
<li>Markets authority consultation on sustainable fund naming closes (Friday)</li>
</ul>
</div>""",

    'sector-intelligence': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #4f46e5; padding-bottom: 12px;">Industry Intelligence</h2>

<div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #4f46e5;">Key Takeaways</p>
<ul style="margin: 0; padding: 0 0 0 20px; color: #1f2937; line-height: 1.8;">
<li>Sector M&A activity up 23% QoQ, driven by consolidation among mid-market players</li>
<li>Three new regulatory consultations opened affecting core operations</li>
<li>A key competitor announced a strategic pivot towards AI-enabled services</li>
</ul>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #4f46e5;">MARKET MOVEMENT</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Private Equity Continues Sector Consolidation</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Ashcombe Capital completed its acquisition of Torrin Services, marking the third major private equity transaction in the sector this quarter. Deal multiples averaging 12x EBITDA suggest continued confidence in recurring revenue models.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Ashcombe Capital statement, Dealflow Monitor</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">COMPETITOR WATCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Halden Group Expands Overseas Operations</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Halden Group announced two new overseas offices, with plans to hire 200 staff within nine months. Overseas revenue now represents 28% of the total, up from 19% a year earlier.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Halden Group announcement, The Ledger Review</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">RESEARCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Consultancy Report: AI Adoption Reshaping Sector Economics</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">New analysis suggests early AI adopters achieving 15-20% cost reductions in core operations. Report highlights data infrastructure as the primary barrier for mid-market firms.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Pellam Advisory research note</p>
</div>""",

    'internal-research': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #475569; padding-bottom: 12px;">Research Synthesis</h2>

<div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 20px; margin-bottom: 24px;">
<p style="margin: 0 0 12px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">Documents Analysed</p>
<p style="margin: 0 0 4px 0; font-size: 14px; color: #64748b;">12 internal reports, 3 external studies, 2 strategy documents</p>
<p style="margin: 0; font-size: 14px; color: #64748b;">Period: last quarter</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #475569;">EMERGING THEME</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Customer Retention Declining in Mid-Market Segment</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Multiple reports identify a consistent pattern: mid-market customer churn increased to 18% (up from 12% a year earlier). Primary drivers cited include pricing pressure and feature gaps compared to enterprise tier.</p>
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
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Analysis of 47 published AI governance frameworks across jurisdictions reveals three distinct approaches: prescriptive regulation, principles-based guidance and sector-specific rules. Each has different compliance implications for multinational organisations.</p>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Key finding: organisations operating under all three approaches face an estimated 340% increase in compliance documentation requirements compared to single-jurisdiction operations.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Based on analysis by our regulatory affairs team</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Supply Chain Resilience: Lessons from Recent Disruptions</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Recent closures of a major shipping lane offer concrete data on supply chain resilience. Companies with diversified routing saw 12% cost increases; those without saw 34%. This supports long-standing recommendations on multi-source strategies.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Internal analysis of 200+ supply chain partners</p>
</div>

<div style="background-color: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px; padding: 16px; margin-bottom: 20px;">
<p style="margin: 0 0 10px 0; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #92400e;">Suitable for External Publication</p>
<p style="margin: 0; font-size: 14px; color: #78350f; line-height: 1.6;">This content has been reviewed and is appropriate for sharing on the company blog, professional networks or industry publications. All claims are cited and fact-checked.</p>
</div>""",

    'crypto-digital-assets': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #c2410c; padding-bottom: 12px;">Crypto & Digital Assets</h2>

<div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; display: flex; justify-content: space-between;">
<div style="text-align: center; padding-right: 20px; border-right: 1px solid #e5e7eb;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">+2.3%</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">Large-cap index (7d)</p>
</div>
<div style="text-align: center; padding: 0 20px; border-right: 1px solid #e5e7eb;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">+1.8%</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">Stablecoin supply (7d)</p>
</div>
<div style="text-align: center; padding-left: 20px;">
<p style="margin: 0 0 4px 0; font-family: Georgia, serif; font-size: 22px; font-weight: 700; color: #c2410c;">-0.6%</p>
<p style="margin: 0; font-size: 12px; color: #6b7280;">Exchange volume (7d)</p>
</div>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">REGULATION</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Securities Regulator Approves First Spot Token Funds</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">After an extended review, a national securities regulator approved applications from three asset managers for exchange-traded funds holding a major digital token directly. Trading begins next week, with analysts expecting strong inflows in the first quarter.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Regulator filing, The Ledger Review</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #059669;">INFRASTRUCTURE</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Layer 2 Network Activity Reaches All-Time High</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Combined value locked across the largest layer 2 networks hit a new high. Fees on the base chain continue to push activity to cheaper layer 2 networks, the busiest of which now processes more daily transactions than the base chain itself.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Chainview Analytics, Blockfield Data</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">RISK</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Major Exchange Reports Security Incident</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Fennick Exchange disclosed unauthorised access affecting customer data (not funds). An investigation is ongoing and regulators have been notified. No asset impact confirmed, but trading volumes dropped 15% in 24 hours.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Fennick Exchange statement, Blockfield Daily</p>
</div>""",

    'trending-topics': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #be123c; padding-bottom: 12px;">What's Trending</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#1</span>
<span style="display: inline-block; background-color: #fef2f2; color: #be123c; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">VIRAL</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Documentary "The Great Unravelling" Sparks Global Debate</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A new streaming documentary examining social media's impact on democracy has drawn tens of millions of views in its first week. Political figures across the spectrum have responded, with some calling for reform of platform regulation.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: major social and discussion platforms | Sentiment: Mixed</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#2</span>
<span style="display: inline-block; background-color: #eff6ff; color: #1e40af; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">BREAKING</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Major Tech Layoffs Signal Industry Recalibration</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Three large technology companies announced combined workforce reductions of about 12,000 roles, citing AI-driven efficiency. Tech worker sentiment on social platforms shows frustration but also resilience.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: professional networks and developer forums | Sentiment: Negative</p>
</div>

<div style="margin-bottom: 24px;">
<div style="display: flex; align-items: center; margin-bottom: 12px;">
<span style="display: inline-block; background-color: #be123c; color: white; font-weight: 700; padding: 4px 12px; border-radius: 4px; font-size: 14px; margin-right: 12px;">#3</span>
<span style="display: inline-block; background-color: #ecfdf5; color: #059669; padding: 4px 10px; border-radius: 4px; font-size: 12px; font-weight: 600;">FEEL GOOD</span>
</div>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Community Response to Storm Damage Inspires Millions</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Volunteer coordination in storm-affected towns has gone viral, with #NeighboursHelping passing two million posts. Local businesses are organising supplies and temporary housing. Strong positive engagement across platforms.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Trending on: photo and short-video platforms | Sentiment: Positive</p>
</div>""",

    'health-science-medicine': """<h2 style="margin: 0 0 20px 0; font-family: Georgia, serif; font-size: 22px; color: #0f172a; border-bottom: 2px solid #047857; padding-bottom: 12px;">Health, Science & Medicine</h2>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #047857;">BREAKTHROUGH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Late-Stage Trial Success for Dementia Prevention Drug</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Calloway Therapeutics announced positive results from a late-stage trial of a preventive dementia drug. The treatment slowed cognitive decline by about a third among high-risk participants over 24 months. A fast-track regulatory review is expected.</p>
<div style="background-color: #ecfdf5; border-left: 4px solid #047857; padding: 14px 16px; margin-bottom: 12px; border-radius: 0 6px 6px 0;">
<p style="margin: 0 0 4px 0; font-size: 11px; font-weight: 700; color: #065f46; text-transform: uppercase;">What This Means</p>
<p style="margin: 0; font-size: 14px; color: #047857; line-height: 1.6;">If approved, this would be among the first preventive treatments for dementia, potentially benefiting millions of people at risk.</p>
</div>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Journal of Clinical Neurology Review, Calloway Therapeutics statement</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #7c3aed;">RESEARCH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Long COVID Study Reveals Immune System Patterns</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">Researchers at a university medical school identified distinct immune signatures in long COVID patients that persist 18 months or more after infection. The findings suggest targeted immunomodulatory treatments may help. Clinical trials are planned within the year.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Annals of Immunology Research, Meridian Health Trust</p>
</div>

<div style="margin-bottom: 24px; padding-bottom: 20px; border-bottom: 1px solid #e5e7eb;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #1e40af;">PUBLIC HEALTH</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">Global Health Body Updates Antimicrobial Resistance Strategy</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">New guidelines from an international health body recommend fewer antibiotic prescriptions for common conditions and more investment in alternative treatments. Member countries have 18 months to update national action plans.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: International Health Council, The Clinical Review</p>
</div>

<div style="margin-bottom: 24px;">
<p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; color: #dc2626;">TECHNOLOGY</p>
<h3 style="margin: 0 0 10px 0; font-family: Georgia, serif; font-size: 18px; color: #0f172a;">AI Diagnostic Tool Outperforms Radiologists in Early Cancer Detection</h3>
<p style="margin: 0 0 12px 0; color: #4b5563; line-height: 1.7;">A medical imaging model from Corvane Health detected early-stage lung cancer more accurately than experienced radiologists in a large retrospective study. A national health service pilot is expanding to 50 more hospitals.</p>
<p style="margin: 0; font-size: 13px; color: #9ca3af;">Source: Journal of Diagnostic Imaging, Meridian Health Trust</p>
</div>""",
}

# Recommended sources for each template category
# These reference actual NewsSource names from the news_source table
# When templates are cloned, these sources can be linked to actual NewsSource records
RECOMMENDED_SOURCES = {
    'politics-public-policy': [
        {'name': 'Reuters', 'type': 'rss'},
        {'name': 'Associated Press', 'type': 'rss'},
        {'name': 'The Guardian', 'type': 'guardian'},
        {'name': 'Politico EU', 'type': 'rss'},
        {'name': 'Foreign Affairs', 'type': 'rss'},
    ],
    'technology-ai-regulation': [
        {'name': 'Ars Technica', 'type': 'rss'},
        {'name': 'TechCrunch', 'type': 'rss'},
        {'name': 'The Verge', 'type': 'rss'},
        {'name': 'Wired', 'type': 'rss'},
        {'name': 'MIT Technology Review', 'type': 'rss'},
    ],
    'economy-markets': [
        {'name': 'Financial Times', 'type': 'rss'},
        {'name': 'Bloomberg', 'type': 'rss'},
        {'name': 'The Economist', 'type': 'rss'},
        {'name': 'Reuters', 'type': 'rss'},
    ],
    'climate-energy-planet': [
        {'name': 'Carbon Brief', 'type': 'rss'},
        {'name': 'Clean Energy Wire', 'type': 'rss'},
        {'name': 'E&E News', 'type': 'rss'},
        {'name': 'The Guardian', 'type': 'guardian'},
    ],
    'sport-state-of-play': [
        {'name': 'BBC Sport', 'type': 'rss'},
        {'name': 'The Athletic', 'type': 'rss'},
        {'name': 'ESPN', 'type': 'rss'},
        {'name': 'Sky Sports', 'type': 'rss'},
    ],
    'policy-monitoring': [
        {'name': 'Financial Times', 'type': 'rss'},
        {'name': 'Politico EU', 'type': 'rss'},
        {'name': 'Reuters', 'type': 'rss'},
        {'name': 'Lawfare', 'type': 'rss'},
    ],
    'sector-intelligence': [
        {'name': 'Reuters', 'type': 'rss'},
        {'name': 'Bloomberg', 'type': 'rss'},
        {'name': 'Financial Times', 'type': 'rss'},
        {'name': 'The Economist', 'type': 'rss'},
    ],
    'internal-research': [
        {'name': 'Stratechery', 'type': 'rss'},
        {'name': 'MIT Technology Review', 'type': 'rss'},
        {'name': 'Foreign Affairs', 'type': 'rss'},
    ],
    'thought-leadership': [
        {'name': 'Stratechery', 'type': 'rss'},
        {'name': 'MIT Technology Review', 'type': 'rss'},
        {'name': 'The Economist', 'type': 'rss'},
        {'name': 'Foreign Affairs', 'type': 'rss'},
    ],
    'crypto-digital-assets': [
        {'name': 'CoinDesk', 'type': 'rss'},
        {'name': 'The Block', 'type': 'rss'},
        {'name': 'Decrypt', 'type': 'rss'},
    ],
    'trending-topics': [
        {'name': 'TechCrunch', 'type': 'rss'},
        {'name': 'The Verge', 'type': 'rss'},
        {'name': 'Axios', 'type': 'rss'},
        {'name': 'Rest of World', 'type': 'rss'},
    ],
    'health-science-medicine': [
        # Narrowed to a Health & Longevity focus — STAT covers translational
        # medicine and clinical practice; NEJM and Nature Medicine for primary
        # literature; The Lancet for global health.
        {'name': 'STAT News', 'type': 'rss'},
        {'name': 'NEJM', 'type': 'rss'},
        {'name': 'Nature Medicine', 'type': 'rss'},
        {'name': 'The Lancet', 'type': 'rss'},
    ],
    'startups-founders': [
        {'name': 'Stratechery', 'type': 'rss'},
        {'name': 'Not Boring', 'type': 'rss'},
        {'name': 'The Information', 'type': 'rss'},
        {'name': "Lenny's Newsletter", 'type': 'rss'},
        {'name': 'First Round Review', 'type': 'rss'},
        {'name': 'TechCrunch', 'type': 'rss'},
    ],
    'world-affairs': [
        {'name': 'Foreign Affairs', 'type': 'rss'},
        {'name': 'Reuters World', 'type': 'rss'},
        {'name': 'FT World', 'type': 'rss'},
        {'name': 'BBC World', 'type': 'rss'},
        {'name': 'Associated Press', 'type': 'rss'},
        {'name': 'Al Jazeera English', 'type': 'rss'},
    ],
    'science-big-ideas': [
        {'name': 'Nature News', 'type': 'rss'},
        {'name': 'Quanta Magazine', 'type': 'rss'},
        {'name': 'Asterisk', 'type': 'rss'},
        {'name': 'Works in Progress', 'type': 'rss'},
        {'name': 'Aeon', 'type': 'rss'},
        {'name': 'Marginal Revolution', 'type': 'rss'},
    ],
}

TEMPLATES = [
    # CATEGORY A - Core Insight Templates
    {
        'name': 'Politics & Policy',
        'slug': 'politics-public-policy',
        'description': 'Track policy movement, legislative changes, and regulatory updates without the political drama.',
        'tagline': 'What Changed',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'landmark',
        'is_featured': True,
        # Featured slots ranked by expected conversion for the /briefings/start picker:
        # 1 AI & Technology, 2 Startups & Founders, 3 World Affairs, 4 Markets & Business,
        # 5 Politics & Policy, 6 Climate & Energy, 7 Science & Big Ideas, 8 Health & Longevity.
        'sort_order': 5,
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
        'name': 'AI & Technology',
        'slug': 'technology-ai-regulation',
        'description': 'Replace multiple tech newsletters with one calm, signal-focused brief on AI, infrastructure, and regulation.',
        'tagline': 'Signal over Hype',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'cpu',
        'is_featured': True,
        'sort_order': 1,
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
        'name': 'Markets & Business',
        'slug': 'economy-markets',
        'description': 'Macro understanding without anxiety. Focus on trends and implications, not daily price movements.',
        'tagline': 'Trends, Not Ticks',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'trending-up',
        'is_featured': True,
        'sort_order': 4,
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
        'name': 'Climate & Energy',
        'slug': 'climate-energy-planet',
        'description': 'High-importance, low-noise clarity on climate policy, energy systems, and environmental science.',
        'tagline': "What's Actually Moving",
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'globe',
        'is_featured': True,
        'sort_order': 6,
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
        'default_sources': RECOMMENDED_SOURCES.get('policy-monitoring', []),
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
        'default_sources': RECOMMENDED_SOURCES.get('sector-intelligence', []),
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
        'default_sources': RECOMMENDED_SOURCES.get('internal-research', []),
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
        'default_sources': RECOMMENDED_SOURCES.get('thought-leadership', []),
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
        # Demoted from the global trial picker — narrow audience and high
        # cadence variability hurts the v1 conversion goal. Still selectable
        # from the marketplace.
        'is_featured': False,
        'sort_order': 20,
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
        'default_sources': RECOMMENDED_SOURCES.get('crypto-digital-assets', []),
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
        'default_sources': RECOMMENDED_SOURCES.get('trending-topics', []),
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
        'name': 'Health & Longevity',
        'slug': 'health-science-medicine',
        'description': 'Translational medicine, longevity research, and clinical practice — presented with appropriate uncertainty and consensus context.',
        'tagline': 'Evidence, Not Hype',
        'category': 'lifestyle',
        'audience_type': 'all',
        'icon': 'heart',
        # Promoted into the global picker: 8th featured slot. Slug unchanged
        # so existing briefings/templates references stay intact; display
        # name + sources tightened toward longevity / clinical practice.
        'is_featured': True,
        'sort_order': 8,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'default_accent_color': '#047857',
        'sample_output': SAMPLE_OUTPUTS.get('health-science-medicine', ''),
        'default_sources': RECOMMENDED_SOURCES.get('health-science-medicine', []),
        'default_filters': {
            'topics': ['Health', 'Longevity', 'Medicine', 'Clinical Practice'],
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
        'focus_keywords': ['research', 'study', 'guideline', 'evidence', 'trial', 'longevity', 'clinical'],
        'exclude_keywords': ['miracle', 'cure', 'breakthrough', 'shocking'],
    },
    # CATEGORY E - New featured presets (Block C of paid-briefings world-class build).
    # Round out the global /briefings/start picker to 8 with the highest-LTV
    # cohorts (startups), broad geopolitics, and Tyler Cowen-style ideas.
    {
        'name': 'Startups & Founders',
        'slug': 'startups-founders',
        'description': 'Build-in-public signal: company-building, product, and operator essays — without the LinkedIn motivation churn.',
        'tagline': 'Operators, Not Influencers',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'rocket',
        'is_featured': True,
        'sort_order': 2,
        'default_cadence': 'daily',
        'default_tone': 'calm_neutral',
        'default_accent_color': '#9333ea',
        'sample_output': '',
        'default_sources': RECOMMENDED_SOURCES.get('startups-founders', []),
        'default_filters': {
            'topics': ['Startups', 'Founders', 'Operators', 'Product', 'Venture'],
            'focus': ['company-building', 'product', 'fundraising', 'go-to-market'],
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
        'custom_prompt_prefix': 'Focus on operator-level signal: company-building, product decisions, fundraising mechanics, and go-to-market lessons. Avoid hot takes, motivation posts, and influencer commentary.',
        'focus_keywords': ['founder', 'startup', 'fundraise', 'go-to-market', 'product', 'operator', 'company-building'],
        'exclude_keywords': ['guru', 'crushed it', 'hustle', 'grindset'],
    },
    {
        'name': 'World Affairs',
        'slug': 'world-affairs',
        'description': 'Geopolitics, diplomacy, and global conflict — synthesised across regions without national-press bias.',
        'tagline': 'Across Borders',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'globe',
        'is_featured': True,
        'sort_order': 3,
        'default_cadence': 'daily',
        'default_tone': 'calm_neutral',
        'default_accent_color': '#0e7490',
        'sample_output': '',
        'default_sources': RECOMMENDED_SOURCES.get('world-affairs', []),
        'default_filters': {
            'topics': ['Geopolitics', 'Diplomacy', 'International Relations', 'Conflict'],
            'geography': 'global',
            'level': ['national', 'supranational', 'global'],
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
        'custom_prompt_prefix': 'Synthesize across regions and outlets to surface what changed in geopolitics, diplomacy, and conflicts. Surface implications, not personalities. Avoid single-national-press framing where possible.',
        'focus_keywords': ['diplomacy', 'treaty', 'conflict', 'sanctions', 'summit', 'foreign policy', 'geopolitics'],
        'exclude_keywords': ['scandal', 'gaffe', 'outrage'],
    },
    {
        'name': 'Science & Big Ideas',
        'slug': 'science-big-ideas',
        'description': 'Frontier research, long essays, and serious thinking — the brief you wish your smartest friend wrote.',
        'tagline': 'Frontier Thinking',
        'category': 'core_insight',
        'audience_type': 'all',
        'icon': 'lightbulb',
        'is_featured': True,
        'sort_order': 7,
        'default_cadence': 'weekly',
        'default_tone': 'calm_neutral',
        'default_accent_color': '#b45309',
        'sample_output': '',
        'default_sources': RECOMMENDED_SOURCES.get('science-big-ideas', []),
        'default_filters': {
            'topics': ['Science', 'Research', 'Ideas', 'Philosophy', 'Progress Studies'],
            'focus': ['frontier research', 'long essays', 'ideas'],
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
        'custom_prompt_prefix': 'Surface frontier research, long-form essays, and serious thinking on ideas that matter — across science, progress, and philosophy. Prefer depth over recency; cite primary sources where possible.',
        'focus_keywords': ['research', 'paper', 'essay', 'ideas', 'theory', 'progress', 'frontier'],
        'exclude_keywords': ['hot take', 'controversy', 'viral'],
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
