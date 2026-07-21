#!/usr/bin/env python3
"""Send ONE real daily-brief email to a single address, for client-rendering tests.

Safe by construction:
  * Renders exactly what subscribers receive (render -> minify/fit -> wrap_links),
    but sends to exactly ONE explicit recipient — never the subscriber list.
  * Reads the DB read-only (rendering performs no writes; vote tokens are signed,
    not persisted). Point DATABASE_URL at the read-only analysis role if you have it.
  * Uses the recipient's OWN subscriber tokens when they are a subscriber, so magic
    and vote links are valid for them and no one else. If the recipient is not a
    subscriber, placeholder tokens are used and those links are inert (rendering is
    still faithful — the point of the test).

Usage:
    RESEND_API_KEY=... DATABASE_URL=... \
      python scripts/send_brief_test_email.py you@example.com [YYYY-MM-DD]

Prints a summary and asks nothing else — running it sends the email.
"""
import os
import sys

import requests


def main() -> int:
    if len(sys.argv) < 2 or ',' in sys.argv[1] or '@' not in sys.argv[1]:
        print("usage: send_brief_test_email.py <single-recipient@addr> [YYYY-MM-DD]")
        print("refusing to run without exactly one recipient address.")
        return 2
    recipient = sys.argv[1].strip()
    date_arg = sys.argv[2].strip() if len(sys.argv) > 2 else None

    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        print("RESEND_API_KEY not set — cannot send. Aborting.")
        return 2

    from app import create_app
    from app.models import DailyBrief, DailyBriefSubscriber
    from app.brief.email_client import ResendClient, _email_html_byte_size
    from app.briefing.link_tracker import wrap_links
    from app.storage_utils import get_base_url

    app = create_app()
    with app.app_context():
        from datetime import date as _date

        if date_arg:
            y, m, d = (int(x) for x in date_arg.split('-'))
            brief = DailyBrief.query.filter_by(
                date=_date(y, m, d), status='published', brief_type='daily').first()
        else:
            brief = DailyBrief.get_latest_published(brief_type='daily')
        if brief is None:
            print("No published daily brief found for that date.")
            return 1

        sub = DailyBriefSubscriber.query.filter_by(email=recipient).first()
        if sub is None:
            # Non-persisted placeholder: links are inert but rendering is faithful.
            sub = DailyBriefSubscriber(
                email=recipient, status='active',
                magic_token='TESTPREVIEW', unsubscribe_token='TESTPREVIEW')
            using = 'placeholder tokens (inert links)'
        else:
            using = f'subscriber #{sub.id} own tokens (working links)'

        client = ResendClient.__new__(ResendClient)
        client._disabled = True
        client.api_key = api_key
        client._from_email_addr = app.config.get('BRIEF_FROM_EMAIL', 'hello@brief.societyspeaks.io')
        client.from_email = f'Daily Brief <{client._from_email_addr}>'
        client.reply_to = os.environ.get('BRIEF_REPLY_TO', client._from_email_addr)

        items = client._get_sorted_brief_items(brief)
        html = client._render_email(sub, brief, sorted_items=items)
        base_url = get_base_url()
        html = wrap_links(html=html, base_url=base_url, run_id=brief.id,
                          r_hash=str(sub.id or 0), secret=app.config.get('SECRET_KEY', ''),
                          track_path='/brief/track/click')

        size_kb = _email_html_byte_size(html) / 1024
        print(f"Brief:      {brief.date} ({len(items)} stories)")
        print(f"Recipient:  {recipient}   [{using}]")
        print(f"From:       {client.from_email}")
        print(f"HTML size:  {size_kb:.1f} KB")

        resp = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'from': client.from_email,
                'to': [recipient],            # single recipient, by construction
                'subject': f'[TEST] {brief.title}',
                'html': html,
                'reply_to': client.reply_to,
            },
            timeout=30,
        )
        if resp.status_code >= 300:
            print(f"SEND FAILED {resp.status_code}: {resp.text[:300]}")
            return 1
        print(f"SENT ✓  id={resp.json().get('id')}")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
