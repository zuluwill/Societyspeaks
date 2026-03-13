# Society Speaks Platform

## Overview
Society Speaks is an AGPL-3.0 licensed public discussion platform built with Flask and PostgreSQL. It aims to facilitate structured dialogue, build consensus on social, political, and community topics, and inform policy. Key capabilities include user profiles, discussion management, geographic filtering, a "News-to-Deliberation Compiler" for trending news, a "Daily Civic Question" for engagement, sophisticated consensus clustering, and a customizable briefing system with a template marketplace. The platform's vision is to foster nuanced debate and enhance civic engagement by leveraging Pol.is technology.

## User Preferences
Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform prioritizes a consistent, mobile-first UI with reusable components and enhanced accessibility (ARIA labels), using Tailwind CSS for styling. It features `discussion_card` components, toast notifications, empty states, and loading spinners. The homepage emphasizes a "sense-making system" by highlighting "Today's Question" and "From the News."

### Open Access Model
Society Speaks employs a "reading is open, delivery is opt-in" model. This includes a daily brief with full content viewable without login, a news dashboard showing all sources and political balance, and email capture components for subscription. A cross-sell strategy is implemented to upsell free users to custom brief options.

### Technical Implementations
The backend is built with Flask, utilizing a modular, blueprint-based architecture, SQLAlchemy for PostgreSQL, Flask-Login for authentication, and Redis for session management and caching. The "News-to-Deliberation Compiler" uses LLMs to identify trending news, score articles, cluster them into discussions, and generate balanced seed statements via hourly background jobs. The "Daily Civic Question" promotes participation with voting, streaks, and one-click email voting. AI automatically detects geographic scope and categories in articles and daily questions. A community moderation system allows flagging of inappropriate content. AI is used for "Lens Check Optimization" and enhanced comment UX. A single-source-to-discussion pipeline automatically creates discussions from various content types. A political leaning system categorizes sources based on AllSides.com data. A multi-tenant briefing system enables customizable, branded briefings with AI settings, source management, and output enhancements. The content selection algorithm uses global scoring based on topic preferences, keyword matches, and source priority, followed by fair source distribution.

### Unified Ingestion Architecture
A unified content ingestion system uses `InputSource` (tracking provenance, domain, channel permissions) and `IngestedItem` models. An `ItemFeedService` provides filtered access to content, ensuring editorial control and source credibility scoring (using `is_verified` and `political_leaning` data) for different features like the Daily Brief and user briefings.

### Feature Specifications
The platform integrates Pol.is for discussion dynamics, supports topic categorization, and geographic filtering. A dedicated News feed page displays trending discussions with source transparency. Security is handled by Flask-Talisman (CSP), Flask-Limiter (rate limiting), Flask-SeaSurf (CSRF protection), and Werkzeug for password hashing. Replit Object Storage manages user-uploaded images. The platform supports dual individual and company profiles. Daily question emails include one-click voting with privacy-controlled comment sharing. Source pages provide metadata and "Engagement Scores." A political diversity system monitors and balances political leanings across content.

### CSP Compliance (March 2026)
The CSP `unsafe-inline` directive was removed (commit `3d32026`, March 11, 2026), requiring all inline `onclick`/`onchange`/`onsubmit` HTML event handlers to be migrated. The following patterns are now used across all 40+ templates:

1. **`data-confirm="message"` pattern**: Global capture-phase handlers in `layout.html` intercept form submit and button click events. Replaces all `onsubmit="return confirm(...)"` and `onclick="return confirm(...)"` patterns.

2. **`class="auto-submit-select"` pattern**: Global `change` delegation in `layout.html` submits the nearest `<form>` when a select with this class changes. Replaces `onchange="this.form.submit()"`.

3. **`data-*` attribute delegation**: Complex handlers (e.g., crop modal, image upload, subscriber actions, pricing tabs) use data attributes (`data-open-crop`, `data-close-crop`, `data-apply-crop`, `data-trigger-id`, `data-copy-text`, `data-action`, etc.) with delegated listeners in nonce-protected `<script>` blocks or external `.js` files.

4. **Direct `addEventListener` calls**: When elements have IDs, listeners are attached directly in nonce-protected script blocks instead of using inline attributes.

5. **Template literal HTML**: Dynamically injected HTML (via `innerHTML`) must also avoid inline handlers — use classes for delegation instead.

External `.js` files (e.g., `image-upload.js`) do NOT require nonces — only inline `<script>` blocks do.

### Deployment Architecture
The application runs as a Replit Reserved VM deployment with two processes started by a single bash run command:

**Process 1 — Web (gunicorn):** `APP_ROLE=web gunicorn --bind=0.0.0.0:5000 --reuse-port --timeout=600 --workers=4 run:app`
Sets `DISABLE_SCHEDULER=1` via the bootstrap in `create_app()`. All 4 gunicorn workers handle HTTP only — none attempt to start APScheduler.

**Process 2 — Scheduler:** `APP_ROLE=scheduler python3 scripts/run_scheduler.py`
Sets `REPLIT_DEPLOYMENT=1` via the bootstrap, starts Flask app context + APScheduler supervisor thread, then parks in a sleep loop. No HTTP serving. Acquires the Redis lock and runs all background jobs.

**Process 3 — Consensus Worker (separate workflow):** `APP_ROLE=worker python3 scripts/run_consensus_worker.py`
Sets `DISABLE_SCHEDULER=1` and `CONSENSUS_WORKER_PROCESS=1`. Polls the consensus job queue and runs heavy sklearn clustering without blocking HTTP or scheduler threads.

The full bash run command for the deployment is:
`bash -c "(while true; do APP_ROLE=scheduler python3 scripts/run_scheduler.py; echo 'Scheduler exited, restarting in 5s...'; sleep 5; done) & SCHED_PID=$!; APP_ROLE=web gunicorn run:app & WEB_PID=$!; trap 'kill $SCHED_PID $WEB_PID 2>/dev/null' INT TERM; wait $WEB_PID; EXIT_CODE=$?; kill $SCHED_PID 2>/dev/null; wait; exit $EXIT_CODE"`

The scheduler runs inside a `while true` restart loop so any crash (including SIGBUS from memory exhaustion) auto-restarts the scheduler without killing the web server. `wait $WEB_PID` (not `wait -n`) means only a gunicorn exit triggers a full deployment restart. The scheduler process itself has a 1-hour max-runtime cap (`_MAX_RUNTIME_SECONDS = 3600` in `scripts/run_scheduler.py`) — it exits cleanly at the hour mark so the restart loop gives it a fresh memory slate, preventing the ~45-minute Bus-error cycle seen in production before this fix.

**Scheduler memory hardening** (applied to prevent the SIGBUS crash):
- `BackgroundScheduler` is initialised with an explicit `APSThreadPoolExecutor(8)` (was default 10) — capping the number of concurrent Flask/SQLAlchemy app contexts alive at once.
- `process_pending_ingestion_jobs(max_jobs=10)` (was 30) — limits peak transient memory from concurrent HTTP/RSS fetches that fire every 5 s.
- `rollup_analytics_daily(days_back=14)` (was 21) — reduces the analytics query window and the size of the in-memory result set materialised every 15 min.
- `scripts/run_scheduler.py` calls `gc.collect()` every 30 seconds (every 6 sleep ticks), followed immediately by `ctypes.CDLL("libc.so.6").malloc_trim(0)` to return freed glibc heap arenas back to the OS — `gc.collect()` alone does not reduce RSS. Also logs RSS via `resource.getrusage()` every 5 minutes.
- Sub-minute polling intervals were raised after the first production deployment showed the scheduler crashing at ~15 min (faster than the pre-fix ~45 min), caused by too many Flask app contexts being created per minute under real production load: `process_brief_generation_queue` 3 s → 10 s; `check_emergency_brief_generate` and `process_source_ingestion_queue` 5 s → 15 s. Max user-visible latency for triggered actions increased from 3-5 s to 10-15 s.

**APP_ROLE bootstrap** (in `create_app()` top, `app/__init__.py`): Maps role to low-level flags via `os.environ.setdefault`. All three roles (web, scheduler, worker) are covered and enforced by contract tests in `tests/test_consensus_job_queue_contract.py` (13 tests).

**Scheduler lock**: Redis SETNX (`scheduler_lock` key), 120s TTL, heartbeat every 20s to `scheduler:last_heartbeat_at`. In the role-separated architecture, only the dedicated scheduler process contests the lock. Non-scheduler workers never attempt to acquire it.

**Monitoring endpoints**: `/health` returns scheduler lock status from Redis. `/metrics` returns P50/P75/P95/P99 request latency from a rolling Redis sample window (last 2000 sampled requests at 10% sampling rate), stored at `web:latency:samples`.

Werkzeug ProxyFix middleware (`x_for=1, x_proto=1, x_host=1`) is applied so `request.remote_addr` reflects the real client IP behind Replit's reverse proxy — critical for per-user rate limiting. Production detection relies on the `REPLIT_DEPLOYMENT=1` environment variable. Three-layer email deduplication: (1) Redis scheduler lock, (2) Redis per-hour send lock, (3) DB-level `last_brief_id_sent` idempotency guard. Magic tokens are stable across sends (only regenerated when expired/missing, with 168h TTL) to prevent "View in Browser" link invalidation. Brief generation is hardened with four layers: (1) `generate_daily_brief` and `generate_weekly_brief` use `misfire_grace_time=21600` (6 hours); (2) a startup-time recovery thread fires within 10 seconds of production scheduler initialization if it's 17:00–22:00 UTC and no brief exists — this directly covers the deployment-at-17:00 failure mode; (3) `daily_brief_safety_net` cron at 19:30 UTC with 6-hour misfire grace + self-healing pipeline fallback; (4) `daily_brief_safety_net_2` cron at 21:30 UTC as last resort. `auto_publish_brief` and `auto_publish_brief_catchup` use `misfire_grace_time=10800` (3 hours); `send_brief_emails` uses `misfire_grace_time=7200` (2 hours).

### System Design Choices
PostgreSQL is the primary database, optimized with connection pooling, pagination, eager loading, and indexing. Redis caching enhances performance. Logging is centralized, and configuration uses `config.py` with environment variables. A `SparsityAwareScaler` is used in consensus clustering. A "Participation Gate" requires users to vote before viewing consensus analysis. Briefing templates are available via a marketplace. Briefing output includes structured HTML, email analytics, and Slack integration.

### scikit-learn Integration
All scikit-learn imports are centralised in `app/lib/sklearn_compat.py`. This module attempts a single module-level import of sklearn (and each required symbol) at process start, sets a `SKLEARN_AVAILABLE` boolean flag, and verifies native shared library dependencies (`libgomp`, `libopenblas`) via `ctypes`. Consumers (`app/trending/clustering.py`, `app/lib/consensus_engine.py`) import `SKLEARN_AVAILABLE` and the sklearn symbols from this module and branch on the flag — they never attempt lazy imports inside function bodies. A `check_sklearn_health()` function is called once from `create_app()` to surface any unavailability immediately at startup rather than silently on the first scheduler tick. The `openblas` system package is declared in `replit.nix` to ensure `libopenblas.so` is present in the deployment container, which prevents `[Errno 5] Input/output error` failures in sklearn's compiled C extensions.

## External Dependencies

### Core Services
- **Pol.is Platform**: For structured discussions and consensus building.
- **PostgreSQL Database**: Primary data store.
- **Redis Cloud**: For session management, caching, and performance.
- **Replit Object Storage**: For user-uploaded media.

### Email and Analytics
- **Resend Email Service**: For transactional emails and user communications.
- **Sentry Error Tracking**: For error monitoring and performance.
- **Google Tag Manager**: For web analytics.

### APIs
- **Guardian API**: For news article fetching.
- **OpenAI/Anthropic APIs**: For LLM-based scoring, embeddings, and content generation.
- **Clearbit API**: For fetching source logos.

### Social Media Integration
- **Bluesky (AT Protocol)**: For automatic posting of news discussions.
- **X/Twitter**: For automatic posting of news discussions.

### Billing & Subscriptions
- **Stripe**: For subscription billing and payment processing, including pricing tiers, free trials, webhooks, and a customer portal.

### Programme Management
- **Visibility hierarchy**: public → unlisted (link, no auth) → invite_only (ProgrammeAccessGrant) → private (owners/stewards only)
- **Public catalogue** shows all active public programmes regardless of whether they have live discussions (removed live-discussion gate in commit e781880)
- **Invite-only + anonymous**: unauthenticated visitors are redirected to `/login` with a flash message instead of getting 404
- **Pending steward invites**: inviting an unregistered email creates a `ProgrammeSteward` with `user_id=NULL` and `pending_email`. The record auto-links when the recipient registers. Token is preserved in the Flask session through the login/register flow and consumed on first use.
- **DB migration head**: `t9u0v1w2x3y4` (adds `pending_email VARCHAR(150) NULL`, makes `user_id` nullable on `programme_steward`)
- **`can_view_programme`**: stewards/editors bypass status check (can view archived programmes). Unknown visibility defaults to False (safe).
- `revoke_programme_access`, `remove_steward` both have try/except + rollback.

### Development & Security Tools
- **Flask Extensions**: For security, forms, and database management.
- **Tailwind CSS**: Utility-first CSS framework.
- **Node.js**: For frontend asset management.

### Audio Generation (TTS)
- **Coqui XTTS v2**: Text-to-speech code exists in `app/brief/xtts_client.py` but the `tts` package is NOT installed (removed Feb 2025 to reduce deployment image size by ~15GB). The code gracefully degrades — audio generation is disabled when the package is absent. Re-add `tts = "^0.22.0"` to pyproject.toml if TTS is needed again, but note it requires PyTorch/CUDA and will significantly increase deployment size.
- **Audio Storage**: Uses Replit Object Storage for persistence.

### Geographic Data
- **Static JSON files**: For country/city data.