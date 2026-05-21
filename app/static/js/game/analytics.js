(function () {
  'use strict';

  /** Client-side PostHog helpers for game flows (share, etc.). */
  window.gameAnalytics = {
    capture: function (event, properties) {
      try {
        if (window.posthog && typeof window.posthog.capture === 'function') {
          window.posthog.capture(event, properties || {});
        }
      } catch (e) {
        /* analytics must never break play */
      }
    },
  };
})();
