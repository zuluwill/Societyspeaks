# Worker Crash Recovery Test Plan

Phase 6.1 failure-mode test: worker crash during consensus/export processing.

## Objective

Verify job timeout/stale/dead-letter lifecycle and recovery behavior when workers crash mid-flight.

## Preconditions

- At least 2 workers running (`Consensus Worker Pool (x3)` recommended).
- Queue metrics observable:
  - queued/running/dead-letter counts
  - queue lag
  - worker heartbeat keys

## Test Steps

1. Create queue pressure:
   - `k6 run load-tests/k6/queue_backlog_spike.js`
2. During active processing, terminate one worker process abruptly.
3. Observe:
   - heartbeat key for terminated worker expires
   - remaining workers continue claims
4. Terminate all workers for a short window (optional harder test).
5. Restart workers.

## Expected Behavior

- No double-claim of same job (SKIP LOCKED protection).
- In-flight jobs from dead workers eventually transition stale/queued/dead-letter according to retry policy.
- Queue drain resumes after workers restart.

## Pass/Fail Criteria

- Queue lag spikes during outage but trends down after restart.
- No unbounded growth of `running` jobs after stale sweep intervals.
- Dead-letter growth stays within expected retry policy envelope.
