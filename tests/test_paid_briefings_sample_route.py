"""
Tests for the public /briefings/sample page (Block C).

Covers:
  - flag off → 404 (page is part of the self-serve trial funnel)
  - flag on, no demo briefing configured → renders fallback template sample_output
  - flag on, demo briefing has a sent BriefRun → renders that run's approved_html
  - flag on, demo briefing id is invalid → falls back to template sample_output
"""
import pytest

from app.models.briefing import BriefTemplate


def _seed_template_with_sample(db, slug='technology-ai-regulation', sample_html='<p>SAMPLE</p>'):
    tpl = BriefTemplate(
        slug=slug,
        name='AI & Technology',
        description='AI & tech',
        category='core_insight',
        audience_type='all',
        is_featured=True,
        is_active=True,
        default_sources=[],
        default_cadence='daily',
        default_tone='balanced',
        sample_output=sample_html,
        custom_prompt_prefix='',
        configurable_options={},
        guardrails={},
    )
    db.session.add(tpl)
    db.session.flush()
    return tpl


@pytest.fixture
def trial_app(app):
    app.config['SELF_SERVE_TRIAL_ENABLED'] = True
    yield app
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False


def test_sample_flag_off_returns_404(app, db):
    app.config['SELF_SERVE_TRIAL_ENABLED'] = False
    client = app.test_client()
    resp = client.get('/briefings/sample')
    assert resp.status_code == 404


def test_sample_flag_on_no_demo_briefing_uses_template_sample_output(trial_app, db):
    with trial_app.app_context():
        _seed_template_with_sample(db, sample_html='<p>TEMPLATE FALLBACK HTML</p>')
        db.session.commit()

    trial_app.config['BRIEFING_SAMPLE_DEMO_BRIEFING_ID'] = None

    client = trial_app.test_client()
    resp = client.get('/briefings/sample')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'TEMPLATE FALLBACK HTML' in body
    # Primary CTA points at /briefings/start.
    assert '/briefings/start' in body


def test_sample_with_invalid_demo_id_falls_back_to_template(trial_app, db):
    with trial_app.app_context():
        _seed_template_with_sample(db, sample_html='<p>FALLBACK USED</p>')
        db.session.commit()

    trial_app.config['BRIEFING_SAMPLE_DEMO_BRIEFING_ID'] = 999999

    client = trial_app.test_client()
    resp = client.get('/briefings/sample')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'FALLBACK USED' in body


def test_sample_renders_demo_briefing_run_when_available(trial_app, db):
    from app.models.briefing import Briefing, BriefRun
    from app.lib.time import utcnow_naive

    with trial_app.app_context():
        # Seed a fallback template so we can detect that the route picked
        # the briefing path over the fallback.
        _seed_template_with_sample(db, sample_html='<p>FALLBACK</p>')

        briefing = Briefing(
            owner_type='user', owner_id=1,  # dummy — sample route doesn't check ownership
            name='Demo Brief',
            cadence='daily', timezone='UTC', preferred_send_hour=7,
            mode='auto_send', visibility='public', status='active',
        )
        db.session.add(briefing)
        db.session.flush()

        run = BriefRun(
            briefing_id=briefing.id,
            status='sent',
            scheduled_at=utcnow_naive(),
            sent_at=utcnow_naive(),
            approved_html='<p>DEMO RUN HTML</p>',
        )
        db.session.add(run)
        db.session.commit()

        trial_app.config['BRIEFING_SAMPLE_DEMO_BRIEFING_ID'] = briefing.id

    client = trial_app.test_client()
    resp = client.get('/briefings/sample')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'DEMO RUN HTML' in body
    assert 'FALLBACK' not in body


def test_sample_heading_escapes_the_template_name_once(trial_app, db):
    """'AI & Technology' must reach the page as one entity, not '&amp;amp;' (shown as '&amp;')."""
    with trial_app.app_context():
        _seed_template_with_sample(db)
        db.session.commit()
    trial_app.config['BRIEFING_SAMPLE_DEMO_BRIEFING_ID'] = None
    body = trial_app.test_client().get('/briefings/sample').get_data(as_text=True)
    assert 'AI &amp; Technology brief' in body
    assert '&amp;amp;' not in body


def test_refresh_brief_template_samples_changes_only_the_example(app, db):
    """The CLI updates sample_output and leaves admin-edited fields alone."""
    from app.models.briefing import BriefTemplate
    with app.app_context():
        tpl = _seed_template_with_sample(db, sample_html='<p>OLD</p>')
        tpl.name = 'Edited in admin'
        db.session.commit()
        runner = app.test_cli_runner()
        dry = runner.invoke(args=['refresh-brief-template-samples', '--dry-run'])
        assert 'would update' in dry.output
        assert db.session.get(BriefTemplate, tpl.id).sample_output == '<p>OLD</p>'
        result = runner.invoke(args=['refresh-brief-template-samples'])
        assert result.exit_code == 0, result.output
        fresh = db.session.get(BriefTemplate, tpl.id)
        assert 'Larkspur Labs' in fresh.sample_output and 'OpenAI' not in fresh.sample_output
        assert fresh.name == 'Edited in admin'
