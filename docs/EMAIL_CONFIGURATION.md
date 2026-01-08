# Email Configuration Guide

Society Speaks uses **Resend** (https://resend.com) for all transactional emails.

> **Migration Note:** This system was migrated from Loops.so to Resend in January 2026 for better performance, cost efficiency, and simpler integration.

## Required Environment Variables

```bash
# Required: Your Resend API key
# Get one at: https://resend.com/api-keys
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# From addresses for different email types
# These must be verified domains in your Resend account
RESEND_FROM_EMAIL="Society Speaks <hello@societyspeaks.io>"
RESEND_DAILY_FROM_EMAIL="Daily Questions <daily@societyspeaks.io>"

# Base URL for building links in emails (no trailing slash)
BASE_URL=https://societyspeaks.io
```

## Email Types

### 1. Transactional Emails (`app/resend_client.py`)

| Email Type | Function | When Sent |
|------------|----------|-----------|
| Password Reset | `send_password_reset_email()` | User requests password reset |
| Welcome | `send_welcome_email()` | New user registration |
| Account Activation | `send_account_activation_email()` | After registration (if enabled) |
| Daily Question Welcome | `send_daily_question_welcome_email()` | New daily question subscriber |
| Daily Question | `send_daily_question_to_all_subscribers()` | Daily at 8am UTC |

### 2. Daily Brief Emails (`app/brief/email_client.py`)

| Email Type | Function | When Sent |
|------------|----------|-----------|
| Daily Brief | `BriefEmailScheduler.send_todays_brief_hourly()` | Every hour (timezone-aware) |

## Features

- **Batch API Support**: High-volume sends use Resend's Batch API (up to 100 emails per request)
- **Rate Limiting**: 14 emails/sec for single sends
- **List-Unsubscribe Headers**: CAN-SPAM/GDPR compliance
- **Retry Logic**: Exponential backoff on failures
- **Magic Links**: Passwordless authentication for daily questions
- **Unified Analytics**: Track opens, clicks, bounces across ALL email types

## Email Analytics

The system includes unified email analytics via the `EmailEvent` model and `EmailAnalytics` service.

### Categories Tracked

| Category | Description |
|----------|-------------|
| `auth` | Password reset, welcome, account activation |
| `daily_brief` | Daily Brief emails |
| `daily_question` | Daily Question emails |
| `discussion` | Discussion notification emails |
| `admin` | Admin-generated emails |

### Events Tracked

- `sent` - Email sent to Resend
- `delivered` - Email delivered to recipient
- `opened` - Recipient opened email
- `clicked` - Recipient clicked a link
- `bounced` - Email bounced (hard/soft)
- `complained` - Recipient marked as spam

### Admin Dashboard

Access analytics at: `/brief/admin/analytics`

Features:
- Overall and per-category statistics
- Open rate, click rate, bounce rate
- Recent events feed
- Filter by category and time period

## Architecture

```
app/
├── resend_client.py        # Unified Resend client for all emails
├── brief/
│   └── email_client.py     # Daily Brief specific (uses Resend)
├── email_utils.py          # Legacy (RateLimiter class, some utilities)
└── templates/
    └── emails/
        ├── base_email.html
        ├── password_reset.html
        ├── welcome.html
        ├── account_activation.html
        ├── daily_question.html
        ├── daily_question_welcome.html
        └── daily_brief.html
```

## Migration from Loops.so

The following Loops.so variables are **deprecated** and can be removed:

```bash
# DEPRECATED - Remove after confirming Resend works
LOOPS_API_KEY=xxxxxxxxx
LOOPS_DAILY_WELCOME_ID=xxxxxxxxx
LOOPS_DAILY_QUESTION_ID=xxxxxxxxx
```

### What Changed

| Feature | Before (Loops) | After (Resend) |
|---------|----------------|----------------|
| Email delivery | 4 emails/sec | 14 emails/sec |
| Batch sending | N/A (individual calls) | 100 emails/batch |
| Templates | Hosted in Loops dashboard | Jinja2 in codebase |
| Contact management | In Loops | Database only |
| Unsubscribe handling | Loops + DB sync | DB only + List-Unsubscribe |

### Deprecated Features

- **Loops Events**: `send_loops_event()` was used for analytics and automations. This functionality has been removed. Use PostHog or similar for event tracking.
- **Profile Completion Reminders**: Previously triggered via Loops events. To be re-implemented if needed.
- **Weekly Discussion Digest**: Temporarily disabled. Can be re-implemented using Resend.

## Troubleshooting

### "RESEND_API_KEY not set"

Ensure `RESEND_API_KEY` is set in your environment or `.env` file.

### Emails not sending

1. Check Resend dashboard for delivery status
2. Verify domain is verified in Resend
3. Check logs for error messages

### High failure rate

1. Check rate limiting (14/sec limit)
2. Verify email addresses are valid
3. Check Resend account quota

## Testing

Send a test email:

```python
from app.resend_client import get_resend_client

client = get_resend_client()
# Test transactional email...
```
