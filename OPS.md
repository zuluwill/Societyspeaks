# Production operations — Society Speaks
#
# Stack: Render (Frankfurt) + Neon (London) + S3 (London) + Upstash
# Deploy: push to GitHub `main` → Render Blueprint auto-deploy
# Detail: RENDER_DEPLOY.md

## Daily deploy

```bash
git push origin main
```

Render rebuilds web + scheduler + consensus worker. Web runs `flask db upgrade` pre-deploy.

After env-only changes: Render → service → **Manual Deploy**.

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

## Secrets hygiene

- Never commit `.env`, dumps, or access keys  
- Rotate Neon password if it was shared in chat  
- Remove temporary AWS keys from Replit Secrets after migrations  
- Production secrets live only in Render (and password manager)
