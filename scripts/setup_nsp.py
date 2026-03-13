#!/usr/bin/env python3
"""
One-shot setup script for the National Strategy Project on Society Speaks.

Creates:
  - NSP company profile + Catherine Day's user account
  - Luke Blackaby's user account + individual profile (so login works) + org admin membership
  - The NSP programme: "Britain in the Next 50 Years: The National Dialogue"
  - 8 seed discussions linked to the programme, each with 7 seed statements covering a range of views

Safe to re-run — all operations check for existing records first.

Usage:
    python scripts/setup_nsp.py [--send-emails]

    --send-emails   Send welcome emails to Catherine and Luke (default: off,
                    so you can verify everything before notifying them)
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User, CompanyProfile, IndividualProfile, Programme, Discussion, OrganizationMember, Statement
from app.lib.time import utcnow_naive
from werkzeug.security import generate_password_hash

# ── Credentials ────────────────────────────────────────────────────────────────
# Passwords are read from environment variables — never hardcode them here.
# Set these before running:
#   export NSP_CATHERINE_PASSWORD='<choose a strong password>'
#   export NSP_LUKE_PASSWORD='<choose a strong password>'
CATHERINE_USERNAME = 'catherine-day-nsp'
CATHERINE_EMAIL    = 'Catherine@nationalstrategy.uk'

LUKE_USERNAME = 'luke-blackaby-nsp'
LUKE_EMAIL    = 'Luke@nationalstrategy.uk'


def _get_passwords():
    catherine_pw = os.environ.get('NSP_CATHERINE_PASSWORD')
    luke_pw = os.environ.get('NSP_LUKE_PASSWORD')
    missing = []
    if not catherine_pw:
        missing.append('NSP_CATHERINE_PASSWORD')
    if not luke_pw:
        missing.append('NSP_LUKE_PASSWORD')
    if missing:
        print(f'\nERROR: Missing required environment variable(s): {", ".join(missing)}')
        print('Set them before running:')
        for var in missing:
            print(f'  export {var}="<strong-password>"')
        sys.exit(1)
    return catherine_pw, luke_pw

# ── Organisation content ───────────────────────────────────────────────────────
ORG_NAME        = 'National Strategy Project'
ORG_DESCRIPTION = (
    'The National Strategy Project (NSP) is an ambitious, independent, cross-sector '
    'initiative to give the UK something it has never had but urgently needs: a trusted '
    'way to understand what the country really wants for its long-term future — and a '
    'practical system to act on it.\n\n'
    'At a time of rising uncertainty, economic pressure, fractured trust and institutional '
    'fatigue, the NSP brings people together across politics, generations, sectors, regions '
    'and the whole of society to co-create a vision for the UK\'s future and shape the '
    'blueprint to achieve it.\n\n'
    'Co-founded by Catherine Day (former Cabinet Office, No.10, FCDO), Robyn Scott '
    '(CEO Apolitical) and Matthew Rycroft (former UK Home Office Permanent Secretary '
    'and UN Ambassador), the NSP draws on deep experience of how government succeeds, '
    'where it fails, and what is missing.\n\n'
    'This is not a party, campaign or advocacy effort. It is a non-partisan public-good '
    'initiative designed to give any government — and the whole country — the clarity, '
    'consent and capability needed to act on the long term.'
)
ORG_WEBSITE = 'https://www.nationalstrategy.uk'
ORG_CITY    = 'London'
ORG_COUNTRY = 'United Kingdom'
ORG_EMAIL   = 'Catherine@nationalstrategy.uk'

# ── Programme content ──────────────────────────────────────────────────────────
PROGRAMME_NAME        = 'Britain in the Next 50 Years: The National Dialogue'
PROGRAMME_DESCRIPTION = (
    'Britain has a future — but it won\'t be like the past. Over the next 50 years the '
    'UK faces demographic shifts, climate change, digital transformation, and deep '
    'questions about how we organise our society and economy. The choices we make now '
    'will shape the country our children and grandchildren inherit.\n\n'
    'This national dialogue invites you to share your views on the long-term choices '
    'facing the UK — from healthcare and housing to the economy, democracy, and our '
    'place in the world. There are no right answers. What matters is hearing what the '
    'British public really thinks, across every region, generation and background.\n\n'
    'This is a world-first, large-scale deliberation combining online participation, '
    'a representative "UK in One Room" event, and deep community outreach — giving the '
    'whole country a trusted, evidence-based picture of where informed public consent lies.\n\n'
    'Your voice shapes Britain\'s long-term future. Join the conversation.'
)
PROGRAMME_THEMES = [
    'Health & Social Care',
    'Economy & Prosperity',
    'Housing',
    'Climate & Environment',
    'Democracy & Governance',
    'Immigration & Integration',
    'Digital & Cyber Security',
    'Social Cohesion',
    'Education & Skills',
    'Defence & Security',
]

# ── Seed discussions ───────────────────────────────────────────────────────────
SEED_DISCUSSIONS = [
    {
        'title': 'How should the UK redesign health and social care for an ageing population?',
        'description': (
            'The UK population is ageing fast — by 2072, roughly 27% of the population will be '
            'over 65. Rising demand for healthcare and social care is unavoidable. The question is '
            'how we redesign the system to cope: funding models, NHS reform, social care, '
            'workforce, and the role of prevention versus treatment. What should the UK prioritise?'
        ),
        'topic': 'Healthcare',
        'programme_theme': 'Health & Social Care',
        'statements': [
            'The UK should move to a single, integrated health and social care system funded from general taxation.',
            'Prevention and early intervention should receive a much larger share of health spending than today.',
            'Social care should remain separate from the NHS but with guaranteed national standards and funding.',
            'Private and voluntary providers should play a bigger role in delivering care, with the state funding and regulating.',
            'We should prioritise fixing workforce pay and conditions so we can recruit and retain enough staff.',
            'Individuals and families who can afford it should contribute more to their own care in later life.',
            'The focus should be on keeping people healthy and independent for longer, not just treating illness.',
        ],
    },
    {
        'title': 'What kind of economic growth should Britain prioritise over the next 50 years?',
        'description': (
            'Economic growth is often treated as the only route to sustaining a high-service '
            'society — but "growth" is not one thing. Should the UK prioritise more output, higher '
            'median living standards, lower inequality, regional balance, or resilience in an '
            'ageing society? And how should we fix the tax and benefit design that quietly punishes '
            'work, training and risk-taking?'
        ),
        'topic': 'Economy',
        'programme_theme': 'Economy & Prosperity',
        'statements': [
            'Raising median living standards should matter more than total GDP growth.',
            'The tax and benefit system should be redesigned so work and training are never penalised.',
            'Regional balance is essential; growth should not be concentrated in London and the South East.',
            'The UK should prioritise productivity and innovation over simply expanding the workforce.',
            'Lower inequality is a goal in itself and makes the economy more resilient.',
            'We need a smaller state and lower taxes to unlock private investment and enterprise.',
            'Stability and predictability for business matter more than headline growth rates.',
        ],
    },
    {
        'title': 'How do we solve the UK\'s housing crisis over the next 50 years?',
        'description': (
            'Housing is one of the UK\'s most damaging self-made constraints — touching living '
            'standards, family formation, regional mobility and economic opportunity. Should the UK '
            'treat housing as infrastructure and build enough of it, or continue to protect it as a '
            'scarce financial asset? What planning reforms, land-use choices and investment are needed?'
        ),
        'topic': 'Society',
        'programme_theme': 'Housing',
        'statements': [
            'Housing should be treated as essential infrastructure and we should build enough to meet need.',
            'Planning reform is necessary but must protect environment and community character.',
            'The green belt should be reformed so we can build more homes where people want to live.',
            'Local communities should have the final say on new development in their area.',
            'More social and affordable housing is essential; the market alone will not deliver it.',
            'House prices should be allowed to fall; affordability matters more than existing owners\' wealth.',
            'We should prioritise brownfield and urban densification over greenfield building.',
        ],
    },
    {
        'title': 'What is the right pace and scale of net zero — and who should bear the cost?',
        'description': (
            'Climate action is a practical necessity, but "climate policy" bundles different things: '
            'cutting emissions, preparing for impacts, and protecting nature. Is there a trade-off '
            'between decarbonisation and growth? How do we balance ambition with fairness — ensuring '
            'costs are not carried disproportionately by those least able to bear them?'
        ),
        'topic': 'Environment',
        'programme_theme': 'Climate & Environment',
        'statements': [
            'The costs of net zero should be shared so lower-income households are not disproportionately hit.',
            'The UK should maintain ambitious decarbonisation targets even if they involve short-term economic trade-offs.',
            'The pace of net zero should be slowed to protect jobs and competitiveness.',
            'Those who have contributed most to emissions should bear the greatest cost of the transition.',
            'Technology and innovation will solve most of the problem; we should avoid heavy-handed regulation.',
            'Nature restoration and adaptation to climate impacts deserve as much focus as cutting emissions.',
            'The UK should act in step with other countries; going faster alone has limited benefit.',
        ],
    },
    {
        'title': 'How much should the UK devolve power away from Westminster to regions and communities?',
        'description': (
            'The UK is highly centralised — a model that is increasingly dysfunctional as local '
            'variation grows and demand for locally delivered services rises. Should we give regions '
            'and local areas meaningful fiscal power and accountability? What does a well-functioning, '
            'trusted state look like in the 2050s — and how do we get there?'
        ),
        'topic': 'Politics',
        'programme_theme': 'Democracy & Governance',
        'statements': [
            'Regions and local areas should have meaningful fiscal power and accountability.',
            'A well-functioning UK state in 2050 will require less centralisation than we have today.',
            'England should have its own devolved settlement, similar to Scotland and Wales.',
            'Too much devolution would create a patchwork; some things must stay national.',
            'Elected mayors and combined authorities are the right level for real decision-making.',
            'Central government should set standards and outcomes but let local areas decide how to deliver.',
            'We should strengthen local democracy with more powers and resources, not just symbolism.',
        ],
    },
    {
        'title': 'How should Britain manage immigration to meet labour needs while maintaining public trust?',
        'description': (
            'If the UK wants a growing workforce and enough staff for health, care, construction and '
            'technology, migration matters. If it wants lower migration, it must substitute through '
            'higher domestic training, higher participation and later retirement. There is no free '
            'option. How should the UK design a stable, honest long-term approach to immigration?'
        ),
        'topic': 'Society',
        'programme_theme': 'Immigration & Integration',
        'statements': [
            'The UK should set a stable long-term migration policy linked to labour and skills needs.',
            'Domestic training and workforce participation should be prioritised before relying on migration.',
            'Immigration levels should be reduced; integration works better when numbers are manageable.',
            'Sectors like health and social care need migration; we should be honest about that dependency.',
            'Public consent matters; policy should follow what the majority say they want.',
            'A points-based system is the right approach; we should refine it, not abandon it.',
            'The focus should be on integration and cohesion, not just controlling numbers.',
        ],
    },
    {
        'title': 'How do we rebuild trust in democracy and public institutions?',
        'description': (
            'Trust in government, public institutions and democratic processes has fallen sharply. '
            'Trust is often treated as a cultural problem — but it is more often an engineering '
            'problem: reliability, responsiveness, integrity and fairness. What practical steps '
            'should the UK take to rebuild the relationship between citizens and the institutions '
            'that serve them?'
        ),
        'topic': 'Politics',
        'programme_theme': 'Democracy & Governance',
        'statements': [
            'Rebuilding trust is mainly about delivery: reliability, responsiveness and fairness.',
            'Citizens should have a formal role in holding institutions to account beyond elections.',
            'Electoral reform would help; proportional representation would make Parliament more representative.',
            'The real problem is media and polarisation; institutions are not the main cause.',
            'Transparency and accountability — including for ministers and officials — must be strengthened.',
            'We need fewer quangos and less bureaucracy; that would restore trust.',
            'Civic education and participation from an early age would rebuild long-term trust in democracy.',
        ],
    },
    {
        'title': 'How should the UK protect itself from growing cyber threats while maintaining a free and open digital economy?',
        'description': (
            'The UK is now a digital society sitting on privately run networks and global technology '
            'stacks. Cyber crime generates estimated losses of £14.7 billion annually — and a '
            'catastrophic cascade failure is a credible risk. How far should the state push baseline '
            'standards? How do we share burdens between firms, citizens and government? And how do '
            'we build an online "security state" — not a surveillance state?'
        ),
        'topic': 'Technology',
        'programme_theme': 'Digital & Cyber Security',
        'statements': [
            'The state should set baseline security standards for critical digital infrastructure.',
            'The UK should avoid surveillance-style solutions; security can be achieved without undermining privacy.',
            'Industry should lead on standards; government should only step in where the market fails.',
            'Strong encryption must be protected; backdoors would weaken security for everyone.',
            'The public sector and critical national infrastructure need mandatory security requirements.',
            'International cooperation is essential; the UK cannot solve cyber threats alone.',
            'Citizens and small businesses need better guidance and support to protect themselves online.',
        ],
    },
]


def create_user(username, email, password, label):
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f'  ✓ {label} already exists (id={existing.id})')
        return existing
    user = User(
        username=username,
        email=email,
        password=generate_password_hash(password),
    )
    db.session.add(user)
    db.session.flush()
    print(f'  + Created {label}: {username} <{email}> (id={user.id})')
    return user


def send_welcome(email, username, password, app):
    """Mirror of admin.routes.send_welcome_email."""
    import requests
    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        print(f'  ! RESEND_API_KEY not set — skipping welcome email for {email}')
        return
    base_url = os.environ.get('BASE_URL', 'https://societyspeaks.io')
    from_email = os.environ.get('RESEND_FROM_EMAIL', 'Society Speaks <hello@societyspeaks.io>')
    html = f"""
    <p>Hello {username},</p>
    <p>Your Society Speaks account has been created as part of the National Strategy Project setup.</p>
    <p><strong>Username:</strong> {username}<br>
       <strong>Password:</strong> {password}<br>
       <strong>Login:</strong> <a href="{base_url}/auth/login">{base_url}/auth/login</a></p>
    <p>Please change your password after first login.</p>
    <p>— Society Speaks</p>
    """
    resp = requests.post(
        'https://api.resend.com/emails',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={'from': from_email, 'to': [email], 'subject': 'Your Society Speaks account', 'html': html},
        timeout=10,
    )
    if resp.status_code in (200, 201):
        print(f'  ✉  Welcome email sent to {email}')
    else:
        print(f'  ! Failed to send email to {email}: {resp.status_code} {resp.text}')


def main(send_emails=False):
    catherine_pw, luke_pw = _get_passwords()
    app = create_app()
    with app.app_context():
        print('\n── NSP Setup ──────────────────────────────────────')

        # 1. Users
        print('\n[1/6] Users')
        catherine = create_user(CATHERINE_USERNAME, CATHERINE_EMAIL, catherine_pw, 'Catherine Day')
        luke = create_user(LUKE_USERNAME, LUKE_EMAIL, luke_pw, 'Luke Blackaby')
        db.session.flush()

        # 2. Company profile
        print('\n[2/6] Company profile')
        profile = CompanyProfile.query.filter_by(user_id=catherine.id).first()
        if not profile:
            profile = CompanyProfile(
                user_id=catherine.id,
                company_name=ORG_NAME,
                description=ORG_DESCRIPTION,
                website=ORG_WEBSITE,
                city=ORG_CITY,
                country=ORG_COUNTRY,
                email=ORG_EMAIL,
            )
            db.session.add(profile)
            db.session.flush()
            print(f'  + Created company profile: {ORG_NAME} (id={profile.id}, slug={profile.slug})')
        else:
            print(f'  ✓ Company profile already exists (id={profile.id})')
        catherine.profile_type = 'company'

        # 3. Luke's individual profile (required so login doesn't redirect to profile setup)
        print('\n[3/6] Luke\'s individual profile')
        luke_profile = IndividualProfile.query.filter_by(user_id=luke.id).first()
        if not luke_profile:
            luke_profile = IndividualProfile(
                user_id=luke.id,
                full_name='Luke Blackaby',
                email=LUKE_EMAIL,
                country='United Kingdom',
            )
            luke.profile_type = 'individual'
            db.session.add(luke_profile)
            db.session.flush()
            print(f'  + Created individual profile for Luke (id={luke_profile.id})')
        else:
            print(f'  ✓ Luke\'s individual profile already exists (id={luke_profile.id})')

        # 4. Luke as org admin member
        print('\n[4/6] Organisation membership')
        existing_member = OrganizationMember.query.filter_by(
            org_id=profile.id, user_id=luke.id
        ).first()
        if existing_member:
            print(f'  ✓ Luke already an org member (role={existing_member.role})')
        else:
            member = OrganizationMember(
                org_id=profile.id,
                user_id=luke.id,
                role='admin',
                status='active',
                invited_by_id=catherine.id,
                joined_at=utcnow_naive(),
            )
            db.session.add(member)
            print(f'  + Added Luke as org admin member')

        # 5. Programme
        print('\n[5/6] Programme')
        programme = Programme.query.filter_by(
            company_profile_id=profile.id,
            name=PROGRAMME_NAME,
        ).first()
        if not programme:
            programme = Programme(
                name=PROGRAMME_NAME,
                description=PROGRAMME_DESCRIPTION,
                geographic_scope='country',
                country='United Kingdom',
                themes=PROGRAMME_THEMES,
                visibility='public',
                status='active',
                company_profile_id=profile.id,
                creator_id=None,
            )
            db.session.add(programme)
            db.session.flush()
            print(f'  + Created programme: {PROGRAMME_NAME} (id={programme.id}, slug={programme.slug})')
        else:
            print(f'  ✓ Programme already exists (id={programme.id})')

        # 6. Seed discussions
        print('\n[6/6] Seed discussions')
        for disc_data in SEED_DISCUSSIONS:
            existing = Discussion.query.filter_by(
                title=disc_data['title'],
                programme_id=programme.id,
            ).first()
            if existing:
                print(f'  ✓ Already exists: {disc_data["title"][:60]}…')
                continue
            disc = Discussion(
                title=disc_data['title'],
                description=disc_data['description'],
                topic=disc_data['topic'],
                programme_id=programme.id,
                programme_theme=disc_data['programme_theme'],
                company_profile_id=profile.id,
                creator_id=catherine.id,
                geographic_scope='country',
                country='United Kingdom',
                has_native_statements=True,
                is_closed=False,
            )
            db.session.add(disc)
            db.session.flush()
            for stmt_content in disc_data.get('statements', []):
                if len(stmt_content.strip()) < 10:
                    continue
                stmt = Statement(
                    discussion_id=disc.id,
                    user_id=catherine.id,
                    content=stmt_content.strip()[:500],
                    statement_type='claim',
                    is_seed=True,
                    source='partner_provided',
                )
                db.session.add(stmt)
            print(f'  + Discussion: {disc_data["title"][:70]}… ({len(disc_data.get("statements", []))} statements)')

        db.session.commit()
        print('\n── Done ────────────────────────────────────────────')
        print(f'\n  Organisation page : /profiles/profile/company/{profile.slug}')
        print(f'  Programme page    : /programmes/{programme.slug}')
        print(f'  Admin manage page : /admin/company/{profile.id}/manage')
        print(f'\n  Catherine login   : {CATHERINE_EMAIL} / <NSP_CATHERINE_PASSWORD>')
        print(f'  Luke login        : {LUKE_EMAIL} / <NSP_LUKE_PASSWORD>')

        if send_emails:
            print('\n── Sending welcome emails ──────────────────────────')
            send_welcome(CATHERINE_EMAIL, CATHERINE_USERNAME, catherine_pw, app)
            send_welcome(LUKE_EMAIL, LUKE_USERNAME, luke_pw, app)
        else:
            print('\n  (Welcome emails not sent — run with --send-emails when ready)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Set up NSP on Society Speaks')
    parser.add_argument('--send-emails', action='store_true',
                        help='Send welcome emails to Catherine and Luke after setup')
    args = parser.parse_args()
    main(send_emails=args.send_emails)
