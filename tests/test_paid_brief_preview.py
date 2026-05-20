"""Dev-only preview: render the full paid brief email and dump it to /tmp.

Not a real assertion test — this just produces an HTML file you can open in
a browser to eyeball the design. Run with::

    python3 -m pytest tests/test_paid_brief_preview.py -s

and then open ``/tmp/paid_brief_preview.html`` and ``/tmp/paid_brief_body_only.html``.
"""
from types import SimpleNamespace

import pytest


def test_render_preview_full_email(app, db, tmp_path):
    from flask import render_template
    from app.models import (
        Briefing, BriefingSource, BriefRecipient, BriefRun, BriefRunItem, InputSource,
    )
    from app.briefing.generator import BriefingGenerator
    from app.lib.editorial import compute_coverage_distribution, UnderreportedPick
    from app.lib.time import utcnow_naive

    sources = [
        InputSource(owner_type='system', name='Ars Technica', type='rss',
                    config_json={'url': 'https://arstechnica.com/feed/'},
                    enabled=True, political_leaning=-0.2),
        InputSource(owner_type='system', name='The Verge', type='rss',
                    config_json={'url': 'https://theverge.com/rss'},
                    enabled=True, political_leaning=-0.1),
        InputSource(owner_type='system', name='MIT Technology Review', type='rss',
                    config_json={'url': 'https://technologyreview.com/feed'},
                    enabled=True, political_leaning=0.0),
        InputSource(owner_type='system', name='Wired', type='rss',
                    config_json={'url': 'https://wired.com/feed'},
                    enabled=True, political_leaning=-0.3),
        InputSource(owner_type='system', name='The Telegraph', type='rss',
                    config_json={'url': 'https://telegraph.co.uk/rss'},
                    enabled=True, political_leaning=0.6),
    ]
    for s in sources:
        db.session.add(s)
    db.session.flush()

    briefing = Briefing(
        name='My Technology, AI & Regulation',
        owner_type='user', owner_id=1, status='active',
        accent_color='#7c3aed',
        max_items=8,
    )
    db.session.add(briefing)
    db.session.flush()
    for s in sources:
        db.session.add(BriefingSource(briefing_id=briefing.id, source_id=s.id))

    run = BriefRun(
        briefing_id=briefing.id,
        scheduled_at=utcnow_naive(),
        status='approved',
        generated_at=utcnow_naive(),
    )
    db.session.add(run)
    db.session.flush()

    stories = [
        dict(category='TECHNOLOGY',
             headline='Google unveils on-device AI agents that draft research briefs',
             source='Ars Technica',
             source_url='https://arstechnica.com/example/google-agents',
             bullets=[
                 'Gemini agents now run locally on Pixel and Chromebook devices for privacy-sensitive work.',
                 'Early benchmarks show 40% faster summarisation than the cloud equivalent on the same prompts.',
                 'Watch for the enterprise SKU launch — pricing will signal who Google sees as the real buyer.',
             ],
             markdown='Google Research argues the local-first approach makes regulatory exposure easier to manage, since user prompts never leave the device. Whether that survives contact with corporate procurement teams is another question.',
             cluster=[
                 {'name': 'The Verge', 'url': 'https://theverge.com/example/google'},
                 {'name': 'MIT Technology Review', 'url': 'https://technologyreview.com/example/google'},
             ],
             context_label='Market Impact',
             context_insight='If on-device agents become the default, the entire LLM cloud economics story shifts: less inference revenue, more chip revenue.'),
        dict(category='REGULATION',
             headline='EU finalises AI Act Article 28 — code-of-practice deadline brought forward',
             source='The Telegraph',
             source_url='https://telegraph.co.uk/example/eu-ai',
             bullets=[
                 'Member states must transpose the foundation-model code of practice by Q3 2026.',
                 'Open-source projects below the 25 PFLOP/s threshold get a partial exemption.',
                 'Enforcement guidance for the EU AI Office still pending — the unknown unknown.',
             ],
             markdown='Industry response has been muted, possibly because the Article 28 changes mostly clarify existing obligations rather than impose new ones. The bigger uncertainty sits with the Office.',
             cluster=[],
             context_label='Policy Context',
             context_insight='This is the AI Act becoming concrete. Compliance teams should already have the foundation-model checklist drafted — if not, that is the week-one ask.'),
        dict(category='RESEARCH',
             headline='Anthropic paper shows interpretability gains in 70B-parameter sparse models',
             source='MIT Technology Review',
             source_url='https://technologyreview.com/example/anthropic',
             bullets=[
                 'Researchers identify 18,000+ interpretable features in a single forward pass.',
                 'Suggests scaling interpretability is more tractable than feared in 2024.',
                 'No safety claims attached — this is a measurement result, not a control result.',
             ],
             markdown='The headline metric is "feature density per parameter," which roughly tripled versus the 2025 baseline at the same model size. Worth reading the appendix for the caveat on cross-layer features.',
             cluster=[],
             context_label='What This Means',
             context_insight='If this generalises, the "we cannot inspect what frontier models are doing" position becomes harder to defend — which changes regulatory leverage too.'),
        dict(category='TECHNOLOGY',
             headline='Apple opens Vision Pro foundation models to third-party developers',
             source='Wired',
             source_url='https://wired.com/example/apple-vision',
             bullets=[
                 'Developers can fine-tune on-device vision models without cloud round-trips.',
                 'Tooling ships in Xcode 19 beta this month; production GA targeted for late 2026.',
                 'Apple holds the safety review — unclear what that does to time-to-market.',
             ],
             markdown='Apple is repositioning Vision Pro from a consumer device to a developer platform. The numbers will turn on whether enterprise spatial-computing use-cases actually exist at scale.',
             cluster=[
                 {'name': 'Ars Technica', 'url': 'https://arstechnica.com/example/apple-vision'},
             ],
             context_label='Why It Matters',
             context_insight='This is Apple admitting that without third-party developers the Vision Pro narrative is finished. Watch which developers actually show up.'),
    ]

    for i, s in enumerate(stories, start=1):
        db.session.add(BriefRunItem(
            brief_run_id=run.id, position=i,
            headline=f"[{s['category']}] {s['headline']}",
            topic_category=s['category'],
            source_name=s['source'],
            source_url=s['source_url'],
            summary_bullets=s['bullets'],
            content_markdown=s['markdown'],
            cluster_also_covered=s['cluster'] or None,
            context_label=s['context_label'],
            context_insight=s['context_insight'],
        ))
    db.session.commit()
    db.session.refresh(run)

    coverage = compute_coverage_distribution([
        SimpleNamespace(source=src) for src in sources
    ])
    underreported = UnderreportedPick(
        title='Quiet European research consortium publishes open-weight vision model',
        source_name='MIT Technology Review',
        url='https://technologyreview.com/example/underreported',
        summary=(
            'A consortium of European universities released a 13B-parameter open-weight vision model with permissive licensing. '
            'Coverage was light — only one of your sources picked it up — but the licence terms are unusually clean.'
        ),
        published_at=utcnow_naive(),
    )

    generator = BriefingGenerator()
    body_html = generator._render_html(
        brief_run=run, briefing=briefing,
        intro_text=(
            "Three threads today: on-device AI is graduating from research to product, "
            "the EU AI Act stops being abstract, and an Anthropic paper changes the "
            "interpretability conversation. One story your sources caught that almost nobody else did."
        ),
        key_takeaways=[
            'On-device agents and open-weight models both keep moving the centre of gravity away from a few cloud incumbents.',
            'EU AI Act compliance is now a 2026 problem, not a 2027 one — start the foundation-model checklist this quarter.',
            'Interpretability research is closing faster than the regulatory debate assumed in early 2025.',
        ],
        coverage_block=coverage,
        underreported=underreported,
    )

    # Render the email shell that wraps the body (this is what subscribers see).
    recipient = BriefRecipient(briefing_id=briefing.id, email='preview@example.com', status='active')
    db.session.add(recipient)
    db.session.commit()
    full_email = render_template(
        'emails/brief_run.html',
        brief_run=run, briefing=briefing, recipient=recipient,
        content_html=body_html,
        intro_text="On-device AI is graduating from research to product…",
        view_url='https://example.test/preview',
        reader_url='https://example.test/reader',
        unsubscribe_url='https://example.test/unsubscribe',
        base_url='https://example.test',
        company_logo_url=None,
        items=list(run.items),
        has_audio=False,
    )

    with open('/tmp/paid_brief_preview.html', 'w') as f:
        f.write(full_email)
    with open('/tmp/paid_brief_body_only.html', 'w') as f:
        f.write('<!doctype html><html><head><meta charset="utf-8"><title>Body preview</title></head>'
                '<body style="margin:0;padding:40px;background:#f1f5f9;">'
                '<div style="max-width:640px;margin:0 auto;background:#ffffff;padding:32px 28px;border-radius:8px;">'
                + body_html +
                '</div></body></html>')

    # Lightweight sanity assertions so this still counts as a test.
    assert 'Today' in body_html
    assert 'EU finalises AI Act' in body_html
    assert 'Coverage perspective' in body_html
    assert 'Under the radar' in body_html
    assert 'Sources today' in body_html
