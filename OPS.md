# Production operations — Society Speaks
#
# Stack: Render (Frankfurt) + Neon (London) + S3 (London) + Redis Cloud (London)
# Deploy: push to GitHub `main` → Render Blueprint auto-deploy
# Detail: RENDER_DEPLOY.md

## Daily deploy

```bash
git push origin main
```

Render rebuilds web + scheduler + consensus worker. Web runs `flask db upgrade` pre-deploy.

**Auto-deploy on `main` is intentional** for a solo production app. Prefer `autoDeployTrigger: checksPass` later if CI is green and you want fewer bad deploys — not `off` unless you want manual releases.

Web health checks use **`/health`** (not `/`). That endpoint is built for deploy liveness and avoids homepage DB/Redis warmup flakes that caused “connection refused” emails.

After env-only changes: Render → service → **Manual Deploy**.

**Scheduler “Application exited early” emails:** expected on deploys (SIGTERM). Recurring every ~30 minutes meant the old Replit timed self-exit was still on — Render uses `SCHEDULER_MAX_RUNTIME_SECONDS=0` so the process stays up. Watch Metrics RSS; only re-enable a timed recycle if memory grows without bound.

**Worker restart emails** (scheduler / consensus) on every push are normal — those services restart with the new image. Keep Render notifications on **failure-only**. After `/health` is the web check path, web “connection refused” during deploy should largely stop; if it continues after the new instance is live, investigate.

## Neon pooler — never session READ ONLY

Production `DATABASE_URL` is the Neon **`-pooler`** endpoint (PgBouncer transaction mode). Session settings stick on the backend and are reused by the next client.

**Do not** open ops/analysis connections with `set_session(readonly=True)` or
`SET default_transaction_read_only = on` against the pooler URL — that causes
intermittent `ReadOnlySqlTransaction` failures on INSERT / `SELECT FOR UPDATE`
across web, webhooks, and workers.

Prefer:

- a **direct** (non-pooler) Neon URL for one-off scripts that need session state, or
- transaction-scoped `BEGIN TRANSACTION READ ONLY` (does not contaminate the pool).

The app clears `default_transaction_read_only` on every SQLAlchemy checkout
(`app/lib/db_engine_guards.py`) and treats `read-only transaction` as a
retryable transient error.

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
python3 scripts/activate_imported_subscribers.py --batch 250 --source <label>           # dry run
python3 scripts/activate_imported_subscribers.py --batch 250 --source <label> --commit
```

Ramp rules (deliverability failures are hard to recover from — ramp slowly):

1. No activation while any send pipeline change is unverified or a bounce
   spike is under observation. **Clean week** (required before the first
   batch): ≥7 consecutive Europe/London send-days with day-level bounce
   **comfortably under 2%** and complaints **<0.1%**, after E0 webhook
   reconnect (opens/delivers landing). A single day sitting on the 2% line
   does **not** start the clock.
2. Batches of 250–500; after each batch, check bounce + complaint rates in
   `email_event` for the following two sends before the next batch.
   Kill-switch: complaints >0.1% or bounces >2% → stop the ramp.
3. Both dry-run by default; `--commit` applies. Only rows with
   `status='imported'` can ever be activated.
4. Prefer real IANA `timezone` on the batch before `--commit`. Import sets
   timezone for *new* rows from chapter/country; **activation does not**.
   UTC leftovers still receive 18:00 UTC. Check readiness with section 7 of
   `docs/analysis/sql/stance-loop-scoreboard.sql`.

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

**Status snapshot (2026-07-14):** webhook + opens live since 12 Jul;
complaints 0; 13 Jul bounce ~1.96% Neon / 2.11% Resend (all Transient) —
on the fence, clean week **not** started. 4,526 still `imported`.

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
Source of truth for Python deps is `requirements.txt` only (no Poetry lock).

Exception: when a GHSA shows the current floor still admits a vulnerable
release, raise that floor (or add an explicit transitive pin) in its own
commit so fresh installs cannot resolve the bad version. That is not
Dependabot noise — it is the security control the upper-bound policy
expects alongside `pip-audit` in `.github/workflows/security.yml`.

Special case — `cryptography` / `atproto`: atproto still declares
`cryptography<47` (upstream [MarshalX/atproto#688](https://github.com/MarshalX/atproto/issues/688)),
while GHSA-537c-gmf6-5ccf is fixed only in `cryptography>=48.0.1`. Keep the
`<47` pin in `requirements.txt` so a plain resolve succeeds, then
force-reinstall the patched wheel via **`scripts/install_python_deps.sh` only**
(Dockerfile, Tests, Security audit, and local/setup scripts all call it — do
not duplicate the override pin). Security CI also asserts
`cryptography>=48.0.1` before `pip-audit`. Do not “fix” the audit by
ignoring the GHSA; drop the force-reinstall once atproto relaxes its upper
bound.

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
