# Render Deployment Checklist

## Prerequisites

- [ ] New Neon account created — copy the **connection string** (pooler endpoint, `?sslmode=require`)
- [ ] Redis provisioned — [Upstash](https://upstash.com) (free tier, EU region) recommended; copy the `rediss://` URL
- [ ] GitHub repo connected to Render (or use Render's Git deploy)

---

## 1. Create services from Blueprint

In the Render dashboard → **Blueprints** → **New Blueprint Instance** → point at this repo.  
Render reads `render.yaml` and creates three services automatically:

| Service | Type | Plan |
|---|---|---|
| `societyspeaks-web` | Web | Standard |
| `societyspeaks-scheduler` | Background Worker | Standard |
| `societyspeaks-consensus-worker` | Background Worker | Standard |

---

## 2. Set secret environment variables

Go to each service → **Environment** tab and fill in the `sync: false` vars.  
All three services share the `societyspeaks-secrets` group — set once, Render propagates.

### Required (all services)
| Variable | Where to get it |
|---|---|
| `DATABASE_URL` | Neon dashboard → Connection string (pooler) |
| `REDIS_URL` | Upstash dashboard → Connection URL |
| `SECRET_KEY` | Generate: `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | Same as above (must be 32 bytes hex) |

### Required (web + scheduler)
| Variable | Where to get it |
|---|---|
| `RESEND_API_KEY` | Resend dashboard |
| `ANTHROPIC_API_KEY` | Anthropic console |
| `OPENAI_API_KEY` | OpenAI platform |
| `STRIPE_SECRET_KEY` | Stripe dashboard |
| `STRIPE_PUBLISHABLE_KEY` | Stripe dashboard |
| `STRIPE_WEBHOOK_SECRET` | Stripe → Webhooks → signing secret |

### Optional but recommended
| Variable | Notes |
|---|---|
| `SENTRY_DSN` | Error tracking |
| `POSTHOG_API_KEY` | Analytics |
| `GUARDIAN_API_KEY` | News ingestion |

---

## 3. Trigger first deploy

- Push to `main` (or click **Manual Deploy** in the dashboard)
- The **web service** runs `flask db upgrade` as a pre-deploy command before going live
- Watch logs — a healthy first deploy ends with `Listening at: http://0.0.0.0:5000`

---

## 4. Verify

- [ ] `GET /` returns 200
- [ ] Admin login works
- [ ] Scheduler logs show jobs starting (check `societyspeaks-scheduler` logs)
- [ ] Consensus worker logs show it polling the queue

---

## 5. DNS cutover

Update `societyspeaks.io` DNS → Render's provided hostname (shown in the web service dashboard).  
Render provisions TLS automatically via Let's Encrypt.

---

## 6. Data migration (if needed)

If you need to restore data from the Neon backup into the new Neon account:

```bash
# Export from old account
pg_dump "OLD_NEON_CONNECTION_STRING" --no-owner --no-acl -Fc -f backup.dump

# Restore to new account
pg_restore -d "NEW_NEON_CONNECTION_STRING" --no-owner --no-acl backup.dump
```

Alternatively, use Neon's built-in branch restore if both are on the same organisation.

---

## Notes

- **Port:** Gunicorn binds to `5000`; `PORT=5000` is set in `render.yaml` so Render routes correctly.
- **Docker workers:** Background services override the image `CMD` with `dockerCommand` (Render rejects `startCommand` for `runtime: docker`).
- **Scheduler:** Only one `societyspeaks-scheduler` instance should run. The scheduler uses a Redis lock internally, so running a second instance is safe but wasteful.
- **Replit Object Storage:** Any features using `replit.object_storage` will not work on Render. Replace with S3-compatible storage (Cloudflare R2, AWS S3) when ready.
- **`replit` package:** The `replit` Python package in `requirements.txt` installs fine on Render and is safe to leave. Its APIs simply return errors if Replit env vars are absent.
