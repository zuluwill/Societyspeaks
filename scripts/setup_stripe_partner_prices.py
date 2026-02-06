#!/usr/bin/env python3
"""
One-time script to create Partner tier Products and Prices in Stripe.

Usage:
    # Dry run (shows what would be created):
    python3 scripts/setup_stripe_partner_prices.py

    # Actually create in Stripe:
    python3 scripts/setup_stripe_partner_prices.py --execute

    # Use a specific Stripe key:
    STRIPE_SECRET_KEY=sk_test_xxx python3 scripts/setup_stripe_partner_prices.py --execute

Requires STRIPE_SECRET_KEY to be set (via .env or environment).
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import stripe

TIERS = [
    {
        'name': 'Society Speaks Partner - Starter',
        'description': 'For independent publishers, blogs, and niche sites. Up to 100 live discussions per month.',
        'amount': 4900,
        'currency': 'gbp',
        'interval': 'month',
        'env_var': 'PARTNER_STRIPE_PRICE_STARTER',
        'metadata': {'tier': 'starter', 'product': 'partner'},
    },
    {
        'name': 'Society Speaks Partner - Professional',
        'description': 'For regional publishers and growing newsrooms. Up to 500 live discussions per month.',
        'amount': 24900,
        'currency': 'gbp',
        'interval': 'month',
        'env_var': 'PARTNER_STRIPE_PRICE_PROFESSIONAL',
        'metadata': {'tier': 'professional', 'product': 'partner'},
    },
]

TRIAL_DAYS = 14


def main():
    api_key = os.getenv('STRIPE_SECRET_KEY')
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY not set. Set it in .env or environment.")
        sys.exit(1)

    stripe.api_key = api_key

    is_test = api_key.startswith('sk_test_')
    execute = '--execute' in sys.argv

    print(f"\n{'=' * 60}")
    print(f"  Stripe Partner Price Setup")
    print(f"  Mode: {'TEST' if is_test else '*** LIVE ***'}")
    print(f"  Action: {'EXECUTING' if execute else 'DRY RUN (pass --execute to create)'}")
    print(f"{'=' * 60}\n")

    if not is_test and execute:
        confirm = input("WARNING: You are about to create LIVE Stripe products. Type 'yes' to confirm: ")
        if confirm.strip().lower() != 'yes':
            print("Aborted.")
            sys.exit(0)

    env_lines = []

    for tier in TIERS:
        print(f"Product: {tier['name']}")
        print(f"  Price:       £{tier['amount'] / 100:.2f}/{tier['interval']}")
        print(f"  Trial:       {TRIAL_DAYS} days")
        print(f"  Env var:     {tier['env_var']}")

        if execute:
            product = stripe.Product.create(
                name=tier['name'],
                description=tier['description'],
                metadata=tier['metadata'],
            )
            print(f"  Product ID:  {product.id}")

            price = stripe.Price.create(
                product=product.id,
                unit_amount=tier['amount'],
                currency=tier['currency'],
                recurring={
                    'interval': tier['interval'],
                    'trial_period_days': TRIAL_DAYS,
                },
                metadata=tier['metadata'],
            )
            print(f"  Price ID:    {price.id}")
            env_lines.append(f"{tier['env_var']}={price.id}")
        else:
            print(f"  (would create product and price)")
            env_lines.append(f"{tier['env_var']}=price_xxx  # will be set after --execute")

        print()

    print(f"{'=' * 60}")
    print("  Add these to your environment / .env:\n")
    for line in env_lines:
        print(f"  {line}")
    print(f"\n{'=' * 60}")

    if not execute:
        print("\nThis was a dry run. Run with --execute to create in Stripe.\n")


if __name__ == '__main__':
    main()
