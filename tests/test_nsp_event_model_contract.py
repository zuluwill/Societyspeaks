from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_analytics_models_exist():
    source = _read("app/models.py")
    assert "class AnalyticsEvent" in source
    assert "class AnalyticsDailyAggregate" in source
    assert "uq_analytics_daily_dims" in source


def test_canonical_event_names_defined():
    source = _read("app/analytics/events.py")
    assert "CANONICAL_EVENT_NAMES" in source
    assert "'account_created'" in source
    assert "'discussion_viewed'" in source
    assert "'statement_voted'" in source
    assert "'response_created'" in source
    assert "'cohort_assigned'" in source
    assert "'analysis_generated'" in source


def test_rollup_job_is_scheduled():
    source = _read("app/scheduler.py")
    assert "rollup_analytics_daily_job" in source
    assert "rollup_analytics_daily(" in source


def test_programme_dashboard_endpoint_exists():
    source = _read("app/programmes/routes.py")
    assert "def programme_nsp_dashboard(" in source
    assert "schema_version': '1.0.0'" in source
