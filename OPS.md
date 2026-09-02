# Production operations — Society Speaks
#
# Stack: Render (Frankfurt) + Neon (London) + S3 (London) + Redis Cloud (London)
# Deploy: push to GitHub `main` → Render Blueprint auto-deploy
# Detail: RENDER_DEPLOY.md

## Daily deploy

```bash
git push origin main
```

Render rebuilds web + scheduler + consensus worker. Web and scheduler both run `flask db upgrade` pre-deploy.

**Deploy order when migrations add columns:** web and scheduler preDeploy both run `flask db upgrade`. Concurrent upgrades are serialised by a Postgres advisory transaction lock in `migrations/env.py` (`acquire_migration_lock` in `app/lib/db_migration_guard.py`) — without it, two services upgrading at once can race on the same DDL and one deploy fails with "column already exists". The scheduler process also refuses to start if the DB revision lags Alembic head (`assert_db_at_head`). If a worker logs `refusing to start: database revision … is not at Alembic head`, run `flask db upgrade` on web (or a one-off shell) before redeploying workers.

**Auto-deploy on `main` is intentional** for a solo production app. Prefer `autoDeployTrigger: checksPass` later if CI is green and you want fewer bad deploys — not `off` unless you want manual releases.

Web health checks use **`/health`** (not `/`). That endpoint is built for deploy liveness and avoids homepage DB/Redis warmup flakes that caused “connection refused” emails.

After env-only changes: Render → service → **Manual Deploy**.

**Scheduler “Application exited early” emails:** expected on deploys (SIGTERM). Recurring every ~30 minutes meant the old Replit timed self-exit was still on — Render uses `SCHEDULER_MAX_RUNTIME_SECONDS=0` so the process stays up. Watch Metrics RSS; only re-enable a timed recycle if memory grows without bound.

**Worker restart emails** (scheduler / consensus) on every push are normal — those services restart with the new image. Keep Render notifications on **failure-only**.

**Web “connection refused” on `/health` while the instance is already live:** this is gunicorn killing workers, not a slow 200. Root cause (Aug 2026): `worker_exit` called PostHog `flush()`/`shutdown()`, which `Thread.join()`s OS consumers from the gevent hub after the Queue/Thread rebind. The hub wedges until gunicorn’s 120s timeout, then SIGKILL; overlapping kills of `WEB_CONCURRENCY=3` leave nothing listening on :5000. Recycle (`max_requests=1000`) is the memory bound — do not disable it. Confirm with log grep:

```text
WORKER TIMEOUT
was sent SIGKILL
shutdown_server_posthog
Thread.join
```

A stack that bottoms out in `ph.shutdown()` / `client.join` / `lane.flush` / `Poller.stop` is the PostHog hang. `worker_exit` must never call those APIs (drain every lane by `qsize`, pause consumers and the poller). The SDK registers `atexit.register(self.join)` with no timeout, and `Client.shutdown()` still does unbounded `wait_for_sync_sends` + `flush(None)` + `join` — recycle then hangs the main greenlet after `worker_exit` (PYTHON-FLASK-JD, 2026-08-24). We skip those atexit handlers, wrap the SDK teardown methods so they no-op under gevent, and drain both analytics and AI lanes. `GeventTimeout` around `worker_exit` cannot interrupt OS `Thread.join`. CI proves this with `test_gunicorn_gevent_recycle_with_live_posthog_client_exits_fast` (real gunicorn+gevent, `max_requests=1`, live async PostHog consumers). Recurring `WORKER TIMEOUT` / `worker_abort` whose dump is **not** in PostHog teardown is a real request stall and should still page — do not add those phrases to the lifecycle drop list. SIGTERM / SIGKILL / “Perhaps out of memory?” (gunicorn’s generic abort text, not proven OOM) stay dropped.

Confirm dashboard `SENTRY_PROFILES_SAMPLE_RATE=0` and `SENTRY_CONTINUOUS_PROFILING` unset/false on web workers. Profiling threads showed up on every abort dump and fight the hub.

**Neon SSL `unexpected message` (Sentry PYTHON-FLASK-FF):** handshake blip at connect time, not a bad DSN. Classified with the other transient phrases in `app/lib/db_transient_errors.py`; `config._make_retry_creator` retries it; HTTP is 503. `/briefings/start` also has `@retry_on_db_disconnect` for mid-request drops. Recurring storms after deploy → check Neon/Redis, do not reclassify as a hard 500.

**Reserved `example.com` Resend 422:** send paths skip RFC 2606 documentation domains. After deploy, `flask list-reserved-emails` lists leftover subscriber/user rows to unsubscribe.

## Weekly brief (`wk001` and regeneration)

**Three different "weekly" products** — do not conflate them in ops or analytics:

| Product | Table / cadence | Send window |
|---|---|---|
| Weekly Brief (reading) | `daily_brief_subscriber.cadence='weekly'` | Subscriber's `preferred_weekly_day` / hour |
| Weekly questions digest (participation) | `daily_question_subscriber.email_frequency='weekly'` | Each sub's `preferred_send_day` + hour (109 on Tue 09:00 UTC when `timezone` is NULL) |
| Dormant discussion digest | `user.weekly_digest_enabled` | Not scheduled |

**Regenerate a live edition safely:**

```bash
flask generate-weekly-brief --date 2026-07-26 --force
```

`--force` rebuilds items in place. If the edition was already **`published`**, status and `published_at` are preserved so `/brief/weekly` never goes dark — the auto-publish job only promotes briefs dated **today**, so demoting an older edition to `ready` would black it out permanently. Test send: `flask test-brief-email you@example.com --type weekly`.

**`wk001` (`brief_item.weekly_development`):** deploy web + scheduler together; both preDeploy migrations must reach head before workers load code that maps the new column. SQLAlchemy selects every mapped column on `BriefItem` — a schema lag breaks daily sends too, not just weekly.

**Weekly digest timezone hygiene:** `DailyQuestionSubscriber.timezone=NULL` is treated as UTC at send time (Tuesday 09:00 UTC for the bulk of weekly digest subs). This is correct behaviour and is now visible: the admin subscriber list renders `UTC · not set` for those rows, and `/daily/preferences` already shows UTC.

Size the cohort with:

```bash
flask backfill-dq-subscriber-timezones --dry-run
```

**Do not run the write step as routine hygiene.** It changes no send behaviour and improves no display — it only overwrites NULL with `UTC`, which permanently erases the difference between *"imported, never asked"* and *"chose UTC"*. That NULL is the query that finds the ~109 people receiving a 09:00 UTC digest at an arbitrary local hour — the exact audience for a "when would you like this?" email. Collect real timezones first; only then make stragglers explicit.

The fix for the underlying UX gap is asking subscribers for a delivery time, not asserting one on their behalf.

## Neon pooler — never session READ ONLY

Production `DATABASE_URL` is the Neon **`-pooler`** endpoint (PgBouncer transaction mode). Session settings stick on the backend and are reused by the next client.

**Do not** open ops/analysis connections with `set_session(readonly=True)` or
`SET default_transaction_read_only = on` against the pooler URL — that causes
intermittent `ReadOnlySqlTransaction` failures on INSERT / `SELECT FOR UPDATE`
across web, webhooks, and workers.

Prefer, in order:

- the sanctioned helper — `from app.lib.ops_db import direct_db_connection`
  (fails closed if it can only resolve a pooler URL; autocommit direct endpoint,
  safe for `set_session(readonly=True)` and any session state), or
- a **direct** (non-pooler) Neon URL for one-off scripts that need session state, or
- transaction-scoped `BEGIN TRANSACTION READ ONLY` (does not contaminate the pool).

Defence in depth, but **not** a substitute for the above: the app clears
`default_transaction_read_only` on SQLAlchemy checkout
(`app/lib/db_engine_guards.py`) and treats `read-only transaction` as a
retryable transient. That guard is **best-effort** — under transaction pooling
the backend serving a later write may differ from the one cleaned at checkout,
so it cleans the pool gradually rather than guaranteeing any single write. The
hot paths (daily-send loop, scheduler phases, click tracking) self-heal on this
error (claim-release + catch-up / next-tick retry), so a contaminated window
degrades transiently rather than failing hard.

If Sentry shows a burst of `ReadOnlySqlTransaction` errors, detox the pool:

```bash
# From a machine with NEON_OWNER_DATABASE_URL (pooler or direct):
python3 - <<'PY'
import os, time, psycopg2
url = os.environ['NEON_OWNER_DATABASE_URL']
for _ in range(24):
    c = psycopg2.connect(url); c.autocommit = True
    cur = c.cursor()
    cur.execute('SET default_transaction_read_only TO off')
    cur.close(); c.close(); time.sleep(0.05)
print('detox done')
PY
```

## Automated backups

Render Cron `societyspeaks-db-backup` runs daily (`0 3 * * *` UTC):

```text
python3 scripts/backup_neon_to_s3.py
```

Writes `s3://$AWS_S3_BUCKET/db-backups/societyspeaks-YYYYMMDD….dump` and prunes older than 30 days.

Required env on the cron service (same as web): `DATABASE_URL`, `AWS_*`.

Manual run (local or Render one-off job):

```bash
export DATABASE_URL='…'   # Neon pooler or direct
export AWS_ACCESS_KEY_ID=…
export AWS_SECRET_ACCESS_KEY=…
export AWS_S3_BUCKET=societyspeaks-assets-uk
export AWS_REGION=eu-west-2
python3 scripts/backup_neon_to_s3.py
```

## Health check

```bash
export RENDER_HEALTH_URL='https://YOUR-SERVICE.onrender.com'
# optional S3 probe:
export AWS_ACCESS_KEY_ID=…
export AWS_SECRET_ACCESS_KEY=…
export AWS_S3_BUCKET=societyspeaks-assets-uk
python3 scripts/ops_health_check.py
```

## S3 bucket hardening (one-time)

```bash
python3 scripts/enable_s3_bucket_best_practice.py
```

Enables versioning + lifecycle (noncurrent 90d, `db-backups/` expiry 30d).  
May need a broader IAM policy than the app user (or run with console admin once).

## IAM policy for app + backups

App user should allow at least:

- `s3:ListBucket` on `arn:aws:s3:::BUCKET`
- `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on `arn:aws:s3:::BUCKET/*`

(Delete is used for backup prune and profile image deletes.)

## Pre-DNS / ongoing verification

See checklist in `RENDER_DEPLOY.md` §5. Confirm scheduler and consensus **logs**, not only “Deployed”.

## Cloudflare (DNS + edge)

Cloudflare Free fronts Render since 2026-07-11. Registration stays at
Namecheap; only nameservers moved (`dexter.ns.cloudflare.com`,
`venus.ns.cloudflare.com`). DNS source of truth: `societyspeaks.io.zone`
(BIND export) — update it whenever records change in the dashboard.

**Proxy status:** only the apex and `www` CNAMEs are proxied (orange).
Everything else — MX, SPF/DKIM/DMARC TXT, SES DKIM CNAMEs, `hello` — must
stay DNS-only (grey) or mail auth breaks.

**Apex must be a CNAME to `societyspeaks-web.onrender.com`, never an A
record.** Render fronts through Cloudflare too; our zone's WAF and cache
rules only run when orange-to-orange routing is triggered, and O2O only
triggers on a proxied CNAME (an A record to Render's IP hands traffic
straight to Render's zone, silently bypassing all our rules — found the
hard way on 2026-07-11).

**Settings that must hold:**

- SSL/TLS mode: **Full (Strict)** (Render serves a valid cert; anything
  weaker invites MITM between edge and origin).
- **Browser Cache TTL: Respect Existing Headers.** Do not force a global
  override (e.g. 4 hours) — origin `Cache-Control` / `s-maxage` is the source
  of truth for static and discovery files.
- **Bot Fight Mode: OFF.** It challenges the answer-engine bots our GEO
  strategy depends on (GPTBot, ClaudeBot, PerplexityBot). Blocking is done
  by one WAF custom rule instead.
- WAF custom rule `block-scraper-uas`: block requests whose User-Agent
  contains any of the robots.txt deny-list (Meta-ExternalAgent, Bytespider,
  AhrefsBot, SemrushBot, DataForSeoBot, PetalBot, MJ12bot, DotBot, BLEXBot).
  Keep this list in sync with `robots()` in `app/routes.py`.
- Cache rule `cache-discovery-files`: eligible for cache on
  `/robots.txt`, `/sitemap.xml`, `/llms.txt`, TTL "respect origin".
  Origin sends `s-maxage=86400` for robots/llms and `s-maxage=3600` for
  the sitemap (kept short so daily brief permalinks surface within the
  hour) — pinned by `tests/test_robots_policy.py`.
- Cache rule `cache-static-assets`: eligible for cache on
  `/assets/*`, `/images/*`, `/css/*`, `/js/*`, `/fonts/*`, `/icons/*`,
  `/logos/*`, `/data/*`, `/dist/*`, `/profiles/assets/*`,
  `/profiles/get-image/*`, `/favicon.ico`, `/favicon.png`, `/favicon.svg`;
  Edge TTL **Respect origin**; enable **Cache eligibility: Eligible for
  cache**. Origin sends `public, max-age=86400, s-maxage=604800` and strips
  `Vary: Cookie` / `Set-Cookie` on these paths (`app/lib/cdn_cache.py`) so
  the Free-plan CDN can actually HIT. Do **not** cache HTML (`/`,
  discussions, etc.) — sessions and CSRF require DYNAMIC HTML.
- After deploy of changed unversioned assets (hero image, `/js/*.js` without
  a cache-bust query), purge those URLs (or "Custom Purge" for `/assets/*`
  and `/js/*`) so edges do not serve stale bodies for up to `s-maxage`.

**Purge after out-of-band content changes** (dashboard: Caching → Purge, or):

```bash
curl -X POST "https://api.cloudflare.com/client/v4/zones/$CF_ZONE_ID/purge_cache" \
  -H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json" \
  --data '{"files":["https://societyspeaks.io/sitemap.xml"]}'
```

**Purge after OG card / share-image deploys** — the cards self-heal on their
edge TTL (`max-age=300` on discussions/brief/daily, `3600` on profiles), so a
purge is only for an *immediate* refresh after a redesign or an `OG_CACHE_VERSION`
bump. Prefix/tag purge is Enterprise-only, so use the all-plan methods:

```bash
export CF_API_TOKEN='…'   # Cloudflare API token with Cache Purge
export CF_ZONE_ID='…'

# After a font/layout change that affects every card:
python3 scripts/purge_og_cloudflare.py --everything

# Refresh just one or two cards:
python3 scripts/purge_og_cloudflare.py --files \
  "https://societyspeaks.io/discussions/9639/og.png"

python3 scripts/purge_og_cloudflare.py --everything --dry-run   # inspect payload
```

Verify a fresh card (redesigned cards are ~50–60 KB; the old broken one was ~10 KB):

```bash
curl -sI "https://societyspeaks.io/discussions/9639/og.png" | grep -i content-length
```

**Cache health check** (expect `cf-cache-status: HIT` on a second request):

```bash
curl -sI "https://societyspeaks.io/css/output.css" | grep -iE 'cf-cache-status|cache-control|vary'
curl -sI "https://societyspeaks.io/assets/images/hero-optimized.jpg" | grep -iE 'cf-cache-status|cache-control|vary'
```

Static responses must **not** include `Vary: Cookie`. HTML may stay
`cf-cache-status: DYNAMIC` — that is correct.

**Speed Observatory / Web Analytics:** a low overall cache hit ratio is
expected while HTML is DYNAMIC; judge CDN health by HIT rate on `/css/*`,
`/js/*`, and `/assets/*`, plus origin TTFB and 5xx — not the site-wide %.
Investigate Cloudflare 5xx spikes (522/524 = origin timeout) in Analytics
→ Traffic alongside Render logs; P99 LCP outliers usually track those.

**Escape hatch:** Render itself fronts through Cloudflare
(Cloudflare-on-Cloudflare is supported); if cert or redirect loops appear,
grey-cloud the affected record and the site serves direct from Render.

## Alerts (dashboard — cannot automate from git)

1. Render → account notifications → failed deploy emails  
2. UptimeRobot / Better Stack → ping production URL every 5 minutes  
3. AWS Billing → alarm if estimated charges > e.g. $50  
4. Neon → keep Launch PITR; retain an independent dump via the cron above  

## Redis session policy

Server-side sessions live in Redis Cloud (London, 250MB free tier). Storage
policy (`app/lib/session_policy.py`): authenticated sessions keep
`PERMANENT_SESSION_LIFETIME` (7 days in production); anonymous sessions get
`ANONYMOUS_SESSION_LIFETIME` (48h); crawler user agents store no session at
all. Without this, ~40k visitor/bot sessions a day at 7-day TTL filled the
instance and volatile-lru evicted logged-in users (July 2026 incident: 275k
keys, 17 of them authenticated).

If Redis memory climbs again:

```bash
export REDIS_URL='rediss://…'
python3 scripts/purge_anonymous_sessions.py            # dry run
python3 scripts/purge_anonymous_sessions.py --execute  # delete anonymous sessions
```

Deleting anonymous sessions logs nobody out (they hold only CSRF/UI state).

## Subscriber segment sync & staged activation

`scripts/import_subscriber_segments.py` syncs segment metadata
(chapter/function/country) onto `daily_brief_subscriber` from a CSV export.
Addresses not already subscribed land as `status='imported'` — segmented but
excluded from every send path, which all gate on `status='active'`. Existing
rows only ever receive metadata; the sync never touches
status/tier/preferences, so unsubscribed/bounced/paused subscribers are
structurally out of reach.

Activate in batches, watching deliverability between batches:

```bash
export DATABASE_URL='postgres://…'   # Neon owner URL
python3 scripts/activate_imported_subscribers.py --status --source <label>
python3 scripts/activate_imported_subscribers.py --batch 250 --source <label>           # dry run
python3 scripts/activate_imported_subscribers.py --batch 250 --source <label> --commit
```

`--status` prints yesterday’s London-day kill-switch (bounce / complaint /
open), how many never-sent actives are waiting for tonight, and remaining
imported. The script excludes UTC/unknown timezones by default
(`--include-utc` to override after a real IANA backfill). After `--commit`
they join the next local-18:00 Daily Brief wave — no separate welcome blast.
`--commit` refuses if ≥100 never-sent actives are already waiting (two
first-send batches must not share a night).

Ramp rules (deliverability failures are hard to recover from — ramp slowly):

1. No activation while any send pipeline change is unverified or a bounce
   spike is under observation. **Clean week** (required before the first
   batch): ≥7 consecutive Europe/London send-days with day-level bounce
   **comfortably under 2%** and complaints **<0.1%**, after E0 webhook
   reconnect (opens/delivers landing). A single day sitting on the 2% line
   does **not** start the clock.
2. **One batch of 250 per send-day**, only after a green morning
   kill-switch (bounce &lt;2%, complaints &lt;0.1%, existing-list opens not
   sagging). Do **not** step to 500 while first-send bounce on a new tranche
   is ~14% — two such batches in one night would push the domain near the
   2% line. Kill-switch: complaints >0.1% or bounces >2% → stop the ramp.
3. Dry-run by default; `--commit` applies. Only rows with
   `status='imported'` can ever be activated.
4. Prefer real IANA `timezone` on the batch before `--commit`. Import sets
   timezone for *new* rows from chapter/country; **activation does not**.
   UTC leftovers still receive 18:00 UTC. Check readiness with section 10a
   of `docs/analysis/sql/stance-loop-scoreboard.sql`.

### Deliverability monitoring (how to read the numbers)

- **Source of truth for kill-switch:** Neon `email_event` day totals for
  `email_category = 'daily_brief'`, bucketed by **Europe/London** date (so
  they match Resend dashboard "Yesterday"). Cross-check Resend after each
  send wave; they should agree within ~1–2%.
- **Canonical query:** `docs/analysis/sql/stance-loop-scoreboard.sql`
  (sections 1–2).
- **Day-level, not hourly.** Soft (Transient) bounces often arrive hours
  after send. Morning Resend charts can show 10%+ "RISK" bars when almost
  no mail was sent that hour — ignore those; use the day total.
- **Transient vs Permanent:** both count toward the >2% kill-switch.
  Permanent/hard bounces are worse for list hygiene (expect suppressions);
  a day of only Transient near 2% is yellow — watch the next day before
  declaring clean.
- **Opens exist only for mail sent after 2026-07-12** (webhook reconnect).
  Pre-12 Jul bounce/complaint history in Neon is incomplete.

**Status snapshot (2026-08-26):** Batches 1–3 of 250 committed. Batch 3
joins tonight’s wave — do not stack a fourth until after that send.
First-send bounce on new tranches is ~14–16% (dead B2B addresses; Permanent
→ `bounced`, Resend-suppressed → `suppressed`). Remaining actives then
bounce like the old list (~0.1–1%). Existing-list bounce on 25 Aug was
1.06% list-wide / 0.1% on the pre-ramp cohort; complaints 0; opens ~16%.
UTC/unknown leftovers (~867) held. 2,909 TZ-ready imported remain after
batch 3 (~12 more send-days). Do not run E5 win-back as part of this ramp.

## Daily brief send integrity

Sends are duplicate-proof at three layers: an atomic per-(subscriber, brief)
claim in the database (conditional UPDATE on `last_brief_id_sent` — exactly
one loop can win; failed sends release the claim for catch-up retry), a
stable Resend `Idempotency-Key` (`brief:{brief_id}:{subscriber_id}` — see
`app/lib/email_idempotency.py`), and the
hourly job's catch-up behaviour, which re-covers subscribers missed by a
mid-send restart. Deploys during the send window are therefore safe but
still ungraceful — they abort the in-flight loop and delay the tail to the
next hourly tick, so prefer deploying outside the active wave.

**Local-time delivery:** each subscriber's `timezone` + `preferred_send_hour`
(default 18) drives `next_send_at`. After the 2026-07 timezone backfill the
daily wave is follow-the-sun (UK evening → US East → US West), not a single
18:00 UTC spike. Expect day-over-day volume charts to stretch across UTC
midnight; each subscriber still gets at most one copy per brief (claims).

**Suppressions:** `email.suppressed` webhook events mark the subscriber
`status='suppressed'` automatically (Resend refuses these addresses — prior
hard bounces/complaints). They leave the active pool so every rate stays
honest. 801 backfilled on 2026-07-13 (791 from the imported cohort); pool
was **874** suppressed as of 2026-07-14 — expect a similar rate as dormant
batches activate.

**Bounce auto-remove:** Resend's bounce.type is `Permanent` / `Transient` /
`Undetermined` (not `hard`/`soft`). Permanent and `email.complained` leave
the active pool immediately (bounced / unsubscribed). Transient is allowed
twice, then `status='bounced'` on the third event so a greylist or full
mailbox is not banned on day one, but a sticky dead address is not mailed
forever. Sends only go to `status='active'`. The activation script cannot
flip bounced/suppressed/unsubscribed rows, and it skips addresses that
already have a hard bounce, complaint, or Resend suppression in
`email_event`. Discussion notifications and the weekly digest also skip
undeliverable addresses; password reset is unchanged.

## Resend webhook verification

The webhook endpoint is `https://societyspeaks.io/brief/webhooks/resend`
(CSRF-exempt; svix-signature authenticated; fails closed if
`RESEND_WEBHOOK_SECRET` is unset). It is the ONLY source of
delivered/opened/bounced/complained events — if it is down, deliverability
monitoring is blind and the activation ramp must stay frozen.

Verification checklist (run after any Resend or webhook change):

1. Resend dashboard → confirm the webhook lives in the **same team** as the
   API key that sends (the team's Emails tab must show real sends).
2. All 8 event types enabled; signing secret (including `whsec_` prefix)
   matches `RESEND_WEBHOOK_SECRET` in the Render secrets env group.
3. Send a test event from the dashboard → Render web logs show
   `Resend webhook received: …` (a 401 `Invalid webhook signature` means
   secret mismatch; silence means Resend isn't routing to this endpoint).
4. After the next real send: `SELECT event_type, count(*) FROM email_event
   WHERE created_at > now() - interval '1 hour' GROUP BY 1;` must include
   `delivered` rows within minutes.

Open tracking is a per-domain Resend setting (tracking subdomain
`link.brief.societyspeaks.io`, DNS-only CNAME). Click tracking stays OFF —
clicks are tracked first-party and webhook copies are dropped. Opens land
in `email_event` only for mail sent after the 2026-07-12 webhook reconnect.

After any Resend or webhook change, also spot-check that Resend dashboard
day totals ≈ Neon London-day totals from the scoreboard SQL (within a
couple of percent). Silence in Neon while Resend shows deliveries means
the webhook is blind — freeze the activation ramp.

## Email unsubscribe compliance (RFC 8058)

Every product that sends `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
must keep its unsubscribe route CSRF-exempt and return an empty `200` for
machine POSTs. Human clicks use GET → confirm page → POST (never unsubscribe
on GET — corporate scanners prefetch every link). Covered routes: Daily Brief,
Daily Question, paid Briefings, game reminders, journey reminders. A
regression test asserts all five are registered in `csrf._exempt_views`.

## Subscriber import runbook

Any bulk data import, in order:

1. Import with `scripts/import_subscriber_segments.py` (dry-run first) —
   never a hand-rolled INSERT; the script preserves status/preferences.
2. Duplicate check: totals vs `count(DISTINCT …)` on the affected tables.
3. `python3 scripts/check_schema_drift.py` before and after.
4. Only then consider activation (see "Subscriber segment sync & staged
   activation" above).

The July 2026 corruption came from a doubled import into tables that had no
primary keys to reject it — steps 2–3 exist so that can never be silent again.

## Schema drift check

The July 2026 incident: a doubled data import left eight tables (brief_run,
brief_recipient, brief_item, analytics_event, analytics_daily_aggregate,
admin_audit_event, audio_generation_job, alembic_version) with every row
physically duplicated and **no primary keys** — which also silently blocked
their foreign keys and unique constraints from ever being created. Symptoms:
ORM `StaleDataError`, `INSERT … ON CONFLICT` failing outright, doubled
analytics counts. Repaired in migrations `bes001`/`pk001`/`pk002`.

To catch model-vs-database drift early:

```bash
export DATABASE_URL='postgres://…'
python3 scripts/check_schema_drift.py
```

Exit 1 = HIGH-severity drift (missing PK/unique/FK/column/table in the DB) —
fix via a guarded migration, mirroring the pk001/pk002 pattern. Cosmetic
findings (extra DB indexes, unique-rule-as-index) are listed but non-fatal.
Run it after any incident touching the schema and before/after risky data
imports.

## Neon egress (public network transfer)

The August 2026 bill was $255.61, of which **$214.72 was public network
transfer** — 2,647 GB moved out of a 3 GB database. Compute was only $39.73
and storage ~$1. The cause was not crawler traffic: it was scheduled jobs
re-downloading TOASTed JSON embedding vectors in loops.

Three columns carry multi-KB JSON vectors and are therefore **`deferred()`**
in the models — `news_article.title_embedding` (~13 KB),
`trending_topic.topic_embedding` (~16 KB),
`polymarket_market.question_embedding` (~21 KB). Only load them with an
explicit `undefer()` where the maths actually needs them. Undeferring one by
default puts a vector on every query that touches the table; a discussion page
eager-loads its source articles, so this reaches public page renders too.

To re-diagnose, rank tables by TOAST blocks touched rather than by slow
queries — the expensive query here is fast and enormous, so it never appears
in a slow-query list:

```bash
psql "$NEON_OWNER_DATABASE_URL" -c "
select relname,
       pg_size_pretty((coalesce(toast_blks_read,0)+coalesce(toast_blks_hit,0))*8192::bigint)
         as toast_touched
from pg_statio_user_tables
order by coalesce(toast_blks_read,0)+coalesce(toast_blks_hit,0) desc limit 10;"
```

Counters reset when the Neon compute restarts — check the window first with
`select pg_postmaster_start_time()`. Note TOAST *blocks* overstate wire bytes
(8 KB page granularity, roughly 4x for these vectors); for actual egress,
measure the payload of a specific query:

```bash
psql "$NEON_OWNER_DATABASE_URL" -c "
select count(*), pg_size_pretty(sum(pg_column_size(m.*))::bigint)
from (<the query as the ORM issues it>) m;"
```

`pg_stat_statements` is installed (created 2026-09-02; already in
`shared_preload_libraries`). Stats reset when the Neon compute restarts
(currently since 2026-08-17). Rank by `rows` and
`shared_blks_hit+shared_blks_read`, not `total_exec_time`:

```bash
psql "$NEON_OWNER_DATABASE_URL" -c "
select calls, rows,
       round((shared_blks_hit+shared_blks_read)*8192/1024.0/1024.0, 1) as mb_touched,
       left(regexp_replace(query, E'\\\\s+', ' ', 'g'), 160) as q
from pg_stat_statements
order by shared_blks_hit+shared_blks_read desc
limit 20;"
```

The matcher must not record `market_match_attempted_at` when the candidate
pool is empty — that is a sync gap, not a negative match. Stamping would hide
topics for 24 hours after markets return.

Do **not** migrate the JSON embedding columns to `pgvector` as part of an
egress hotfix. `vector` 0.8.0 is available on this Neon project, but CI tests
run on SQLite (no `vector` type), the matcher still needs market metadata for
keyword fallback, and exact cosine over a 400-row pool is cheaper as a Python
matmul once the pool is loaded once. The follow-up is a dedicated migration:
`CREATE EXTENSION vector`, `vector(1536)` (or `halfvec`) columns, backfill,
then `ORDER BY embedding <=> :q` so similarity never downloads the pool.
Enabling the extension with no consumers is not that patch.

Known remaining offenders (from `pg_stat_statements`, window since
2026-08-17), *not* addressed by the loop/defer/url_hash fix:

- **`brief_item` N+1** — 2,957,803 calls returning 11.1 rows each (~1.8 KB/row,
  ~3.6 GB/day, ~4% of the bill). `DailyBrief.items` is `lazy='dynamic'`, so
  every access re-queries; brief email sends appear to re-read the item list
  per recipient. Fix by loading the items once per send, not per recipient.
- **Statement listing burns buffers, not bytes** — 1,667 calls returning 20
  rows each but touching 423 GB of buffers (~254 MB per call). That is compute,
  not egress: it belongs to the always-on CU line, not the transfer line.

Do **not** buy Scale-plan private networking to make this cheaper ($0.01/GB
instead of $0.10/GB) — at TB scale that is still paying for a bug.

## Dependency pinning policy

Every runtime dependency in `requirements.txt` carries an upper bound at the
major version production currently runs (0.x packages bound at the next
minor). Render rebuilds the image from scratch on every deploy, so an
unbounded `>=` floor silently installs whatever PyPI serves that day — that
is how stripe v15 replaced v12 during the Replit→Render migration and broke
every Stripe webhook until 2026-07-12.

Upgrading a dependency is a deliberate act: raise the bound in its own
commit, run the full suite, deploy, watch Sentry. Never widen a bound as a
side effect of other work.

Dependabot (`.github/dependabot.yml`) opens grouped minor/patch PRs weekly
for pip + npm, and monthly for Actions/Docker. Pip uses
`versioning-strategy: increase-if-necessary` so ranged pins do not spawn
noise PRs that only raise the floor. Exact `==` pins are bumped in the
`python-minor-patch` group. Docker Python majors and Tailwind CSS majors
are ignored — those are deliberate platform/CSS migrations, not drive-bys.
Stripe / redis-py / Flask-Limiter majors are ignored for the same reason
(documented breakages or exact pins); cachelib 0.10+ is ignored as a 0.x
minor because 0.16 changes `FileSystemCache` hashing. `increase-if-necessary`
also opens a PR the moment a version exists **outside** a safety ceiling
(setuptools 84, posthog ≥7.37.6, openai 3, anthropic 1, greenlet 4) — those
are ignored as version updates so they cannot starve the weekly 5-PR slot.
PostHog also has `versions: [">=7.37.6"]` and is excluded from the
python-minor-patch group: `update-types` alone still opened a patch widen
to `<7.37.7` (PR #39), which admits the gevent-incompatible `_DrainSignal`.
A GHSA that only exists past 7.37.6 will not get a Dependabot PR — pip-audit
is the backstop; raise that ceiling only with a gevent review. Other ignored
packages still get security PRs (`update-types` only).

When an in-major bump pulls a **new unbounded transitive** (flask-limiter
3.12 → `limits>=3.13`; redis-py 5.3 → `PyJWT>=2.9`; flask-session →
`msgspec>=0.18.6`; gevent → `greenlet>=3.2.2`), add an explicit
upper-bounded pin in the same change so the next image rebuild cannot
jump a major the suite never reviewed.

Source of truth for Python deps is `requirements.txt` only (no Poetry lock).

Exception: when a GHSA shows the current floor still admits a vulnerable
release, raise that floor (or add an explicit transitive pin) in its own
commit so fresh installs cannot resolve the bad version. That is not
Dependabot noise — it is the security control the upper-bound policy
expects alongside `pip-audit` in `.github/workflows/security.yml`.

Special case — `cryptography` / `atproto`: atproto still declares
`cryptography<47` (upstream [MarshalX/atproto#688](https://github.com/MarshalX/atproto/issues/688)),
while current advisories need `cryptography>=50.0.0` (PKCS#7 oracle
GHSA-g6cj-pr64-35w5; earlier OpenSSL fix was `>=48.0.1`). Keep the
`<47` pin in `requirements.txt` so a plain resolve succeeds, then
force-reinstall the patched wheel via **`scripts/install_python_deps.sh` only**
(Dockerfile, Tests, Security audit, and local/setup scripts all call it — do
not duplicate the override pin). Security CI also asserts
`cryptography>=50.0.0` before `pip-audit`. Dependabot ignores the
`requirements.txt` cryptography pin so it does not reopen weekly
“raise the ceiling to <51” PRs that cannot resolve alongside atproto.
Do not “fix” the audit by ignoring the GHSA; drop the force-reinstall
once atproto allows `cryptography>=50`.

Special case — `setuptools` / PYSEC-2026-3447: the `python:3.11-slim` image
ships setuptools 79.x. GHSA-h35f-9h28-mq5c (MANIFEST.in NFC/NFD exclusion
bypass on macOS APFS when building sdists) is fixed in **83.0.0**. Pin
`setuptools>=83.0.0,<84` in `requirements.txt` and upgrade that same
specifier in `scripts/install_python_deps.sh` *before* `pip install -r` so
sdist builds during the resolve use the patched FileList. Stay on 83.x —
setuptools 84 is a distutils/compiler major, not a drive-by. Do not
`--ignore-vuln PYSEC-2026-3447`. Security CI asserts the installed version
and `pip-audit`s the env.

Special case — `nanoid` / GHSA-2v37-7h3g-55p8: Tailwind 3 / postcss 8 depend
on nanoid **3.x**. The infinite-loop fix for `customAlphabet(size=0)` is
**3.3.18** on that line (5.1.6 / 6.x are ESM majors and would break the CSS
build). Pin it with an npm `overrides` entry, keep Dependabot from opening
nanoid major PRs, and let Security CI `npm audit --audit-level=high`.

## Billing webhook Sentry alert

Stripe webhooks hit `POST /billing/webhook`. A silent 5xx here means missed
renewals, failed cancellations, and stuck subscriptions — page someone.

Create (or verify) this alert in Sentry:

1. Sentry → Alerts → Create Alert → **Issues** (or Metric if you prefer
   transaction volume).
2. Filter: `transaction:"/billing/webhook"` **or**
   `http.url:*\/billing\/webhook*` and status `5xx` /
   `status_code:[500 TO 599]`.
3. Threshold: **any** matching event (count ≥ 1) in 5 minutes.
4. Action: email/Slack the on-call owner (William).
5. Environment: `production` only.

If you use Metric Alerts instead of Issue Alerts, set dataset to Transactions,
query `transaction:/billing/webhook http.status_code:>=500`, critical at ≥1.

## Secrets hygiene

- Never commit `.env`, dumps, or access keys
- Rotate Neon password if it was shared in chat
- Production secrets live only in Render (and password manager)
- `DEPLOYED_PRODUCTION=1` enables real email/social sends — never set it on a second live host while another is still sending
- Replit is decommissioned (shut down 2026-07-11) — Render is the only live host; if any Replit-era secrets are still valid anywhere, rotate them
