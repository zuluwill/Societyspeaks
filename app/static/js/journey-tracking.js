/**
 * Journey step timing and abandon tracking.
 *
 * Reads config from window.JourneyTrackingCfg (set inline by view_native.html).
 * Sends beacons to /programmes/journey/step-timing and /programmes/journey/abandon.
 * All PostHog captures happen server-side so the same identity resolution applies.
 *
 * Events fired (server-side via beacon):
 *   journey_step_timed  — user completes all votes in a step (carries time_on_step_seconds)
 *   journey_abandoned   — user leaves mid-step after casting at least one vote
 */
(function () {
  'use strict';

  var cfg = window.JourneyTrackingCfg;
  if (!cfg || !cfg.programmeId || !cfg.discussionId) return;

  var TIMING_URL = '/programmes/journey/step-timing';
  var ABANDON_URL = '/programmes/journey/abandon';

  // ── Step start time in sessionStorage ────────────────────────────────────
  // Only record the start time if this is a fresh arrival (not a return visit
  // mid-session), so the timer reflects actual time-on-step.
  var SS_KEY = 'jss_' + cfg.discussionId;
  if (!sessionStorage.getItem(SS_KEY)) {
    sessionStorage.setItem(SS_KEY, String(Date.now()));
  }
  var stepStartMs = parseInt(sessionStorage.getItem(SS_KEY), 10) || Date.now();
  var stepCompleted = false;

  // ── Helpers ───────────────────────────────────────────────────────────────
  function countVotes() {
    var v = window.userVotes || {};
    return Object.keys(v).filter(function (k) {
      return v[k] !== undefined && v[k] !== null;
    }).length;
  }

  function sendBeacon(url, payload) {
    try {
      if (typeof navigator.sendBeacon === 'function') {
        navigator.sendBeacon(
          url,
          new Blob([JSON.stringify(payload)], { type: 'application/json' })
        );
      } else {
        // Fallback for older browsers: fire-and-forget fetch (best effort on unload)
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
          keepalive: true,
        }).catch(function () {});
      }
    } catch (_) {
      // Silently ignore — server-side events cover the core funnel
    }
  }

  // ── Step completed ────────────────────────────────────────────────────────
  // Fired by the journey UI IIFE (view_native.html) via ss:journeyStepComplete
  document.addEventListener('ss:journeyStepComplete', function () {
    if (stepCompleted) return;
    stepCompleted = true;
    var elapsed = Date.now() - stepStartMs;
    // Clear so returning users start a fresh timer if they revisit the step
    sessionStorage.removeItem(SS_KEY);
    sendBeacon(TIMING_URL, {
      programme_id: cfg.programmeId,
      discussion_id: cfg.discussionId,
      time_on_step_ms: elapsed,
    });
  });

  // ── Abandon ───────────────────────────────────────────────────────────────
  // pagehide fires reliably on navigation, tab close, and mobile backgrounding.
  // Only fires if the step is incomplete and the user has cast at least one vote
  // (zero-vote departures are bounces, not mid-journey abandons).
  window.addEventListener('pagehide', function () {
    if (stepCompleted) return;
    var cast = countVotes();
    if (cast === 0) return;
    var elapsed = Date.now() - stepStartMs;
    sendBeacon(ABANDON_URL, {
      programme_id: cfg.programmeId,
      discussion_id: cfg.discussionId,
      step_number: cfg.stepNumber,
      step_name: cfg.stepName,
      votes_cast: cast,
      total_statements: cfg.totalStatements,
      time_on_step_ms: elapsed,
    });
  });
})();
