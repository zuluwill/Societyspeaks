"""Process-liveness heartbeat cadence.

The beat must mean "process alive", not "process between jobs". A 120s Redis
TTL with a 20s interval leaves room to miss a tick without flapping, and is
shorter than the scheduler's 5-minute sweep so a real crash is noticed on
the next look.

``run_heartbeat_loop`` is a plain function so tests can drive it without
importing ``scripts/run_consensus_worker.py``, which mutates process env
(``CONSENSUS_WORKER_PROCESS``, ``DISABLE_SCHEDULER``) at import time.
"""

import logging

logger = logging.getLogger(__name__)

HEARTBEAT_TTL_SECONDS = 120
HEARTBEAT_INTERVAL_SECONDS = 20


def run_heartbeat_loop(publish, stop_event, interval=HEARTBEAT_INTERVAL_SECONDS):
    """Beat until ``stop_event`` is set. A publish failure must not kill the loop.

    C-extension clustering (numpy/sklearn) releases the GIL, so this can run
    on a daemon thread beside a long job. A multi-minute *pure-Python* hold
    of the GIL would still starve it — that is not how the consensus engine
    spends its time.
    """
    while not stop_event.is_set():
        try:
            publish()
        except Exception as exc:
            logger.debug("Heartbeat tick failed: %s", exc)
        stop_event.wait(interval)
