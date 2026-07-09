# Render Deployment Checklist

Production stack (July 2026):

| Piece | Provider / region |
|---|---|
| App (web) | Render Frankfurt — `societyspeaks-web` |
| Scheduler | Render Frankfurt — `societyspeaks-scheduler` |
| Consensus worker | Render Frankfurt — `societyspeaks-consensus-worker` |
| DB backup cron | Render Frankfurt — `societyspeaks-db-backup` (daily 03:00 UTC → S3) |
| Postgres | Neon London (`aws-eu-west-2`) |
| Redis | Redis Cloud, London (`REDIS_URL`) |
| Object storage | AWS S3 London (`eu-west-2`) — bucket e.g. `societyspeaks-assets-uk` |
| Source of truth | GitHub `main` → Render auto-deploy |

Day-to-day ops (deploy, backups, health, alerts): [OPS.md](./OPS.md).

Residency Q&A line (honest): **Primary data store and object storage: UK (London). Application processing: EEA (Frankfurt).**

---

## Prerequisites

- [ ] Neon project in **London**; you own the account; pooler `DATABASE_URL` with `sslmode=require`
- [ ] Redis Cloud (or other) Redis; copy the `rediss://` URL
- [ ] S3 bucket in **`eu-west-2`** + IAM user with least-privilege access to that bucket only
- [ ] GitHub repo connected to Render
- [ ] Secrets copied from the previous host (Replit) — **except** `DATABASE_URL` (use Neon) and storage (use AWS_*)

---

## 1. Create services from Blueprint

In the Render dashboard → **+ New → Blueprint** → point at this repo / branch `main`.  
Render reads `render.yaml` and creates three services + config env group:

| Service | Type | Plan |
|---|---|---|
| `societyspeaks-web` | Web | Standard |
| `societyspeaks-scheduler` | Background Worker | Standard |
| `societyspeaks-consensus-worker` | Background Worker | Standard |

**Render quirk:** `sync: false` inside an `envVarGroup` is ignored. Put secrets on each service (or edit a linked group after create). See §2.

---

## 2. Environment variables

### Required on all three services

| Variable | Source |
|---|---|
| `DATABASE_URL` | Neon London **pooler** URL (`?sslmode=require`). Not Helium. |
| `REDIS_URL` | Redis Cloud |
| `SECRET_KEY` | Copy from previous production (changing logs everyone out) |
| `ENCRYPTION_KEY` | Copy from previous production |
| `AWS_ACCESS_KEY_ID` | IAM user for the assets bucket |
| `AWS_SECRET_ACCESS_KEY` | IAM secret |
| `AWS_S3_BUCKET` | e.g. `societyspeaks-assets-uk` |
| `AWS_REGION` | `eu-west-2` |

`NEON_DATABASE_URL` is an optional fallback if `DATABASE_URL` is blank; prefer a filled `DATABASE_URL`.

### Required for mail / AI / billing (web + scheduler at minimum)

| Variable | Source |
|---|---|
| `RESEND_API_KEY` | Resend |
| `RESEND_WEBHOOK_SECRET` | Resend |
| `ANTHROPIC_API_KEY` | Anthropic |
| `OPENAI_API_KEY` | OpenAI |
| `STRIPE_SECRET_KEY` | Stripe |
| `STRIPE_PUBLISHABLE_KEY` | Stripe |
| `STRIPE_WEBHOOK_SECRET` | Stripe |

### Optional

| Variable | Notes |
|---|---|
| `SENTRY_DSN` | Errors |
| `SENTRY_ENVIRONMENT` | Set to `production` in `societyspeaks-config` (do not use `prod`) |
| `POSTHOG_API_KEY` | Analytics |
| `GUARDIAN_API_KEY` | News ingestion |
| `PARTNER_KEY_SECRET` / partner Stripe price IDs | Partner embeds |

Non-secret config (`APP_BASE_URL`, from-addresses, Stripe price IDs, etc.) lives in Blueprint group `societyspeaks-config`.

**Production sends:** `DEPLOYED_PRODUCTION=1` is set in that group. Email/social/scheduler jobs use this flag (not `FLASK_ENV`). Keep Replit **paused** (or off) while it is set on Render so you never run two senders.

---

## 3. Object storage migration (from Replit)

Repo statics:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_S3_BUCKET=societyspeaks-assets-uk
export AWS_REGION=eu-west-2
python3 scripts/upload_static_assets.py
```

User uploads / audio / evidence / exports (run **inside Replit** while Object Storage is still available):

```bash
python3 scripts/migrate_object_storage_to_s3.py --dry-run
python3 scripts/migrate_object_storage_to_s3.py
```

Remove temporary AWS secrets from Replit after a successful run. Do **not** delete Replit Object Storage until Render has served images correctly for a while.

---

## 4. Deploy

- Push to `main` or **Manual Deploy** on each service
- Web runs `flask db upgrade` as `preDeployCommand`
- Healthy web logs end with gunicorn listening on `0.0.0.0:5000`

---

## 5. Verify before DNS (do not skip)

“Deployed” in the Render UI is **not** enough. Check logs and behaviour.

### Web (`societyspeaks-web`)

- [ ] `GET /` returns 200 on the `.onrender.com` URL
- [ ] Login works
- [ ] Hero / static image loads (S3 or filesystem fallback)
- [ ] Known profile image: `/get-image/<filename>` returns an image
- [ ] A discussion page loads; voting works (needs Redis)

### Scheduler (`societyspeaks-scheduler`)

- [ ] Logs show process start with `APP_ROLE=scheduler` (not crash-looping)
- [ ] Logs show the scheduler cycle / jobs registering (not only “Deployed”)
- [ ] No repeated `DATABASE_URL` / Redis / import tracebacks
- [ ] No recurring “Application exited early” emails outside deploys — the process stays up (`SCHEDULER_MAX_RUNTIME_SECONDS=0` on Render; do not re-enable timed self-exit unless you accept those alerts)

### Consensus worker (`societyspeaks-consensus-worker`)

- [ ] Logs show worker start / queue polling
- [ ] Triggering consensus on a discussion (or waiting for a queued job) completes without worker crash

### Ops

- [ ] AWS secrets removed from Replit Secrets (still present on Render)
- [ ] Neon password rotated if it was ever pasted into chat
- [ ] `societyspeaks-db-backup` cron present; `DATABASE_URL` + `AWS_*` set on it
- [ ] One-time: `python3 scripts/enable_s3_bucket_best_practice.py` (versioning + lifecycle)
- [ ] Uptime monitor pointed at the Render URL (then at the domain after cutover)
- [ ] Render failed-deploy notifications enabled
- [ ] AWS billing alarm set (optional but recommended)
- [ ] `python3 scripts/ops_health_check.py` with `RENDER_HEALTH_URL` passes

---

## 6. DNS cutover

**Do this now that Replit is paused** — the public domain is otherwise down until DNS points at Render.

1. Render → **`societyspeaks-web`** → **Settings** → **Custom Domains**
2. Add `societyspeaks.io` and `www.societyspeaks.io` (if you use www)
3. At your DNS host, apply the records Render shows (usually CNAME / A / ALIAS)
4. Wait until Render shows the domain **Verified** with TLS
5. Confirm `https://societyspeaks.io` serves Render (homepage, login, images)
6. Keep Replit **Paused** as rollback for a few days; only **Shut down** later
7. Stripe/Resend webhooks that use `societyspeaks.io` keep working; update only if they pointed at a Replit-only hostname

### After DNS

- [ ] Uptime monitor → `https://societyspeaks.io`
- [ ] Remove temporary AWS keys from Replit Secrets (if still present)
- [ ] Rotate Neon password if it was ever pasted into chat
- [ ] Confirm scheduler logs show jobs running (with `DEPLOYED_PRODUCTION=1`)
- [ ] Confirm one successful `societyspeaks-db-backup` run (or trigger manually)

---

## Notes

- **Port:** Gunicorn binds to `5000`; `PORT=5000` is set in `render.yaml`.
- **Docker workers:** use `dockerCommand` (Render rejects `startCommand` for `runtime: docker`).
- **Scheduler:** keep a **single** scheduler instance (`DISABLE_SCHEDULER=1` on web).
- **APScheduler:** do not scale web to multiple instances with in-process scheduler enabled.
- **Object storage:** `app/storage_utils.py` provider order is S3 → Replit → local static fallback.
- **`replit` package:** may remain in `requirements.txt`; unused outside Replit.
- **Cost:** three Standard Render services ≈ $75/mo plus Neon Launch + S3 + Redis Cloud.
