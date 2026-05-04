# Gevent monkey-patching must happen before any other import so that the
# standard library's socket, threading, and ssl modules are replaced with
# gevent-cooperative equivalents before Flask/SQLAlchemy/Redis import them.
from gevent import monkey  # noqa: E402
monkey.patch_all()

# Patch psycopg2's libpq wait mechanism so DB I/O yields to gevent's event
# loop instead of blocking the whole worker process.
from psycogreen.gevent import patch_psycopg  # noqa: E402
patch_psycopg()

# ---------------------------------------------------------------------------
# IPv4-preference patch
#
# Replit's deployment environment does not have outbound IPv6 connectivity
# (confirmed: socket.connect to 2001:4860:4860::8888 returns ENETUNREACH).
# Several external services (Neon PostgreSQL, Redis Cloud) now return both
# AAAA (IPv6) and A (IPv4) records in their DNS responses.  Without this
# patch, Python's socket layer may try an IPv6 address first, fail with
# "Network is unreachable", and surface an error to Sentry before falling
# back to IPv4 — or not fall back at all depending on the client library.
#
# This wrapper must be applied AFTER gevent's monkey.patch_all() so that
# we wrap the already-patched gevent socket, not the stdlib original.
# ---------------------------------------------------------------------------
import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _prefer_ipv4(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
    results = _orig_getaddrinfo(host, port, family, type, proto, flags)
    if family == 0:  # only filter when caller did not specify address family
        ipv4 = [r for r in results if r[0] == _socket.AF_INET]
        if ipv4:
            return ipv4
    return results


_socket.getaddrinfo = _prefer_ipv4

# ---------------------------------------------------------------------------
# Cert-file reliability: copy the CA bundle to /tmp (a RAM-backed tmpfs)
# before any network library is initialised.
#
# In Replit's production container, Python packages live on an overlay
# filesystem that can intermittently return EIO (errno 5) when a file is
# read.  Every outgoing TLS connection reads a CA bundle from that path
# (certifi for requests/httpx, stripe's own bundle for the Stripe SDK).
# Copying both to /tmp once at worker startup means all SSL context
# creation for the lifetime of this process reads from RAM, never the
# overlay-fs.
#
# REQUESTS_CA_BUNDLE  – picked up by the requests library on every request
# SSL_CERT_FILE       – picked up by httpx (openai/anthropic SDK) at Client()
#                       instantiation time
# ---------------------------------------------------------------------------
import os as _os
import shutil as _shutil

try:
    import certifi as _certifi
    _certifi_src = _certifi.where()
    _certifi_dst = '/tmp/ca-bundle.crt'
    if not _os.path.exists(_certifi_dst):
        _shutil.copy2(_certifi_src, _certifi_dst)
    _os.environ.setdefault('REQUESTS_CA_BUNDLE', _certifi_dst)
    _os.environ.setdefault('SSL_CERT_FILE', _certifi_dst)
except Exception:
    # Best-effort: if this fails the libraries fall back to their own cert
    # paths and the Stripe-specific /tmp fix in billing/service.py still
    # covers the critical payment path.
    pass

from app import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
