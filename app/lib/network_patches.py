"""
Network-level patches that must be applied at process start, before any
library opens a TCP socket.

This module is the SINGLE SOURCE OF TRUTH for these patches.  Every entry
point that creates a Flask application or otherwise opens network
connections (gunicorn web, scheduler, consensus worker, maintenance
scripts) must call ``apply_ipv4_preference()`` exactly once at the top of
the process — see the call sites referenced below.

Why this exists
---------------
Replit's deployment environment has no outbound IPv6 connectivity
(``socket.connect`` to any 2000::/3 address returns ENETUNREACH).  Several
managed services that this app depends on (Neon PostgreSQL, Redis Cloud)
publish both ``A`` (IPv4) and ``AAAA`` (IPv6) DNS records.  Without this
patch, Python's socket layer may try an IPv6 address first, fail with
"Network is unreachable", and surface the error to Sentry — or, depending
on the client library, never fall back to IPv4 at all.

Design constraints
------------------
* Idempotent.  Safe to call multiple times — re-running ``apply_*`` is a
  no-op once the wrapper is installed.
* Order-sensitive.  When used together with ``gevent.monkey.patch_all()``
  the gevent patch MUST run first.  This module wraps whatever
  ``socket.getaddrinfo`` is currently bound, so wrapping the gevent-
  cooperative version preserves greenlet-safe DNS resolution.
* SSRF-safe.  The wrapper preserves the full address set (both families)
  for resolution checks that pass ``port=None``, so SSRF blocklists
  defined in IPv4 + IPv6 ranges still see every resolved address before
  any connection is attempted.
* Family-respecting.  Explicit ``AF_INET`` / ``AF_INET6`` requests pass
  through unfiltered.
* Fail-open for IPv6-only hosts.  If a hostname resolves to AAAA records
  only, the wrapper still returns them rather than failing.

Entry points that call this
---------------------------
* ``run.py``                            — gunicorn web (after gevent patch)
* ``scripts/run_scheduler.py``          — scheduler process
* ``scripts/run_consensus_worker.py``   — consensus worker pool
* maintenance scripts under ``scripts/`` that call ``create_app()``
"""

from __future__ import annotations

import logging
import socket
import threading

logger = logging.getLogger(__name__)

_PATCH_FLAG = "_societyspeaks_ipv4_patch_applied"
_lock = threading.Lock()


def apply_ipv4_preference() -> bool:
    """Install an IPv4-preference wrapper around ``socket.getaddrinfo``.

    Returns ``True`` if the patch was installed by this call, ``False``
    if it was already in place (idempotent — every call site is allowed
    to defensively call this without coordination).
    """
    with _lock:
        if getattr(socket, _PATCH_FLAG, False):
            return False

        original_getaddrinfo = socket.getaddrinfo

        def _prefer_ipv4(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
            results = original_getaddrinfo(host, port, family, type, proto, flags)
            # Filter to IPv4-only when:
            #   - The caller did not pin a specific family (family==0 / AF_UNSPEC).
            #   - A port was supplied — i.e. this is a real connection lookup,
            #     not an SSRF / blocklist resolution check (which deliberately
            #     passes port=None so it can inspect every resolved address).
            #   - At least one IPv4 result exists.  If only IPv6 records came
            #     back we return the unfiltered set rather than failing closed,
            #     so IPv6-only services keep working in environments that
            #     support them.
            if family == 0 and port is not None:
                ipv4 = [r for r in results if r[0] == socket.AF_INET]
                if ipv4:
                    return ipv4
            return results

        socket.getaddrinfo = _prefer_ipv4
        setattr(socket, _PATCH_FLAG, True)
        logger.info("IPv4-preference patch installed on socket.getaddrinfo")
        return True


def is_applied() -> bool:
    """Return True if ``apply_ipv4_preference()`` has been called in this process."""
    return bool(getattr(socket, _PATCH_FLAG, False))
