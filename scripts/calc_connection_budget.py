#!/usr/bin/env python3
"""
Compute Postgres connection budget for NSP readiness.

Formula:
  total_connections =
    web_workers * (pool_size + max_overflow) +
    worker_processes * pool_budget +
    admin_headroom

Usage:
  python3 scripts/calc_connection_budget.py \
    --web-workers 8 \
    --pool-size 10 \
    --max-overflow 20 \
    --worker-processes 3 \
    --worker-pool-budget 10 \
    --admin-headroom 30 \
    --max-connections 500
"""

from __future__ import annotations

import argparse
import json
import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Postgres connection budget calculator")
    parser.add_argument("--web-workers", type=int, default=_env_int("WEB_WORKERS", 4))
    parser.add_argument("--pool-size", type=int, default=_env_int("DB_POOL_SIZE", 10))
    parser.add_argument("--max-overflow", type=int, default=_env_int("DB_MAX_OVERFLOW", 20))
    parser.add_argument("--worker-processes", type=int, default=_env_int("WORKER_PROCESSES", 2))
    parser.add_argument("--worker-pool-budget", type=int, default=_env_int("WORKER_POOL_BUDGET", 10))
    parser.add_argument("--admin-headroom", type=int, default=_env_int("ADMIN_HEADROOM", 30))
    parser.add_argument("--max-connections", type=int, default=_env_int("PG_MAX_CONNECTIONS", 500))
    parser.add_argument("--reserve-percent", type=float, default=25.0)
    args = parser.parse_args()

    web_budget = args.web_workers * (args.pool_size + args.max_overflow)
    worker_budget = args.worker_processes * args.worker_pool_budget
    total_connections = web_budget + worker_budget + args.admin_headroom

    reserve_target = int(args.max_connections * (args.reserve_percent / 100.0))
    allowed_budget = args.max_connections - reserve_target
    within_budget = total_connections <= allowed_budget

    payload = {
        "inputs": {
            "web_workers": args.web_workers,
            "pool_size": args.pool_size,
            "max_overflow": args.max_overflow,
            "worker_processes": args.worker_processes,
            "worker_pool_budget": args.worker_pool_budget,
            "admin_headroom": args.admin_headroom,
            "max_connections": args.max_connections,
            "reserve_percent": args.reserve_percent,
        },
        "computed": {
            "web_budget": web_budget,
            "worker_budget": worker_budget,
            "total_connections": total_connections,
            "allowed_budget_after_reserve": allowed_budget,
            "reserve_target_connections": reserve_target,
            "within_budget": within_budget,
        },
        "formula": "total_connections = web_workers * (pool_size + max_overflow) + worker_processes * pool_budget + admin_headroom",
    }

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
