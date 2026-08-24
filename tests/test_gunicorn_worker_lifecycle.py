"""Contracts for gunicorn worker recycle / PostHog shutdown (Render /health)."""

import inspect
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import gunicorn_config

ROOT = Path(__file__).resolve().parents[1]


def test_preload_app_stays_off():
    assert gunicorn_config.preload_app is False


def test_max_requests_recycle_stays_enabled_with_jitter():
    """Recycle bounds per-worker memory; jitter avoids lockstep SIGKILLs."""
    assert gunicorn_config.max_requests == 1000
    assert gunicorn_config.max_requests_jitter >= 300


def test_worker_exit_bounds_posthog_shutdown_with_gevent_timeout():
    src = inspect.getsource(gunicorn_config.worker_exit)
    assert "shutdown_server_posthog" in src
    assert "GeventTimeout" in src
    assert gunicorn_config._WORKER_EXIT_BUDGET_SECONDS <= 5.0


def test_worker_exit_disarms_sdk_atexit_join_before_drain():
    """PYTHON-FLASK-JD: SDK atexit(self.join) runs after worker_exit on recycle."""
    src = inspect.getsource(gunicorn_config.worker_exit)
    assert "disarm_posthog_blocking_shutdown" in src
    assert src.index("disarm_posthog_blocking_shutdown") < src.index(
        "shutdown_server_posthog()"
    )


def test_render_web_keeps_profiling_off():
    src = Path("render.yaml").read_text(encoding="utf-8")
    assert 'SENTRY_PROFILES_SAMPLE_RATE' in src
    assert 'SENTRY_CONTINUOUS_PROFILING' in src
    assert 'value: "0"' in src.split("SENTRY_PROFILES_SAMPLE_RATE", 1)[1][:200]
    assert 'value: "false"' in src.split("SENTRY_CONTINUOUS_PROFILING", 1)[1][:200]


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _read_log(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _wait_log_count(path: Path, needle: str, count: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        text = _read_log(path)
        if text.count(needle) >= count:
            return text
        time.sleep(0.05)
    raise AssertionError(
        f"gunicorn log never contained {needle!r} {count} times within "
        f"{timeout}s (saw {text.count(needle)})\n{text[-4000:]}"
    )


def _wait_log_contains(path: Path, needle: str, timeout: float) -> str:
    return _wait_log_count(path, needle, 1, timeout)


def _http_ok(url: str, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                body = resp.read()
                if resp.status == 200:
                    return body
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last = exc
        time.sleep(0.05)
    raise AssertionError(f"never got HTTP 200 from {url}: {last}")


def _kill_pg(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
    proc.wait(timeout=5)


def test_gunicorn_gevent_recycle_with_live_posthog_client_exits_fast(tmp_path):
    """PYTHON-FLASK-JD: recycle must not hang in PostHog join/flush/shutdown.

    Boots the production gunicorn config (gevent, preload off, worker_exit)
    with ``max_requests=1`` and a live async PostHog client. The old worker
    must log ``Worker exiting`` well inside gunicorn's abort timeout. A
    source-only unit test cannot catch this; the hang is OS Thread.join from
    the hub after worker_exit returns.
    """
    port = _free_port()
    log_path = tmp_path / "gunicorn-recycle.log"
    log_file = log_path.open("wb", buffering=0)
    env = os.environ.copy()
    env.update(
        {
            "FLASK_ENV": "development",
            "DATABASE_URL": "sqlite:///:memory:",
            "SECRET_KEY": "gunicorn-recycle-test-not-for-production",
            "WEB_CONCURRENCY": "1",
            "POSTHOG_API_KEY": "phc_gunicorn_recycle_test",
            "POSTHOG_HOST": "http://127.0.0.1:1",
            "SENTRY_DSN": "",
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(ROOT),
        }
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gunicorn",
            "-c",
            str(ROOT / "gunicorn_config.py"),
            "--bind",
            f"127.0.0.1:{port}",
            "--workers",
            "1",
            "--worker-class",
            "gevent",
            "--timeout",
            "8",
            "--graceful-timeout",
            "4",
            "--max-requests",
            "1",
            "--max-requests-jitter",
            "0",
            "tests.gunicorn_posthog_recycle_wsgi:app",
        ],
        cwd=ROOT,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    url = f"http://127.0.0.1:{port}/health"
    try:
        boot = _wait_log_contains(log_path, "POSTHOG_RECYCLE_PROBE", timeout=20.0)
        assert "Booting worker" in boot
        probe = [
            line
            for line in boot.splitlines()
            if line.startswith("POSTHOG_RECYCLE_PROBE")
        ]
        assert probe, boot[-2000:]
        assert "sync_mode=False" in probe[-1], probe[-1]
        assert "gevent_threads=True" in probe[-1], probe[-1]
        consumers = int(probe[-1].split("consumers=")[1].split()[0])
        assert consumers >= 1, probe[-1]

        _http_ok(url, timeout=8.0)
        recycle_started = time.monotonic()
        _wait_log_contains(log_path, "Worker exiting", timeout=5.0)
        recycle_elapsed = time.monotonic() - recycle_started
        assert recycle_elapsed < 4.0, (
            f"worker recycle took {recycle_elapsed:.2f}s — PostHog teardown "
            f"is blocking the hub again\n{_read_log(log_path)[-4000:]}"
        )

        _wait_log_count(log_path, "POSTHOG_RECYCLE_PROBE", 2, timeout=8.0)
        _wait_log_count(log_path, "Booting worker", 2, timeout=8.0)
        _http_ok(url, timeout=8.0)

        os.kill(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=6.0)
        except subprocess.TimeoutExpired:
            _kill_pg(proc)
            raise AssertionError(
                "gunicorn master did not exit within 6s after SIGTERM\n"
                + _read_log(log_path)[-4000:]
            )
    finally:
        log_file.close()
        if proc.poll() is None:
            _kill_pg(proc)

    log = _read_log(log_path)
    assert "WORKER TIMEOUT" not in log, log[-4000:]
    assert "worker_abort" not in log, log[-4000:]
    assert log.count("Booting worker") >= 2, log[-4000:]
    assert log.count("Worker exiting") >= 1, log[-4000:]
    assert log.count("POSTHOG_RECYCLE_PROBE") >= 2, log[-4000:]
