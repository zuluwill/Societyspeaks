"""HTTP probe behaviour for journey_reading_link_probe (no network)."""

from unittest.mock import patch

from app.programmes import journey_reading_link_probe as probe_mod


def test_probe_url_head_success_short_circuits():
    with patch.object(probe_mod, "_request_once", return_value=(200, None)) as m:
        out = probe_mod.probe_url("https://example.com/", timeout=5.0)
    assert out.ok and out.status == 200 and out.method == "HEAD"
    m.assert_called_once()


def test_probe_url_falls_back_to_get_after_head_405():
    calls = []

    def side_effect(url, method, timeout, ctx):
        calls.append(method)
        if method == "HEAD":
            return 405, None
        return 200, None

    with patch.object(probe_mod, "_request_once", side_effect=side_effect):
        out = probe_mod.probe_url("https://example.com/", timeout=5.0)
    assert out.ok and out.status == 200 and out.method == "GET"
    assert calls == ["HEAD", "GET"]


def test_probe_url_retries_get_after_head_404():
    calls = []

    def side_effect(url, method, timeout, ctx):
        calls.append(method)
        if method == "HEAD":
            return 404, None
        return 200, None

    with patch.object(probe_mod, "_request_once", side_effect=side_effect):
        out = probe_mod.probe_url("https://example.com/page", timeout=5.0)
    assert out.ok and out.status == 200 and out.method == "GET"
    assert calls == ["HEAD", "GET"]


def test_probe_url_head_404_and_get_404_fails():
    with patch.object(probe_mod, "_request_once", return_value=(404, None)) as m:
        out = probe_mod.probe_url("https://example.com/missing", timeout=5.0)
    assert not out.ok and out.status == 404
    assert m.call_count == 2


def test_probe_url_persistent_429_is_soft():
    with patch.object(probe_mod, "_request_once", return_value=(429, None)):
        with patch.object(probe_mod.time, "sleep"):
            out = probe_mod.probe_url("https://example.com/rate-limited", timeout=5.0)
    assert not out.ok and out.status == 429 and out.soft_forbidden


def test_probe_url_444_is_soft_even_when_host_not_walled():
    # Use a non-walled host so soft_forbidden comes from the 444 status
    # classifier, not from _BOT_WALLED_HOSTS (bmvg.de is already walled).
    with patch.object(probe_mod, "_request_once", return_value=(444, None)):
        out = probe_mod.probe_url("https://example.com/closed", timeout=5.0)
    assert not out.ok and out.status == 444 and out.soft_forbidden


def test_probe_url_bot_walled_timeout_is_soft():
    def side_effect(url, method, timeout, ctx):
        return None, "The read operation timed out"

    with patch.object(probe_mod, "_request_once", side_effect=side_effect):
        with patch.object(probe_mod.time, "sleep"):
            out = probe_mod.probe_url("https://www.ihrec.ie/", timeout=5.0)
    assert not out.ok and out.soft_forbidden
