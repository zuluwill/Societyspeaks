"""Unit tests for EmailEvent.compute_rate_metrics (DRY rate definitions)."""

import pytest

from app.models.email import EmailEvent


def test_compute_rate_metrics_ctr_and_open_vs_delivered():
    r = EmailEvent.compute_rate_metrics(
        total_sent=100,
        total_delivered=90,
        total_opened=45,
        total_clicked=18,
        total_bounced=2,
        total_complained=1,
        engagement_basis="delivered",
    )
    assert r["open_rate"] == 50.0
    assert r["click_rate"] == pytest.approx(20.0)
    assert r["click_to_open_rate"] == 40.0
    assert r["complaint_rate"] == pytest.approx(100 * 1 / 90, rel=0.01)
    assert r["delivery_rate"] == pytest.approx(90.0)
    assert r["delivery_rate_estimated"] is False
    assert r["bounce_rate"] == 2.0


def test_compute_rate_metrics_na_when_no_delivered_events():
    r = EmailEvent.compute_rate_metrics(
        total_sent=1000,
        total_delivered=0,
        total_opened=50,
        total_clicked=30,
        total_bounced=0,
        total_complained=0,
        engagement_basis="delivered",
    )
    assert r["open_rate"] is None
    assert r["click_rate"] is None
    assert r["complaint_rate"] is None
    assert r["delivery_rate"] is None


def test_compute_rate_metrics_delivery_estimated_from_bounces():
    r = EmailEvent.compute_rate_metrics(
        total_sent=100,
        total_delivered=0,
        total_opened=0,
        total_clicked=0,
        total_bounced=5,
        total_complained=0,
        engagement_basis="delivered",
    )
    assert r["delivery_rate"] == 95.0
    assert r["delivery_rate_estimated"] is True


def test_compute_rate_metrics_sent_basis_briefing_style():
    r = EmailEvent.compute_rate_metrics(
        total_sent=200,
        total_delivered=0,
        total_opened=80,
        total_clicked=20,
        engagement_basis="sent",
    )
    assert r["open_rate"] == 40.0
    assert r["click_rate"] == 10.0
    assert r["click_to_open_rate"] == 25.0


def test_compute_rate_metrics_ctor_na_when_zero_opens():
    r = EmailEvent.compute_rate_metrics(
        total_sent=10,
        total_delivered=10,
        total_opened=0,
        total_clicked=5,
        engagement_basis="delivered",
    )
    assert r["click_to_open_rate"] is None


def test_compute_rate_metrics_invalid_basis():
    with pytest.raises(ValueError):
        EmailEvent.compute_rate_metrics(
            1, 1, 1, 1, 0, 0, engagement_basis="invalid"  # type: ignore[arg-type]
        )
