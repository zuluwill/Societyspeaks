"""Server-side PostHog helpers and process lifecycle.

Architecture (intentional):

- **Never** call ``posthog.flush()`` on the HTTP request path. It blocks on the
  PostHog API and harms TTFB / Core Web Vitals. Capture only; the SDK batches.

- **Gunicorn**: ``preload_app`` is **off** (see gunicorn_config.py — preloading
  monkey-patches the master and breaks worker reaping), so each worker builds
  its own PostHog client at app import and no fork handling is needed.
  :func:`reinitialize_posthog_after_fork` is retained (tested, unwired) in case
  a preload configuration ever returns (PostHog/posthog-python#290).

- **Gevent**: monkey-patched ``queue.Queue`` lacks ``threading.Queue`` private
  APIs (``mutex``, ``not_empty``, ``all_tasks_done``). PostHog >=7.37.6's
  ``_DrainSignal`` uses those and crashes the consumer under gunicorn+gevent
  (Sentry 2026-08-07). :func:`apply_posthog_gevent_compat` rebinds PostHog to
  the unpatched stdlib ``Queue`` and ``Thread`` so consumers run on real OS
  threads and do not block the hub.

- **Never join from the hub**: after the Queue/Thread rebind, ``flush()``,
  ``shutdown()``, ``Client.join``, ``_Lane.join`` / ``_Lane.flush`` /
  ``wait_for_sync_sends``, and ``Poller.stop`` all wait on real ``threading``
  primitives (``queue.join``, ``Condition.wait``, ``Thread.join``). Calling any
  of them from a gunicorn gevent worker (``worker_exit`` / ``atexit``) freezes
  the hub until gunicorn's 120s timeout SIGKILLs the process (Render ``/health``
  connection refused, Aug 2026). ``GeventTimeout`` cannot interrupt those OS
  waits — skipping them is the only reliable control.
  :func:`shutdown_server_posthog` drains every lane by ``qsize()`` with
  cooperative sleep, pauses consumers and the poller, and only ``Thread.join``s
  when gevent is not patching threads.

- **SDK atexit(join)**: ``Client.__init__`` registers ``atexit.register(self.join)``
  with no timeout. Recycle/SIGTERM runs that handler *after* ``worker_exit`` and
  hangs the main greenlet (Sentry PYTHON-FLASK-JD, 2026-08-24). We skip that
  registration, wrap the SDK teardown methods so they no-op under gevent even
  if a bound method was already atexit-registered, and no-op instance
  ``join``/``flush``/``shutdown``. Our drain is the only shutdown path.

- **Drain on shutdown**: ``register_posthog_atexit()`` (from ``create_app``) and
  ``gunicorn`` ``worker_exit`` call ``shutdown_server_posthog()``. Drain every
  lane (analytics + AI); ``client.queue`` is only the analytics lane.

- **Best-effort delivery**: SIGKILL, OOM, or hard crashes can lose buffered events.
  For revenue‑critical attribution, persist facts in your DB first; analytics mirror
  that truth.

- **Frontend analytics** (snippet in ``layout.html``) are separate from this module.
"""
from __future__ import annotations

import atexit
import logging
import uuid
from typing import Any, Optional

_shutdown_done = False
_gevent_compat_applied = False
_log = logging.getLogger(__name__)


def _queue_supports_posthog_drain(queue_cls: Any) -> bool:
    """True when *queue_cls* exposes threading.Queue APIs PostHog drain needs."""
    try:
        sample = queue_cls()
        return hasattr(sample, "mutex") and hasattr(sample, "not_empty")
    except Exception:
        return False


def apply_posthog_gevent_compat() -> bool:
    """Make PostHog's async consumer safe under ``gevent.monkey.patch_all()``.

    PostHog 7.37.6+ (``_DrainSignal``) reaches into ``queue.Queue.mutex`` /
    ``not_empty``. Gevent's patched Queue has neither, so the consumer thread
    dies with ``AttributeError`` and events stop uploading.

    When gevent has patched ``queue``, rebind PostHog to the *original* stdlib
    ``Queue`` and make ``Consumer`` subclass the original ``threading.Thread``
    so the uploader runs on a real OS thread (correct under gevent — do not use
    greenlets for blocking HTTP upload).

    Re-checks even after a prior success so a stale flag cannot leave PostHog
    on a gevent Queue. No-op when gevent is absent or has not patched ``queue``.
    Returns True when PostHog's Queue supports drain APIs afterwards.
    """
    global _gevent_compat_applied
    try:
        from gevent import monkey
    except ImportError:
        return False
    try:
        if not monkey.is_module_patched("queue"):
            return False
        real_queue = monkey.get_original("queue", "Queue")
        real_thread = monkey.get_original("threading", "Thread")
    except Exception as exc:
        _log.warning("PostHog gevent compat: could not resolve originals: %s", exc)
        return False

    try:
        import posthog.client as ph_client
        import posthog.consumer as ph_consumer

        if _queue_supports_posthog_drain(getattr(ph_client, "Queue", None)):
            _gevent_compat_applied = True
            return True

        ph_client.Queue = real_queue
        # Consumer was defined as ``class Consumer(Thread)`` after monkey-patch,
        # so its base is the greenlet Thread. Swap to the real OS Thread.
        # Queue rebind is the critical part; base swap is best-effort.
        try:
            if ph_consumer.Consumer.__bases__ != (real_thread,):
                ph_consumer.Consumer.__bases__ = (real_thread,)
        except Exception as bases_exc:
            _log.warning(
                "PostHog gevent compat: Queue rebound but Thread base swap failed: %s",
                bases_exc,
            )

        ok = _queue_supports_posthog_drain(ph_client.Queue)
        _gevent_compat_applied = ok
        if ok:
            _log.info(
                "PostHog gevent compat applied (stdlib Queue + OS Thread for consumers)"
            )
        else:
            _log.error(
                "PostHog gevent compat: Queue still lacks mutex/not_empty after rebind"
            )
        return ok
    except Exception as exc:
        _log.warning("PostHog gevent compat failed: %s", exc)
        return False


def configure_posthog_credentials(
    api_key: str,
    host: str,
    *,
    debug: bool = False,
) -> None:
    """Set module-level PostHog credentials used by ``capture`` / ``setup``.

    Does not force a client to start; the first capture (or an explicit
    :func:`reinitialize_posthog_after_fork`) creates the default client.
    Applies gevent Queue/Thread rebinding first when needed so ``setup()``
    never builds a consumer on a gevent Queue. If rebinding fails under
    gevent, fall back to ``sync_mode=True`` (no background consumer).
    """
    import posthog as ph

    compat_ok = apply_posthog_gevent_compat()

    # api_key drives setup(); project_api_key is what our call-site guards check.
    ph.api_key = api_key
    ph.project_api_key = api_key
    ph.host = host
    ph.debug = debug

    # Last resort: never start a DrainSignal consumer on a gevent Queue.
    try:
        from gevent import monkey

        if monkey.is_module_patched("queue") and not compat_ok:
            ph.sync_mode = True
            _log.warning(
                "PostHog sync_mode=True under gevent (compat failed; avoids "
                "consumer AttributeError on mutex/not_empty)"
            )
    except ImportError:
        pass

    _patch_atexit_skip_posthog_join()
    _patch_posthog_blocking_teardown_methods()
    _patch_posthog_client_init_for_gevent()
    disarm_posthog_blocking_shutdown()


def reinitialize_posthog_after_fork() -> None:
    """Replace any pre-fork PostHog client with a worker-local one.

    Safe to call when PostHog is not configured (no-op). Currently unwired:
    preload_app is off, so workers never inherit a pre-fork client. Wire this
    into a post-fork hook again only if preload_app is ever re-enabled.
    """
    global _shutdown_done
    try:
        import posthog as ph

        api_key = getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)
        if not api_key:
            return

        apply_posthog_gevent_compat()

        # Drop inherited client/consumers from the master process.
        old = getattr(ph, "default_client", None)
        if old is not None:
            # Do not old.shutdown() — that Thread.join()s and will hang the
            # child hub if preload_app is ever re-enabled under gevent.
            try:
                _pause_posthog_consumers(old)
            except Exception:
                pass
            ph.default_client = None

        _shutdown_done = False
        # setup() builds a fresh Client + consumer threads for this worker.
        if hasattr(ph, "setup"):
            ph.setup()
        disarm_posthog_blocking_shutdown()
        _log.info("PostHog client reinitialized after fork")
    except Exception as exc:
        _log.warning("PostHog post-fork reinitialize failed: %s", exc)


def _gevent_is_patching_threads() -> bool:
    """True when gevent has replaced threading primitives in this process."""
    try:
        from gevent import monkey

        return bool(
            monkey.is_module_patched("threading")
            or monkey.is_module_patched("thread")
            or monkey.is_module_patched("queue")
        )
    except ImportError:
        return False


def _cooperative_sleep(seconds: float) -> None:
    """Sleep without pinning the gevent hub when monkey-patched."""
    if seconds <= 0:
        return
    try:
        from gevent import monkey

        if monkey.is_module_patched("time"):
            import gevent

            gevent.sleep(seconds)
            return
    except ImportError:
        pass
    import time

    time.sleep(seconds)


def _posthog_lanes(client: Any) -> list:
    """PostHog 7.37+ splits capture across analytics + AI lanes."""
    lanes = getattr(client, "_lanes", None)
    if lanes:
        return list(lanes)
    return []


def _posthog_queues(client: Any) -> list:
    """Every lane queue. ``client.queue`` is analytics-only (back-compat)."""
    queues = []
    for lane in _posthog_lanes(client):
        queue = getattr(lane, "queue", None)
        if queue is not None:
            queues.append(queue)
    if queues:
        return queues
    queue = getattr(client, "queue", None)
    return [queue] if queue is not None else []


def _posthog_consumers(client: Any) -> list:
    """Every lane consumer. ``client.consumers`` is None in sync_mode."""
    consumers: list = []
    for lane in _posthog_lanes(client):
        consumers.extend(getattr(lane, "consumers", None) or ())
    if consumers:
        return consumers
    return list(getattr(client, "consumers", None) or ())


def _drain_client_queue(client: Any, timeout: float = 1.0) -> None:
    """Wait for the client's consumer threads to empty the capture queues.

    Never use ``flush()`` here. After :func:`apply_posthog_gevent_compat`
    rebinds PostHog to stdlib ``Queue``, ``flush()`` waits on
    ``all_tasks_done`` — a real ``threading.Condition`` — from the gunicorn
    greenlet, which wedges the hub. Drain every lane; skipping the AI lane
    leaves events that ``Client.shutdown`` would then ``queue.join()`` forever.
    """
    import time

    queues = _posthog_queues(client)
    if not queues:
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if all(queue.qsize() == 0 for queue in queues):
                return
        except Exception:
            return
        _cooperative_sleep(0.05)
    leftover: Any = 0
    try:
        leftover = sum(queue.qsize() for queue in queues)
    except Exception:
        leftover = "?"
    _log.warning(
        "PostHog queue not fully drained at shutdown (%s events left)",
        leftover,
    )


def _pause_posthog_consumers(client: Any) -> None:
    """Ask upload threads to stop without waiting for them.

    ``Consumer.pause()`` is the SDK's cooperative stop. The worker/process is
    about to exit; leftover daemon threads die with it. Do not ``join()``.
    """
    for consumer in _posthog_consumers(client):
        for method_name in ("pause", "stop"):
            method = getattr(consumer, method_name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    pass
                break


def _pause_posthog_poller(client: Any) -> None:
    """Stop the feature-flag poller without ``Thread.join``.

    ``Poller.stop`` sets the event then ``join()``s with no timeout.
    """
    poller = getattr(client, "poller", None)
    if poller is None:
        return
    stopped = getattr(poller, "stopped", None)
    if stopped is not None and callable(getattr(stopped, "set", None)):
        try:
            stopped.set()
        except Exception:
            pass


def _join_posthog_consumers(client: Any, timeout: float = 1.0) -> None:
    """Bounded ``Thread.join`` — only safe when gevent is not patching threads."""
    import time

    consumers = _posthog_consumers(client)
    if not consumers:
        return
    deadline = time.monotonic() + timeout
    per = max(0.05, timeout / max(len(consumers), 1))
    for consumer in consumers:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        join = getattr(consumer, "join", None)
        if not callable(join):
            continue
        try:
            join(min(per, remaining))
        except Exception:
            pass


_POSTHOG_TEARDOWN_NAMES = frozenset({"join", "shutdown", "flush", "stop"})


def _is_posthog_sdk_join(func: Any) -> bool:
    """True for SDK teardown bound methods the SDK atexit-registers.

    ``Client.join`` is the production path (PYTHON-FLASK-JD). Celery
    integration registers ``shutdown``. ``flush`` / ``Poller.stop`` are
    included so a future SDK atexit cannot bypass the skip.
    """
    if getattr(func, "__name__", None) not in _POSTHOG_TEARDOWN_NAMES:
        return False
    inst = getattr(func, "__self__", None)
    if inst is None:
        return False
    mod = getattr(type(inst), "__module__", "") or ""
    return mod.startswith("posthog")


def _uninstall_posthog_sdk_atexit(client: Any = None) -> None:
    """Best-effort drop of ``atexit.register(self.join)``.

    CPython's ``atexit.unregister`` does not match a later bound-method object
    even when ``==`` is true, so this often no-ops. The reliable control is
    :func:`_patch_atexit_skip_posthog_join` (never register). Keep this for
    the rare case unregister does match.
    """
    import posthog as ph

    seen: set[int] = set()
    for candidate in (client, getattr(ph, "default_client", None)):
        if candidate is None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        join = getattr(candidate, "join", None)
        if callable(join):
            try:
                atexit.unregister(join)
            except Exception:
                pass
        for name in ("shutdown", "flush"):
            method = getattr(candidate, name, None)
            if callable(method):
                try:
                    atexit.unregister(method)
                except Exception:
                    pass


_ATEXIT_PATCHED = False
_TEARDOWN_METHODS_PATCHED = False


def _patch_atexit_skip_posthog_join() -> None:
    """Do not let PostHog teardown methods onto the atexit list.

    ``Client.__init__`` does ``atexit.register(self.join)`` with no timeout.
    Recycle then hangs in ``lane.join()`` (PYTHON-FLASK-JD). Skip that
    registration; :func:`shutdown_server_posthog` is the drain path.
    """
    global _ATEXIT_PATCHED
    if _ATEXIT_PATCHED:
        return
    orig = atexit.register
    if getattr(orig, "_ss_skip_posthog_join", False):
        _ATEXIT_PATCHED = True
        return

    def register(func, *args, **kwargs):
        if _is_posthog_sdk_join(func):
            return func
        return orig(func, *args, **kwargs)

    register._ss_skip_posthog_join = True  # type: ignore[attr-defined]
    atexit.register = register
    _ATEXIT_PATCHED = True


def _wrap_noop_under_gevent(cls: Any, name: str) -> None:
    """Replace *cls.name* so gevent-patched processes never enter the original."""
    orig = getattr(cls, name, None)
    if orig is None or getattr(orig, "_ss_gevent_noop", False):
        return

    def wrapped(self, *args, **kwargs):
        if _gevent_is_patching_threads():
            return None
        return orig(self, *args, **kwargs)

    wrapped._ss_gevent_noop = True  # type: ignore[attr-defined]
    wrapped._ss_orig = orig  # type: ignore[attr-defined]
    wrapped.__name__ = getattr(orig, "__name__", name)
    wrapped.__doc__ = getattr(orig, "__doc__", None)
    setattr(cls, name, wrapped)


def _patch_posthog_blocking_teardown_methods() -> None:
    """No-op SDK teardown that joins OS threads when gevent owns threading.

    Instance assignment of ``client.join`` does not rewrite a bound method
    already sitting on the atexit list. Wrapping the class methods means
    even that leftover bound call short-circuits under gevent. ``flush`` /
    ``shutdown`` / lane waits / ``Poller.stop`` are the leftover PYTHON-FLASK-JD
    siblings: any one of them wedges the hub the same way.
    """
    global _TEARDOWN_METHODS_PATCHED
    if _TEARDOWN_METHODS_PATCHED:
        return
    try:
        import posthog.client as ph_client
    except Exception:
        return

    for name in ("join", "flush", "shutdown"):
        _wrap_noop_under_gevent(ph_client.Client, name)
    lane = getattr(ph_client, "_Lane", None)
    if lane is not None:
        for name in ("join", "flush", "wait_for_sync_sends"):
            _wrap_noop_under_gevent(lane, name)

    try:
        import posthog.poller as ph_poller
    except Exception:
        ph_poller = None
    if ph_poller is not None:
        orig_stop = getattr(ph_poller.Poller, "stop", None)
        if orig_stop is not None and not getattr(orig_stop, "_ss_gevent_noop", False):

            def stop(self):
                if _gevent_is_patching_threads():
                    stopped = getattr(self, "stopped", None)
                    if stopped is not None and callable(getattr(stopped, "set", None)):
                        try:
                            stopped.set()
                        except Exception:
                            pass
                    return None
                return orig_stop(self)

            stop._ss_gevent_noop = True  # type: ignore[attr-defined]
            stop._ss_orig = orig_stop  # type: ignore[attr-defined]
            ph_poller.Poller.stop = stop

    _TEARDOWN_METHODS_PATCHED = True


def _neuter_blocking_teardown_under_gevent(client: Any) -> None:
    """Make ``join`` / ``flush`` / ``shutdown`` no-ops on this instance.

    Defense in depth if anything still calls those APIs after we skip atexit.
    Class-level wraps in :func:`_patch_posthog_blocking_teardown_methods` are
    the path that covers already-registered bound methods.
    """
    if client is None or not _gevent_is_patching_threads():
        return
    if getattr(client, "_ss_join_neutered", False):
        return

    def _no_teardown(*_a, **_k):
        return None

    try:
        client.join = _no_teardown
        client.flush = _no_teardown
        client.shutdown = _no_teardown
        client._ss_join_neutered = True
    except Exception:
        pass
    for lane in _posthog_lanes(client):
        try:
            lane.join = _no_teardown
            lane.flush = _no_teardown
            lane.wait_for_sync_sends = _no_teardown
        except Exception:
            pass


def _neuter_client_join_under_gevent(client: Any) -> None:
    """Back-compat alias used by tests and older call sites."""
    _neuter_blocking_teardown_under_gevent(client)


def disarm_posthog_blocking_shutdown() -> None:
    """Skip SDK atexit teardown and no-op join/flush/shutdown under gevent.

    Safe to call before the default client exists (no-op) and again from
    gunicorn ``worker_exit`` immediately before our drain. Re-applies the
    class wraps so a worker whose ``create_app`` order skipped them is still
    covered.
    """
    _patch_atexit_skip_posthog_join()
    _patch_posthog_blocking_teardown_methods()
    try:
        import posthog as ph
    except Exception:
        return
    client = getattr(ph, "default_client", None)
    _uninstall_posthog_sdk_atexit(client)
    _neuter_blocking_teardown_under_gevent(client)


_CLIENT_INIT_PATCHED = False


def _patch_posthog_client_init_for_gevent() -> None:
    """Wrap ``Client.__init__`` so every new client drops the atexit join."""
    global _CLIENT_INIT_PATCHED
    if _CLIENT_INIT_PATCHED:
        return
    try:
        import posthog.client as ph_client
    except Exception:
        return
    orig = ph_client.Client.__init__
    if getattr(orig, "_ss_gevent_atexit_patched", False):
        _CLIENT_INIT_PATCHED = True
        return

    def wrapped(self, *args, **kwargs):
        orig(self, *args, **kwargs)
        try:
            _uninstall_posthog_sdk_atexit(self)
            _neuter_blocking_teardown_under_gevent(self)
        except Exception:
            pass

    wrapped._ss_gevent_atexit_patched = True  # type: ignore[attr-defined]
    ph_client.Client.__init__ = wrapped
    _CLIENT_INIT_PATCHED = True


def shutdown_server_posthog() -> None:
    """Drain captured events and stop consumers without blocking the caller.

    Safe to call multiple times (e.g. gunicorn ``worker_exit`` + interpreter
    ``atexit``). No-ops when the SDK was not configured.

    Must never call ``posthog.flush()`` or ``posthog.shutdown()``: both join
    OS threads / condition variables. Under gunicorn+gevent that join is
    issued from the hub and becomes a 120s WORKER TIMEOUT (production 2026-08).
    """
    global _shutdown_done
    disarm_posthog_blocking_shutdown()
    if _shutdown_done:
        return
    try:
        import posthog as ph

        if not (
            getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)
        ):
            return
        _shutdown_done = True
        client = getattr(ph, "default_client", None)
        if client is None:
            return
        _drain_client_queue(client)
        _pause_posthog_consumers(client)
        _pause_posthog_poller(client)
        if not _gevent_is_patching_threads():
            _join_posthog_consumers(client)
    except Exception:
        _shutdown_done = True


def register_posthog_atexit(registrar=None) -> None:
    """Register :func:`shutdown_server_posthog` for normal interpreter exit.

    Tests may pass a ``registrar`` callable (signature matching ``atexit.register``).
    """
    _reg = registrar if registrar is not None else atexit.register
    _reg(shutdown_server_posthog)


def _get_request_user_agent() -> Optional[str]:
    """Return the current request's user-agent string, or None outside request context."""
    try:
        from flask import request
        return request.headers.get("User-Agent")
    except Exception:
        return None


def posthog_js_distinct_id() -> Optional[str]:
    """Return the PostHog JS SDK's ``distinct_id`` for the current request.

    The browser SDK persists its identity in a cookie named
    ``ph_<POSTHOG_API_KEY>_posthog`` whose value is a (URL-encoded) JSON blob.
    Reusing that ``distinct_id`` as the server-side ``distinct_id`` is what
    stitches server events to the same person PostHog already tracks for
    pageviews — no ``$identify``/``alias`` round-trip required (same id == same
    person). Returns ``None`` outside a request, when analytics is unconfigured,
    or when the cookie is absent (first visit / cleared) so callers can fall
    back to a stable server-side identity (e.g. a fingerprint).
    """
    try:
        import json
        from urllib.parse import unquote

        from flask import current_app, request

        api_key = current_app.config.get("POSTHOG_API_KEY")
        if not api_key:
            return None
        raw = request.cookies.get(f"ph_{api_key}_posthog")
        if not raw:
            return None
        data = json.loads(unquote(raw))
        distinct_id = data.get("distinct_id")
        if isinstance(distinct_id, str) and distinct_id.strip():
            return distinct_id.strip()
        return None
    except Exception:
        return None


def request_is_scripted_client() -> bool:
    """True when the current request's User-Agent is a known scripted client.

    Reuses the aggressive session-policy list (python-requests, curl, headless
    browsers, declared bots). Returns False outside a request context or when
    no User-Agent is present, so cron/scheduler captures are unaffected.
    """
    try:
        from app.lib.session_policy import (
            SESSION_SKIP_UA_INDICATORS,
            user_agent_is_bot,
        )

        ua = _get_request_user_agent()
        if not ua:
            return False
        return user_agent_is_bot(ua, SESSION_SKIP_UA_INDICATORS)
    except Exception:
        return False


def request_is_prefetch() -> bool:
    """True when the current request is a link prefetch / preview, not a human view.

    Detects the standard, explicit signals email clients and browsers send when
    they fetch a link *before* a human opens it — mail scanners, Apple Mail /
    Safari link previews, Chrome/Firefox prefetch:

    - ``Sec-Purpose: prefetch`` / ``prerender`` (Fetch Metadata standard)
    - ``Purpose: prefetch``
    - ``X-Purpose: prefetch`` / ``preview``
    - ``X-Moz: prefetch``

    High precision by design: a human clicking the link sends none of these, so
    gating the GET-fired ``email_vote_confirm_viewed`` on this never drops a real
    view. Unlike a User-Agent or cookie heuristic it won't skip a first-time
    human, so the confirm-viewed step stays symmetric with the (ungated) POST
    ``email_vote_confirmed`` and the funnel cannot go negative. Returns False
    outside a request context.
    """
    try:
        from flask import request

        headers = request.headers
        sec_purpose = (headers.get('Sec-Purpose') or '').lower()
        if 'prefetch' in sec_purpose or 'prerender' in sec_purpose:
            return True
        if (headers.get('Purpose') or '').strip().lower() == 'prefetch':
            return True
        if (headers.get('X-Purpose') or '').strip().lower() in ('prefetch', 'preview'):
            return True
        if (headers.get('X-Moz') or '').strip().lower() == 'prefetch':
            return True
        return False
    except Exception:
        # Outside a request context (cron/scheduler) there is no prefetch signal.
        return False


def request_has_browser_evidence() -> bool:
    """True when the current request demonstrably comes from a JS-executing browser.

    The only reliable crawler signal at our traffic mix is cookie carriage:
    most crawlers present ordinary browser User-Agents but never execute the
    PostHog JS snippet, so they never send the ``ph_<key>_posthog`` cookie
    (measured 2026-07: 6,952 of 6,962 ``journey_started`` distinct_ids had no
    client-side event, ~99.9% crawler share). Use this to gate any server-side
    capture that fires on a bare GET; action-gated events (votes, POSTs) do
    not need it. Trade-off: a human's very first page render is skipped too —
    they are captured on any subsequent navigation once the cookie exists.
    """
    if request_is_scripted_client():
        return False
    return posthog_js_distinct_id() is not None


def resolve_request_distinct_id(
    user_id: Any = None,
    anon_fallback: Optional[str] = None,
) -> Optional[str]:
    """Canonical server-side ``distinct_id`` for an event fired during a request.

    The single source of truth for identity so server events stitch to the JS
    SDK's person (and to each other):

    - **Logged-in** → ``str(user_id)``, matching the JS SDK's ``identify('<id>')``.
    - **Anonymous** → the browser's PostHog cookie ``distinct_id`` when present
      (so server events join the same person as JS pageviews), else the supplied
      durable ``anon_fallback`` (e.g. a vote fingerprint or session id) so the
      event still attributes to a stable identity rather than fragmenting.

    Returns ``None`` only when anonymous with no cookie and no fallback, letting
    callers skip the capture rather than invent an id.
    """
    if user_id:
        return str(user_id)
    js_id = posthog_js_distinct_id()
    if js_id:
        return js_id
    if anon_fallback:
        return str(anon_fallback)
    return None


# Path/route argument names that carry secrets (magic-link / unsubscribe /
# preferences tokens, signatures, one-time codes). Their values must never reach
# analytics, so we redact them out of any URL we attach to events.
_SENSITIVE_URL_ARG_HINTS = (
    "token",
    "secret",
    "signature",
    "sig",
    "key",
    "code",
    "otp",
    "password",
    "passwd",
    "auth",
)


def _is_sensitive_arg(name: str) -> bool:
    lowered = (name or "").lower()
    return any(hint in lowered for hint in _SENSITIVE_URL_ARG_HINTS)


def _redact_path(path: str, view_args: Optional[dict]) -> str:
    """Replace secret path segments (e.g. ``/daily/unsubscribe/<token>``) with a
    placeholder, using the matched route args so only genuine secrets are masked
    (ids, dates, slugs, uuids are preserved for analytics)."""
    redacted = path or ""
    for key, value in (view_args or {}).items():
        if value is None:
            continue
        if _is_sensitive_arg(key):
            redacted = redacted.replace(str(value), f"<{key}>")
    return redacted


def email_subscriber_distinct_id(email: Optional[str]) -> Optional[str]:
    """Stable, pseudonymous ``distinct_id`` for an email-only (no account) person.

    Email subscribers have no user id and (for cron-sent digests) no browser
    cookie, so their email is the only stable identifier tying together
    subscribe -> digest_sent -> one-click vote -> unsubscribe. We hash it so raw
    PII never becomes a PostHog distinct_id (which surfaces in exports/URLs),
    while staying identical across every one of that subscriber's events.

    Must be used for *all* email-keyed events so they share one identity. Returns
    ``None`` for a falsy email.
    """
    if not email:
        return None
    import hashlib

    normalized = str(email).strip().lower()
    return "subscriber:" + hashlib.sha256(normalized.encode()).hexdigest()[:32]


def request_context_properties() -> dict:
    """Browser-context event properties derived from the current Flask request.

    Server-side SDK captures carry none of the page context the JS SDK attaches
    automatically, which is why discovery/attribution questions are unanswerable
    from server events alone. We decompose the URL ourselves rather than relying
    on PostHog to parse ``$current_url``: UTM extraction is unreliable for custom
    (non-``$pageview``) server events. Returns ``{}`` outside a request context.

    Privacy: many server events fire on token-bearing routes (magic-link login,
    one-click unsubscribe, preferences). We therefore (a) drop the query string
    from the emitted URLs so ``?token=`` style secrets never leak — campaign data
    is preserved via the explicit ``$utm_*`` keys — and (b) redact secret path
    segments via the matched route args. First-touch attribution (``$initial_*``)
    lives on the person profile via the JS SDK and cannot be reconstructed here.
    """
    try:
        from urllib.parse import parse_qs, urlparse, urlunparse

        from flask import request

        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        view_args = getattr(request, "view_args", None) or {}

        safe_path = _redact_path(parsed.path, view_args)
        # Rebuild without query/fragment so no secret query params survive.
        safe_url = urlunparse((parsed.scheme, parsed.netloc, safe_path, "", "", ""))
        props: dict = {
            "$current_url": safe_url,
            "$host": parsed.netloc,
            "$pathname": safe_path,
        }
        referrer = request.referrer
        if referrer:
            ref = urlparse(referrer)
            # Strip the referrer's query string too; keep domain + path for funnels.
            props["$referrer"] = urlunparse((ref.scheme, ref.netloc, ref.path, "", "", ""))
            props["$referring_domain"] = ref.netloc
        for param in (
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
        ):
            value = query.get(param, [None])[0]
            if value:
                props[f"${param}"] = value
        return props
    except Exception:
        return {}


def stitch_email_subscriber_posthog_identity(
    subscriber_email: Optional[str],
) -> Optional[str]:
    """Merge a browser PostHog person into the email-subscriber canonical id.

    Email vote funnels must attribute to ``subscriber:<hash>`` so confirm-viewed
    and confirmed events stitch across sessions and devices. When the visitor
    already has a JS cookie distinct_id, alias it into the subscriber hash before
    capture so server events join the same person as prior pageviews.
    """
    canonical = email_subscriber_distinct_id(subscriber_email)
    if not canonical:
        return None
    js_id = posthog_js_distinct_id()
    if js_id and js_id != canonical:
        try:
            import posthog as ph

            # Match safe_posthog_capture's readiness check so alias and capture
            # agree on whether PostHog is configured.
            if not getattr(ph, "project_api_key", None):
                return canonical
            ph.alias(previous_id=js_id, distinct_id=canonical)
        except Exception as exc:
            _log.warning(
                "PostHog alias %s -> %s failed: %s",
                js_id,
                canonical,
                exc,
            )
    return canonical


def stitch_posthog_on_user_login(
    user: Any,
    *,
    subscriber_email: Optional[str] = None,
    event: str = "user_logged_in",
    properties: Optional[dict] = None,
    identify_properties: Optional[dict] = None,
) -> None:
    """Merge anonymous/subscriber PostHog persons into an authenticated user.

    Call immediately after ``login_user`` on magic-link paths so email-acquired
    anonymous events (``subscriber:<hash>``, JS cookie UUID) stitch to
    ``str(user.id)`` — matching the frontend ``identify('<id>')`` in
    ``layout.html``.
    """
    if user is None or not getattr(user, "id", None):
        return
    try:
        import posthog as ph

        if not (getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)):
            return

        canonical = str(user.id)
        prior: list[str] = []
        js_id = posthog_js_distinct_id()
        if js_id and js_id != canonical:
            prior.append(js_id)
        sub_hash = email_subscriber_distinct_id(subscriber_email)
        if sub_hash and sub_hash != canonical and sub_hash not in prior:
            prior.append(sub_hash)

        for previous_id in prior:
            try:
                ph.alias(previous_id=previous_id, distinct_id=canonical)
            except Exception as exc:
                _log.warning(
                    "PostHog alias %s -> %s failed: %s",
                    previous_id,
                    canonical,
                    exc,
                )

        id_props = identify_properties or {
            "email": getattr(user, "email", None),
            "username": getattr(user, "username", None),
        }
        safe_posthog_capture(
            posthog_client=ph,
            distinct_id=canonical,
            event=event,
            properties=properties or {},
            identify_properties={k: v for k, v in id_props.items() if v},
        )
    except Exception as exc:
        _log.warning(
            "PostHog login stitch failed for user %s: %s",
            getattr(user, "id", None),
            exc,
        )


def _drain_posthog_client(posthog_client: Any, *, timeout: float = 0.25) -> None:
    """Best-effort bounded drain after revenue-critical captures."""
    try:
        client = getattr(posthog_client, 'default_client', None)
        if client is None:
            import posthog as ph

            client = getattr(ph, 'default_client', None)
        if client is not None:
            _drain_client_queue(client, timeout=timeout)
    except Exception as exc:
        _log.warning('PostHog queue drain failed: %s', exc)


def event_uuid_from_insert_id(insert_id: str) -> str:
    """Deterministic UUIDv5 for PostHog ``capture(uuid=...)``.

    posthog-python 7.x requires a valid UUID here; any other string is
    discarded and replaced with a random id, so ``$insert_id`` in properties
    does not deduplicate.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'https://societyspeaks.io/ph/{insert_id}'))


def _merge_person_set_properties(props: dict, identify_properties: dict) -> None:
    """Attach person properties as ``$set`` on the capture payload.

    posthog-python 6+ deprecated ``identify()`` (removed on the 7.x module
    and Client). Backend person updates go on the event as ``$set`` —
    https://posthog.com/docs/product-analytics/identify and
    https://posthog.com/docs/product-analytics/person-properties. A separate
    ``set()`` / ``$identify`` call would enqueue a second event for the same
    write. Merge into any ``$set`` already on the event so explicit keys win.
    """
    existing = props.get("$set")
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(identify_properties)
    props["$set"] = merged


def safe_posthog_capture(
    *,
    posthog_client: Any,
    distinct_id: str,
    event: str,
    properties: Optional[dict] = None,
    identify_properties: Optional[dict] = None,
    insert_id: Optional[str] = None,
    durable: bool = False,
) -> bool:
    """Capture (and optionally identify) in PostHog, never raising into callers.

    Automatically attaches ``$raw_user_agent`` to every server-side event so
    that PostHog's "Filter Bot Events" Data Pipeline transformation can drop
    crawler traffic without any changes to individual call sites.

    When fired inside a request, also attaches browser context (``$current_url``,
    ``$referrer``/``$referring_domain``, ``$utm_*``) so server-side events are
    attributable to discovery channels. Explicit ``properties`` always win over
    the auto-derived values. Outside a request context these are simply omitted.

    ``insert_id`` is attached as ``$insert_id`` (queryable) and as a
    deterministic UUIDv5 passed to ``capture(uuid=...)``. posthog-python 7.x
    only deduplicates on that ``uuid`` argument; a non-UUID ``$insert_id``
    property is ignored and replaced with a random event id (the stance
    reconciler previously multiplied ``email_vote_confirmed`` ~672× per vote).
    ``identify_properties`` become ``properties['$set']`` on the same
    capture. That is the supported backend path after ``identify()`` was
    removed; do not send a follow-up ``set()`` / ``$identify`` for the
    same write.

    ``durable=True`` performs a bounded queue drain after capture — use only for
    conversion-critical events where batch loss on fast POST handlers would
    otherwise under-count. Never call ``flush()`` on the HTTP path.
    """
    if not posthog_client or not getattr(posthog_client, "project_api_key", None):
        return False
    # Never invent a 'None'/empty person when identity could not be resolved.
    if not distinct_id:
        _log.warning("Skipping PostHog event %s — no distinct_id", event)
        return False
    # Scripted clients (python-requests, curl, declared bots) are never worth
    # capturing; UA-based filtering downstream cannot recover once they are in.
    # Browser-UA crawlers are NOT caught here — page-load-triggered call sites
    # must additionally gate on request_has_browser_evidence().
    if request_is_scripted_client():
        return False

    try:
        props = dict(properties or {})
        capture_kwargs = {
            'distinct_id': str(distinct_id),
            'event': event,
            'properties': props,
        }
        if insert_id:
            props['$insert_id'] = insert_id
            capture_kwargs['uuid'] = event_uuid_from_insert_id(insert_id)
        if "$raw_user_agent" not in props:
            ua = _get_request_user_agent()
            if ua:
                props["$raw_user_agent"] = ua
        for key, value in request_context_properties().items():
            props.setdefault(key, value)
        if identify_properties:
            _merge_person_set_properties(props, identify_properties)

        posthog_client.capture(**capture_kwargs)
        if durable:
            _drain_posthog_client(posthog_client)
        return True
    except Exception as exc:
        # Analytics must never break product flows, but failures must be visible.
        _log.warning("PostHog capture failed for event %s: %s", event, exc)
        return False


def safe_system_capture(
    event: str,
    properties: Optional[dict] = None,
    *,
    insert_id: Optional[str] = None,
    durable: bool = True,
) -> None:
    """Capture a PostHog event for automated background/scheduler jobs.

    Uses ``distinct_id='system'`` because these events have no user identity
    and no HTTP request context. Unlike ``safe_posthog_capture``, this function
    intentionally omits request-context enrichment (``$current_url``, UTM tags)
    since there is no request. Always a no-op when PostHog is not configured.

    Pass ``insert_id`` so scheduler retries do not create duplicate events
    (posthog-python 7.x dedupes on ``uuid=``, not a property ``$insert_id``).
    """
    try:
        import posthog as ph

        if not (getattr(ph, "api_key", None) or getattr(ph, "project_api_key", None)):
            return
        props = dict(properties or {})
        capture_kwargs = {
            'distinct_id': 'system',
            'event': event,
            'properties': props,
        }
        if insert_id:
            props['$insert_id'] = insert_id
            capture_kwargs['uuid'] = event_uuid_from_insert_id(insert_id)
        ph.capture(**capture_kwargs)
        if durable:
            _drain_posthog_client(ph)
    except Exception as exc:
        _log.warning("PostHog system capture failed for event %s: %s", event, exc)
