/**
 * Resilient vote submission helper.
 *
 * Provides a single fetch wrapper with:
 *   - AbortController timeout (default 10 s)
 *   - Exponential-backoff retry on network / 5xx failures (default 3 attempts)
 *   - Error classification so callers can distinguish 429 / network / server errors
 *
 * Used by server-rendered voting surfaces (e.g. view_native.html).
 * The embed template is intentionally self-contained and does not use this module.
 */
(function () {
  'use strict';

  /**
   * Submit a vote with resilience (timeout + retry).
   *
   * @param {string}   url          Request URL, e.g. /statements/42/vote
   * @param {object}   payload      JSON body to send
   * @param {string}   csrfToken    CSRF token value
   * @param {object}   [opts]
   * @param {number}   [opts.timeoutMs=10000]     Per-attempt timeout in ms
   * @param {number}   [opts.maxRetries=3]         Max retries after first failure
   * @param {number[]} [opts.retryDelays]           Delay (ms) before each retry
   * @returns {Promise<object>}  Parsed JSON response on success
   * @throws  {Error}            With .status and .data on HTTP errors; plain Error on timeout/network
   */
  async function submitVoteWithResilience(url, payload, csrfToken, opts) {
    const { timeoutMs, maxRetries, retryDelays } = Object.assign(
      { timeoutMs: 10000, maxRetries: 3, retryDelays: [1000, 2000, 4000] },
      opts
    );

    let attempts = 0;

    async function attempt() {
      const controller = new AbortController();
      const timerId = setTimeout(() => controller.abort(), timeoutMs);

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
          },
          credentials: 'same-origin',
          signal: controller.signal,
          body: JSON.stringify(payload),
        });
        clearTimeout(timerId);

        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const err = new Error('Vote failed');
          err.status = response.status;
          err.data = data;
          throw err;
        }
        return data;
      } catch (err) {
        clearTimeout(timerId);
        if (err.name === 'AbortError') {
          err.message = 'Request timed out';
        }
        // Do not retry client errors (4xx): rate-limit, forbidden, closed, etc.
        const status = err.status || 0;
        if (status >= 400 && status < 500) {
          throw err;
        }
        attempts++;
        if (attempts <= maxRetries) {
          const delay = retryDelays[attempts - 1] || 4000;
          await new Promise((resolve) => setTimeout(resolve, delay));
          return attempt();
        }
        throw err;
      }
    }

    return attempt();
  }

  window.VoteResilience = { submitVoteWithResilience };
})();
