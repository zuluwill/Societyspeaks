---
name: Brief unsubscribe token design
description: Why DailyBriefSubscriber has two separate tokens and how each is used.
---

# Brief Subscriber Token Architecture

## The rule
Email unsubscribe links must use `subscriber.unsubscribe_token`, NOT `subscriber.magic_token`.
The `magic_link` route regenerates `magic_token` on expiry — this would silently break any in-flight unsubscribe link.

**Why:** When a user clicks "View in Browser" from an older email, the magic_token rotates (new random value replaces old). Any unsubscribe link in that email (or older ones) that used the old token would then return "Invalid unsubscribe link."

**How to apply:**
- `magic_token` → authentication only (magic link, preferences link). Expires and rotates.
- `unsubscribe_token` → unsubscribe link in all emails. Set once on subscriber creation via `ensure_unsubscribe_token()`. Never changes.
- Both the `unsubscribe` route and the `switch_to_weekly` route look up by `unsubscribe_token` first, then fall back to `magic_token` for pre-migration emails.
- The unsubscribe route accepts GET (human click) AND POST (RFC 8058 one-click unsubscribe for Gmail/Yahoo bulk sender compliance).
- Migration uses `gen_random_uuid()` — never deterministic/predictable tokens.
- Daily question system (DailyQuestionSubscriber / resend_client.py) is unaffected: its magic_link route does NOT regenerate the token, so old unsubscribe links remain valid.
