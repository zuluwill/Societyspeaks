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
    warmup_budget_seconds: Optional[float] = None,
    app: Optional[Flask] = None,
    generator: Optional[Callable[[int], Optional[int]]] = None,
) -> FirstBriefResult:
    """Spawn a worker thread to generate the first BriefRun for ``briefing_id``.

    Returns within ``deadline_seconds`` regardless of whether the worker
    finished. On timeout the worker keeps running — caller renders a
    "preparing" page; the row will be picked up on the next scheduler pass
    even if the worker dies mid-flight.

    Args:
        briefing_id:          Newly-created :class:`Briefing` to generate for.
        deadline_seconds:     Wall-clock seconds the *route* waits for the
                              worker. Defaults to
                              ``FIRST_BRIEF_SYNC_DEADLINE_SECONDS``. Keep this
                              below the platform's HTTP request timeout
                              (typically 30-60s) — the worker still finishes
                              in the background past the deadline.
        warmup_budget_seconds: How long the worker spends ingesting sources
                              before generation. Defaults to
                              ``BRIEFING_SOURCE_WARMUP_SECONDS``. For the
                              trial signup path, pass a value smaller than
                              ``deadline_seconds`` so generation gets a fair
                              shot at completing within the wait window.
        app:                  Flask app to bind in the worker thread.
        generator:            Override for tests. Takes (briefing_id) and
                              returns the committed BriefRun id or None.
                              When set, ``warmup_budget_seconds`` is ignored.

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

    if generator is not None:
        work_fn = generator
    else:
        # Bind the warmup budget so the worker thread sees the caller's choice.
        def work_fn(bid: int) -> Optional[int]:
            return _default_generate_brief_run(
                bid, warmup_budget_seconds=warmup_budget_seconds,
            )

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


def _default_generate_brief_run(
    briefing_id: int, *, warmup_budget_seconds: Optional[float] = None,
) -> Optional[int]:
    """Production generator: warm up sources, then generate the BriefRun.

    Args:
        briefing_id:           Briefing to generate for.
        warmup_budget_seconds: Cap on synchronous ingestion before generation.
                               When ``None``, falls back to the global
                               ``BRIEFING_SOURCE_WARMUP_SECONDS`` config. The
                               trial signup path passes a short value (e.g.
                               20s) so the *page* doesn't block on slow feeds
                               — the worker is still allowed to finish
                               afterward, the brief simply uses whatever
                               content was available at generation time.

    Returns:
        Committed ``BriefRun`` id, or ``None`` when generation produced no
        row (briefing missing/inactive/no items).
    """
    from app.briefing.generator import generate_brief_run_for_briefing
    from app.briefing.source_warmup import warm_up_briefing_by_id

    warm_up_briefing_by_id(briefing_id, budget_seconds=warmup_budget_seconds)
    brief_run = generate_brief_run_for_briefing(
        briefing_id,
        skip_warmup=True,
    )
    return brief_run.id if brief_run else None
