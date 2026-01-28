# Code Review: UX/UI Voting & Related Changes

**Review date:** 2025-01-28  
**Scope:** Newsletter pre-fill, statement back button, position pre-select, “Be First” threshold, inline argument prompt, gamification toasts, brief coverage display, right-leaning sources.

---

## Summary of fixes applied

| Issue                                            | Severity | Fix                                                                                                                           |
| ------------------------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------- | --- | ------------------------------------------------------------------------ |
| **Position pre-select used wrong attribute**     | Bug      | `user_vote.vote_value` → `user_vote.vote` (StatementVote has `.vote` not `.vote_value`)                                       |
| **“Write a detailed argument” link 404**         | Bug      | Link pointed to `/statements/<id>/respond` (no route). Updated to `/statements/<id>/responses/create?position=...`            |
| **Vote loading spinner never showed**            | Bug      | Spinner had `display: none` and JS only toggled `hidden`. Added `.is-loading` class and use it in JS to show spinner          |
| **Form POST from view_statement returned JSON**  | Bug      | Full-page form submit to `vote_statement` got JSON response. Added redirect when not AJAX so user sees updated statement page |
| **create_response ignored position query param** | UX       | GET `?position=pro                                                                                                            | con | neutral` now pre-fills the position field when coming from inline prompt |
| **DRY: duplicate vote forms**                    | DRY      | view_statement vote forms (auth vs anonymous) merged into one block with conditional classes                                  |

---

## Best practices & DRY

### Done well

- **Subscribe pre-fill:** Uses `current_user.is_authenticated and current_user.email`; readonly + helper text for logged-in users.
- **Brief coverage:** Only shows bar when `has_any_sources`; uses `item.sources_by_leaning is mapping` for safe access; transparency note when a perspective is missing.
- **quick_response route:** Validates position, min length, caps content at 500 chars; redirects back to discussion with `#statement-{id}`.
- **view_statement:** Back button at top; position selector pre-select and helper text; response form only for authenticated users.

### DRY

- view_statement vote forms were duplicated for auth vs anonymous; now a single block with `vote_btn_anon` and `vote_btn_title` derived from `current_user.is_authenticated`.
- Position validation in `quick_response` matches `create_response` (same valid_positions list).

### Recommendations

- **Hardcoded URLs in view_native.html:** Quick-response form uses `action="/statements/${statementId}/quick-response"`. If the app is mounted under a prefix (e.g. `/app/`), this will break. Consider injecting a base path (e.g. `data-base-url` or `window.APP_BASE`) and building the URL in JS, or rendering the action in a small inline script per statement.
- **Magic numbers:** `vote_display_threshold = 50` and “Need: 7+ statements, 50+ votes” appear in view_native.html. Consider a single config or template variable so they stay in sync.

---

## Edge cases & dependencies

### Handled

- **Anonymous on view_statement:** `user_vote` is `None`; position block is inside `{% if current_user.is_authenticated %}`, so anonymous users only see “Log in to add your response” and no position selector.
- **Subscribe with no email:** Condition is `current_user.is_authenticated and current_user.email`; if email is missing, the normal (editable) email field is shown.
- **quick_response:** Empty or short content: no DB write; flash “Response must be at least 5 characters”. Orphan statement (no discussion): redirect to search with error.
- **brief/view.html coverage:** `sources_by_leaning` guarded with `is mapping` and default `{}`; keys `left`/`center`/`right` match coverage_analyzer and generator.
- **vote_statement:** Form POST vs AJAX: non-JSON and non-`X-Requested-With: XMLHttpRequest` requests now redirect to view_statement with flash instead of returning JSON.

### Downstream (follow-up fixes applied)

- **User.name → username:** create_response.html, flag_statement.html, view_response.html, moderation_queue.html now use `username` with `{% if user %}...{% else %}Anonymous{% endif %}` so anonymous or missing authors don’t break.
- **Form POST vote errors:** vote_statement redirects form POSTs (non-AJAX) back to view_statement with flash on error (bot, missing vote, invalid value) instead of returning JSON.
- **view_native.html** inline argument prompt is only rendered when `{% if current_user.is_authenticated %}` in the vote success path, so anonymous users don’t see it (correct).
- **Brief items:** `sources_by_leaning` is set in generator and coverage_analyzer; brief view passes `items` from the DB, so existing briefs have the column. No code change required for that.

---

## Security & validation

- **quick_response:** `@login_required`, rate limit 30/min; position validated against allowlist; content length 5–500; CSRF via form token.
- **vote_statement:** Bot check on User-Agent; rate limit 30/min; vote value validated -1/0/1; CSRF on form POST (AJAX uses X-CSRFToken from template).
- **Subscribe:** CSRF token on form; email required; no sensitive data in template beyond pre-filled email for current user.

---

## Accessibility & UX

- Back link at top of statement page: clear and visible.
- Position pre-select and “Pre-selected based on your X vote” reduce friction.
- “Join the conversation” and tooltip for “Your perspective shapes the analysis” improve low-vote messaging.
- Inline argument prompt: optional short input or link to full form; auto-dismiss 30s; dismiss button with `aria-label="Dismiss"`.
- Gamification toasts: “X more to unlock full analysis” / “Analysis unlocked” give clear progress.
- Vote buttons on view_statement: anonymous get `title="Vote without an account"` for context.

---

## New sources (news_fetcher.py)

- 15 right-leaning sources added with leaning and reputation; no logic changes.
- **Action:** Run `flask seed-sources` (or your project’s equivalent) to insert them into the DB.

---

## Testing suggestions

1. **view_statement:** Log in, vote Agree → position “Pro” pre-selected; submit response form → success. Log out → vote buttons show “Vote without an account”; submit vote → redirect back to statement with “Vote recorded.”
2. **view_native:** Vote Agree/Disagree → toast and inline argument prompt (logged in only). Submit quick thought → redirect to discussion with anchor. Click “write a detailed argument” → create_response page with position pre-filled.
3. **Subscribe:** Logged in with email → email readonly, “Using your account email.” Logged out → normal email field.
4. **Brief view:** Item with no right sources → “No right coverage” and transparency note; bar only when `has_any_sources`.
