"""Tests for coarse User-Agent device classification."""

from app.lib.device_class import classify_user_agent


def test_classify_mobile_safari():
    ua = (
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
        'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
    )
    assert classify_user_agent(ua) == 'mobile'


def test_classify_desktop_chrome():
    ua = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    assert classify_user_agent(ua) == 'desktop'


def test_classify_bot_python_requests():
    assert classify_user_agent('python-requests/2.32.4') == 'bot'


def test_classify_unknown_empty():
    assert classify_user_agent('') == 'unknown'
    assert classify_user_agent(None) == 'unknown'
