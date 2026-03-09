# Redis Failover Test Plan

Phase 6.1 failure-mode test: Redis failover behavior.

## Objective

Verify the platform degrades safely when Redis becomes unavailable and recovers cleanly after failover.

## Preconditions

- Web app + worker pool running.
- Monitoring available for:
  - API error rate
  - queue lag/dead-letter
  - session/login error rate
  - rate-limit behavior

## Test Steps

1. Start baseline traffic:
   - `k6 run load-tests/k6/read_storm.js`
   - `k6 run load-tests/k6/vote_storm.js`
2. Trigger Redis failure/failover (infrastructure action).
3. Keep traffic running for 5-10 minutes during incident.
4. Restore Redis service.
5. Continue traffic for 10 minutes post-recovery.

## Expected Behavior

- App remains available for core read paths.
- Rate limiter/session behavior may degrade but should not crash web workers.
- Worker loop should continue with retry logs and recover when Redis returns.
- Queue jobs should not be permanently stuck (monitor lag trend post-recovery).

## Pass/Fail Criteria

- No sustained 5xx storm after failover starts.
- Queue lag returns toward baseline after Redis restoration.
- No unrecoverable dead-letter spike solely caused by failover window.
- Login/session flows recover without manual app restart.
