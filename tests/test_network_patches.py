"""
Unit tests for app/lib/network_patches.

These guarantee the IPv4-preference wrapper:
  1. Filters AAAA results out of real connection lookups (port given).
  2. PRESERVES every result for SSRF / blocklist resolution checks
     (port=None) — a regression here would let attackers slip past the
     IPv6 portion of the SSRF blocklist in app/briefing/ingestion/
     webpage_scraper.py.
  3. Passes through explicit AF_INET / AF_INET6 requests unfiltered.
  4. Falls open for IPv6-only hostnames (returns IPv6 results rather
     than failing with no addresses).
  5. Is idempotent — calling apply_ipv4_preference() multiple times
     does not double-wrap the function.
"""

import socket

import pytest


@pytest.fixture
def fresh_socket(monkeypatch):
    """Yield a clean socket module state.

    The patch installs itself on ``socket.getaddrinfo`` and sets a flag
    on the socket module.  Tests need a fresh slate so they can install
    the patch over a known stub.
    """
    fake_results = []

    def _fake_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        return list(fake_results)

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo)
    monkeypatch.setattr(socket, "_societyspeaks_ipv4_patch_applied", False, raising=False)

    yield fake_results


def test_filters_to_ipv4_when_port_given(fresh_socket):
    fresh_socket[:] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 5432, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.1", 5432)),
    ]

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    results = socket.getaddrinfo("example.com", 5432)
    assert len(results) == 1
    assert results[0][0] == socket.AF_INET
    assert results[0][4][0] == "203.0.113.1"


def test_preserves_all_addresses_when_port_is_none(fresh_socket):
    """SSRF blocklists pass port=None to inspect every resolved address.

    Filtering IPv6 here would let a host with public IPv4 + private
    IPv6 pass the blocklist check — a real security regression.
    """
    fresh_socket[:] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
    ]

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    results = socket.getaddrinfo("example.com", None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    families = sorted(r[0] for r in results)
    assert socket.AF_INET in families
    assert socket.AF_INET6 in families


def test_passes_through_explicit_af_inet6(fresh_socket):
    fresh_socket[:] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 80, 0, 0)),
    ]

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    results = socket.getaddrinfo("example.com", 80, socket.AF_INET6)
    assert results[0][0] == socket.AF_INET6


def test_passes_through_explicit_af_inet(fresh_socket):
    fresh_socket[:] = [
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.1", 80)),
    ]

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    results = socket.getaddrinfo("example.com", 80, socket.AF_INET)
    assert results[0][0] == socket.AF_INET


def test_falls_open_when_only_ipv6_results(fresh_socket):
    """IPv6-only services must keep working — return IPv6 unfiltered."""
    fresh_socket[:] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 443, 0, 0)),
    ]

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    results = socket.getaddrinfo("ipv6-only.example", 443)
    assert len(results) == 1
    assert results[0][0] == socket.AF_INET6


def test_apply_is_idempotent(fresh_socket):
    """Calling twice must not double-wrap or change behaviour."""
    fresh_socket[:] = [
        (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("2001:db8::1", 5432, 0, 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.1", 5432)),
    ]

    from app.lib.network_patches import apply_ipv4_preference, is_applied

    first = apply_ipv4_preference()
    second = apply_ipv4_preference()
    third = apply_ipv4_preference()

    assert first is True
    assert second is False
    assert third is False
    assert is_applied() is True

    # Behaviour unchanged after the no-op re-applies.
    results = socket.getaddrinfo("example.com", 5432)
    assert len(results) == 1
    assert results[0][0] == socket.AF_INET


def test_does_not_filter_when_results_empty(fresh_socket):
    """An empty result set must not raise — the underlying call would
    have raised socket.gaierror if resolution failed; an empty list is
    just passed through.
    """
    fresh_socket[:] = []

    from app.lib.network_patches import apply_ipv4_preference
    apply_ipv4_preference()

    assert socket.getaddrinfo("example.com", 80) == []
