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

## Secrets hygiene

- Never commit `.env`, dumps, or access keys
- Rotate Neon password if it was shared in chat
- Remove temporary AWS keys from Replit Secrets after migrations
- Production secrets live only in Render (and password manager)
- `DEPLOYED_PRODUCTION=1` enables real email/social sends — never set it on a second live host while another is still sending
- Keep Replit paused (not running) while Render owns production sends
