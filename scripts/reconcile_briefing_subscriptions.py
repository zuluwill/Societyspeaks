#!/usr/bin/env python3
"""Run Paid Briefings Stripe reconciliation once (ops / cron wrapper).

Requires the same environment as the web app (DATABASE_URL, STRIPE_SECRET_KEY, Redis if used).
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main():
    from app import create_app

    application = create_app()
    with application.app_context():
        from app.billing.reconciliation import reconcile_briefing_subscriptions_batch

        stats = reconcile_briefing_subscriptions_batch()
        print(stats)


if __name__ == '__main__':
    main()
