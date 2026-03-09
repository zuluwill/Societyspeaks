# Load Test Suite (k6)

Phase 6.1 scripted load tests for NSP readiness.

## Prerequisites

- Install [k6](https://k6.io/docs/get-started/installation/)
  - macOS (Homebrew): `brew install k6`
- Start app locally or target deployed environment.

## Directory

- `load-tests/k6/vote_storm.js`
- `load-tests/k6/read_storm.js`
- `load-tests/k6/export_burst.js`
- `load-tests/k6/partner_lookup_burst.js`
- `load-tests/k6/nsp_uk_traffic_profile.js`
- `load-tests/k6/queue_backlog_spike.js`
- `load-tests/chaos/redis_failover.md`
- `load-tests/chaos/worker_crash_recovery.md`

## Common env vars

- `BASE_URL` (default `http://localhost:5000`)
- `AUTH_COOKIE` (optional; required for steward-only/private endpoints)

## 1) Vote storm

Simulates high-rate vote writes on a hot statement path.

Required:
- `STATEMENT_ID`

Example:

```bash
BASE_URL="https://societyspeaks.io" \
STATEMENT_ID=123 \
RATE=200 DURATION=5m PRE_VUS=200 MAX_VUS=800 \
k6 run load-tests/k6/vote_storm.js
```

## 2) Read storm

Simulates concurrent statement pagination reads and optional full discussion page reads.

Required:
- `DISCUSSION_ID`

Optional:
- `DISCUSSION_SLUG` (enables additional `/discussions/<id>/<slug>` read)

Example:

```bash
BASE_URL="https://societyspeaks.io" \
DISCUSSION_ID=123 \
DISCUSSION_SLUG="my-discussion-slug" \
START_RATE=100 RATE_STEP_1=300 RATE_STEP_2=600 RATE_STEP_3=600 \
STAGE_1=2m STAGE_2=5m STAGE_3=3m \
k6 run load-tests/k6/read_storm.js
```

## 3) Export burst

Simulates burst enqueueing of async programme export jobs.

Required:
- `PROGRAMME_SLUG`
- `AUTH_COOKIE` for a steward user session

Example:

```bash
BASE_URL="https://societyspeaks.io" \
PROGRAMME_SLUG="nsp-programme" \
AUTH_COOKIE="session=<cookie-value>" \
RATE=30 DURATION=3m PRE_VUS=60 MAX_VUS=300 \
k6 run load-tests/k6/export_burst.js
```

## 4) Partner lookup burst

Simulates partner API lookup traffic spikes.

Required:
- `ARTICLE_URL`

Optional:
- `PARTNER_REF` (default `loadtest`)
- `PARTNER_API_KEY` (for keyed lookup context)
- `RANDOMIZE_URL=true` (cache-bypass stress mode)

Example:

```bash
BASE_URL="https://societyspeaks.io" \
ARTICLE_URL="https://example.com/news/story-1" \
PARTNER_REF="observer" \
RATE=300 DURATION=5m PRE_VUS=300 MAX_VUS=1000 \
k6 run load-tests/k6/partner_lookup_burst.js
```

## 5) UK mixed traffic profile

Combines read/vote/partner/export traffic with UK-style burst windows.

Recommended env vars for composed sub-scenarios:
- `STATEMENT_ID` (needed only if vote traffic enabled)
- `DISCUSSION_ID` (needed only if read traffic enabled)
- `PROGRAMME_SLUG` (needed only if export traffic enabled)
- `ARTICLE_URL` (needed only if partner lookup traffic enabled)

Recommended:
- `AUTH_COOKIE` (for export queueing / steward-only paths)

Example:

```bash
BASE_URL="https://societyspeaks.io" \
STATEMENT_ID=123 DISCUSSION_ID=456 PROGRAMME_SLUG="nsp-programme" \
ARTICLE_URL="https://example.com/news/story-1" \
AUTH_COOKIE="session=<cookie>" \
START_RATE=150 RATE_MORNING=500 RATE_DAY_PEAK=1200 RATE_EVENING_PEAK=1800 RATE_SOAK=700 \
W_READ=60 W_VOTE=25 W_PARTNER=12 W_EXPORT=3 \
k6 run load-tests/k6/nsp_uk_traffic_profile.js
```

Notes:
- If a route-specific identifier is missing, that branch is skipped safely.
- To run without exports on a new programme setup, set `W_EXPORT=0` and omit `PROGRAMME_SLUG`.

## 6) Queue backlog spike

Queues export jobs aggressively and optionally consensus triggers to stress queue consumers.

Required:
- `PROGRAMME_SLUG`

Optional:
- `DISCUSSION_ID` (adds consensus trigger load)
- `AUTH_COOKIE` (required for protected paths)

Example:

```bash
BASE_URL="https://societyspeaks.io" \
PROGRAMME_SLUG="nsp-programme" \
DISCUSSION_ID=456 \
AUTH_COOKIE="session=<cookie>" \
RATE=80 DURATION=5m PRE_VUS=120 MAX_VUS=600 \
k6 run load-tests/k6/queue_backlog_spike.js
```

## Failure-mode drills

- Redis failover runbook: `load-tests/chaos/redis_failover.md`
- Worker crash recovery runbook: `load-tests/chaos/worker_crash_recovery.md`

## Result interpretation

- Start with conservative rates and ramp up until:
  - threshold violations (`p95`, `p99`, `http_req_failed`)
  - elevated queue lag / dead-letter counts
  - DB lock contention or saturation indicators
- Export burst should be evaluated with queue metrics, not only request latency.
- Partner lookup burst should be evaluated with cache hit ratio and rate-limit behavior.
