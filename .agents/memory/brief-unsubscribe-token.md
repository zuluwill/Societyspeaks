---
name: Stable unsubscribe token pattern
description: Both DailyBriefSubscriber and DailyQuestionSubscriber use a stable unsubscribe_token separate from the rotating magic_token.
---

# Stable Unsubscribe Token Pattern

## The rule
Email unsubscribe links must use `subscriber.unsubscribe_token`, NOT `subscriber.magic_token`.
Always write `subscriber.unsubscribe_token or subscriber.magic_token` in email clients for backward compatibility with pre-migration emails.

**Why:** `magic_token` rotates — for DailyBriefSubscriber it rotates when a user clicks an expired magic link; for DailyQuestionSubscriber it rotates before every daily batch send. Both patterns silently break unsubscribe links in older emails.

**How to apply:**
- `magic_token` → authentication only (magic link, preferences link). Can rotate freely.
- `unsubscribe_token` → unsubscribe link in all emails. Set once via `ensure_unsubscribe_token()`. Never changes.
- Both models (`DailyBriefSubscriber`, `DailyQuestionSubscriber`) have `ensure_unsubscribe_token()`.
- Call `ensure_unsubscribe_token()` in every creation AND reactivation path, immediately after `generate_magic_token()`.
- Both unsubscribe routes (`/brief/unsubscribe/<token>`, `/daily/unsubscribe/<token>`) do dual lookup: `unsubscribe_token` first, `magic_token` fallback.
- Both routes accept GET (human click) AND POST (RFC 8058 one-click for Gmail/Yahoo). Brief returns `''`/200 for any POST; Daily detects one-click via `request.form.get('List-Unsubscribe') == 'One-Click'` to distinguish from its two-step reason-capture form POST.
- Migrations use `gen_random_uuid()` — never deterministic tokens.
- Migration chain: `ab1cd2ef3gh4` (brief) → `cd2ef3gh4ij5` (daily question). Single linear head.
