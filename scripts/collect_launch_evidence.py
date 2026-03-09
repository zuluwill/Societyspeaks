#!/usr/bin/env python3
"""
Collect Phase 6 launch-gate evidence artifacts into a timestamped bundle.

Usage:
  python3 scripts/collect_launch_evidence.py \
    --base-url https://societyspeaks.io \
    --admin-cookie "session=<cookie>" \
    --k6-summary load-tests/results/vote_storm.json \
    --k6-summary load-tests/results/read_storm.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any
from urllib import request


def _now_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _fetch_launch_room_health(base_url: str, admin_cookie: str | None) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/admin/launch-room/health.json"
    req = request.Request(url)
    if admin_cookie:
        req.add_header("Cookie", admin_cookie)
    req.add_header("Accept", "application/json")
    with request.urlopen(req, timeout=10) as resp:  # nosec: B310 (controlled by operator input)
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _summarize_k6(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "count": len(results),
        "files": [],
    }
    for item in results:
        path = item.get("__path")
        metrics = item.get("metrics", {})
        summary["files"].append(
            {
                "path": path,
                "http_req_failed_rate": metrics.get("http_req_failed", {}).get("values", {}).get("rate"),
                "http_req_duration_p95": metrics.get("http_req_duration", {}).get("values", {}).get("p(95)"),
                "http_req_duration_p99": metrics.get("http_req_duration", {}).get("values", {}).get("p(99)"),
                "iterations": metrics.get("iterations", {}).get("values", {}).get("count"),
            }
        )
    return summary


def _render_gate_report(health: dict[str, Any], k6_summary: dict[str, Any], stamp: str) -> str:
    queue = health.get("queue", {})
    consensus = queue.get("consensus", {})
    exports = queue.get("exports", {})
    integrity = health.get("integrity", {})
    dead_letter = integrity.get("dead_letter", {})

    return f"""# NSP Launch Gate Evidence ({stamp})

## Snapshot Inputs

- launch-room health endpoint: captured
- k6 summary files captured: {k6_summary.get('count', 0)}

## Operational Snapshot

- Consensus queue lag (s): {consensus.get('queue_lag_seconds')}
- Consensus dead-letter count: {consensus.get('dead_letter_count')}
- Export queue lag (s): {exports.get('queue_lag_seconds')}
- Export dead-letter count: {exports.get('dead_letter_count')}
- Integrity dead-letter (consensus/export): {dead_letter.get('consensus_jobs')}/{dead_letter.get('export_jobs')}

## Gate A: Integrity

- Status: TODO (set PASS/FAIL)
- Evidence:
  - launch-room integrity snapshot
  - duplicate vote checks
  - drift trend

## Gate B: Performance

- Status: TODO (set PASS/FAIL)
- Evidence:
  - k6 summary stats
  - p95/p99 results for vote/read
  - DB saturation notes

## Gate C: Data Delivery

- Status: TODO (set PASS/FAIL)
- Evidence:
  - export queue health
  - signed-download validation
  - NSP contract acceptance

## Gate D: Resilience

- Status: TODO (set PASS/FAIL)
- Evidence:
  - redis failover drill notes
  - worker crash recovery notes
  - queue backlog recovery notes
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect NSP launch evidence artifacts")
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--admin-cookie", default=None, help="session cookie for admin endpoint")
    parser.add_argument("--out-dir", default="artifacts/launch-gates")
    parser.add_argument("--k6-summary", action="append", default=[], help="Path to k6 summary JSON")
    args = parser.parse_args()

    stamp = _now_stamp()
    out_root = Path(args.out_dir) / stamp
    out_root.mkdir(parents=True, exist_ok=True)

    health = _fetch_launch_room_health(args.base_url, args.admin_cookie)
    (out_root / "launch_room_health.json").write_text(json.dumps(health, indent=2), encoding="utf-8")

    k6_results = []
    for path_str in args.k6_summary:
        path = Path(path_str)
        data = _read_json_file(path)
        data["__path"] = str(path)
        k6_results.append(data)

    k6_summary = _summarize_k6(k6_results)
    (out_root / "k6_summary_index.json").write_text(json.dumps(k6_summary, indent=2), encoding="utf-8")

    report = _render_gate_report(health, k6_summary, stamp)
    (out_root / "gate_report.md").write_text(report, encoding="utf-8")

    print(f"Launch evidence bundle written to: {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
