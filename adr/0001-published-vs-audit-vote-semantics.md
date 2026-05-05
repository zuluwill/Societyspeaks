# ADR 0001: Published vs audit vote semantics

**Status:** Accepted  
**Date:** 2026-05-05  

## Context

`statement_vote` rows can reference statements that are later deleted or negatively moderated. Those rows remain useful for **audit, debugging, and some research pipelines**, but must not inflate **participant-facing** totals or journey progress without an explicit, documented choice.

Anonymous voters may appear under multiple `session_fingerprint` values before cookie unification; lookups merge **aliases** (see `app.lib.vote_identity`). Persisting new votes still uses one canonical fingerprint per row (database uniqueness).

## Decision

1. **Published / participant-facing aggregates** (UI, partner dashboards where we promise “what participants see”, programme summaries aligned with discussions, journey/recap numerators we have aligned):

   - Count votes only on **visible statements**: `is_deleted == False` and `mod_status >= 0`.
   - Implementation: `visible_statement_vote_filters()` and `PUBLIC_PARTICIPANT_COUNT_PARAMS` in `app/lib/participation_metrics.py`.
   - Anonymous identity: use `anonymous_fingerprint_aliases_for_daily_lookup()` (or code paths that delegate to it: `get_user_response`, `_build_user_votes_map`, journey batch helpers, etc.) so legacy cookies and embed fingerprints do not split one visitor into zero progress.

2. **Audit / raw storage**

   - Rows on deleted or negatively moderated statements **stay in `statement_vote`** unless a separate retention or GDPR process deletes them.
   - Any export, notebook, or admin report that must include **every cast vote** must be **explicitly labelled** (e.g. “raw votes”, “audit export”) and must **not** silently reuse published headline numbers.

3. **Moderator / creator views**

   - Views that intentionally include withheld statements must pass **`min_mod_status=None`** (or equivalent) to counting helpers and should be limited to authorised roles. Do not change defaults in `participation_metrics` for this without updating this ADR.

## Consequences

- New features that show vote counts, participation, or “your progress” should default to **`visible_statement_vote_filters`** and alias-aware anonymous lookups unless the product spec explicitly defines another mode.
- Comparing “PostHog journey” metrics to on-site participation may still diverge if events use different definitions; align analytics specs with this ADR where possible.

## References

- `app/lib/participation_metrics.py` — filter helpers and `PUBLIC_PARTICIPANT_COUNT_PARAMS`
- `app/lib/vote_identity.py` — anonymous fingerprint aliases and cookies
- `app/programmes/journey.py` — journey/recap batch counts (visible statements + anon aliases)
