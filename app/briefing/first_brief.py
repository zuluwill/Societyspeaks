"""
Synchronous first-brief generation for self-serve trial signups.

The trial flow promises a "first brief in minutes" experience. To deliver
that we kick off a real :class:`BriefRun` generation in a worker thread the
moment the trial is created and wait up to ``deadline_seconds`` for it to
finish. If the worker is still running when the deadline expires we leave it
alone — it will commit a ``BriefRun`` row eventually and the scheduler picks
up the work — and the HTTP response renders a graceful "your first brief is
being built" fallback page.

Threading discipline (per docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md):

- The Flask **app object** is captured before the thread starts so the worker
  can establish its own :func:`app_context`. ``current_app`` is request-bound
  and not available in worker threads.
- :data:`db.session` is a thread-local scoped session (Flask-SQLAlchemy), so
  the worker gets its **own** session — it does not share the request thread's
  identity map. Pass *ids*, not ORM instances, across the thread boundary.
- The worker commits and calls ``db.session.remove()`` so the session is
  cleaned up regardless of outcome. Failing to do this leaks DB connections
  under load.
- :class:`concurrent.futures.ThreadPoolExecutor` is shut down with
  ``wait=False`` after :meth:`Future.result` returns or raises
  :class:`TimeoutError`, so the worker keeps running on timeout.

The function is a single entry point; the route layer doesn't need to know
any of the above — it just calls :func:`generate_first_brief_sync` and
inspects the returned :class:`FirstBriefResult`.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from flask import Flask, current_app


logger = logging.getLogger(__name__)


FirstBriefStatus = Literal['ready', 'pending', 'failed']


@dataclass
class FirstBriefResult:
    """Outcome of :func:`generate_first_brief_sync`.

    Attributes:
        status:        ``'ready'`` if a BriefRun was committed within the
                       deadline, ``'pending'`` if the worker is still running
                       (route should render the fallback page), ``'failed'``
                       if generation raised before any commit.
        brief_run_id:  Set when ``status == 'ready'``; ``None`` otherwise.
        elapsed_s:     Wall-clock seconds spent waiting for the worker.
    """

    status: FirstBriefStatus
    brief_run_id: Optional[int]
    elapsed_s: float


def generate_first_brief_sync(
    briefing_id: int,
    *,
    deadline_seconds: Optional[float] = None,
    app: Optional[Flask] = None,
    generator: Optional[Callable[[int], Optional[int]]] = None,
) -> FirstBriefResult:
    """Spawn a worker thread to generate the first BriefRun for ``briefing_id``.

    Returns within ``deadline_seconds`` regardless of whether the worker
    finished. On timeout the worker keeps running — caller renders a
    "preparing" page; the row will be picked up on the next scheduler pass
    even if the worker dies mid-flight.

    Args:
        briefing_id:       Newly-created :class:`Briefing` to generate for.
        deadline_seconds:  Wall-clock seconds to wait. Defaults to the value
                           of ``FIRST_BRIEF_SYNC_DEADLINE_SECONDS`` from
                           Flask config (30s when unset).
        app:               Flask app to bind in the worker thread. Defaults
                           to ``current_app._get_current_object()``; must be
                           called from inside a request or app context unless
                           explicitly provided (e.g. in tests).
        generator:         Override the BriefRun generator. Takes a briefing
                           id and returns the committed BriefRun id (or
                           ``None``). Used by tests to avoid LLM calls.

    Returns:
        :class:`FirstBriefResult` describing the outcome.
    """
    # Resolve config + app before crossing the thread boundary.
    bound_app = app
    if bound_app is None:
        # _get_current_object pierces the LocalProxy so we hand the worker the
        # real Flask instance, not a request-bound proxy.
        bound_app = current_app._get_current_object()

    if deadline_seconds is None:
        deadline_seconds = float(bound_app.config.get('FIRST_BRIEF_SYNC_DEADLINE_SECONDS', 30))

    work_fn = generator or _default_generate_brief_run

    started = time.monotonic()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='first-brief')

    def _worker() -> Optional[int]:
        with bound_app.app_context():
            from app import db
            try:
                return work_fn(briefing_id)
            finally:
                # Always release the thread's scoped session, even when the
                # generator commits internally — prevents connection leaks.
                try:
                    db.session.remove()
                except Exception:
                    pass

    future: Future = executor.submit(_worker)

    try:
        brief_run_id = future.result(timeout=deadline_seconds)
    except FuturesTimeoutError:
        # Don't cancel the future — let the worker finish in the background.
        # The BriefRun row will appear; the scheduler will send/approve it.
        elapsed = time.monotonic() - started
        logger.info(
            "first-brief sync timed out after %.1fs (briefing_id=%s) — worker continues",
            elapsed, briefing_id,
        )
        # wait=False keeps the worker thread alive after executor goes away.
        executor.shutdown(wait=False, cancel_futures=False)
        return FirstBriefResult(status='pending', brief_run_id=None, elapsed_s=elapsed)
    except Exception as exc:
        elapsed = time.monotonic() - started
        logger.error(
            "first-brief sync failed (briefing_id=%s): %s",
            briefing_id, exc, exc_info=True,
        )
        executor.shutdown(wait=False)
        return FirstBriefResult(status='failed', brief_run_id=None, elapsed_s=elapsed)

    # Future completed within deadline — shut down executor cleanly.
    executor.shutdown(wait=False)
    elapsed = time.monotonic() - started

    if not brief_run_id:
        return FirstBriefResult(status='failed', brief_run_id=None, elapsed_s=elapsed)

    return FirstBriefResult(status='ready', brief_run_id=brief_run_id, elapsed_s=elapsed)


def _default_generate_brief_run(briefing_id: int) -> Optional[int]:
    """Production generator: call into :mod:`app.briefing.generator`.

    Returns the committed BriefRun id, or ``None`` if generation produced no
    row (e.g. briefing missing or inactive). The generator commits its own
    work — we only handle the thread-safety boundary here.
    """
    from app.briefing.generator import generate_brief_run_for_briefing

    brief_run = generate_brief_run_for_briefing(briefing_id)
    return brief_run.id if brief_run else None
