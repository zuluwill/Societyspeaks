import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, authHeaders, sleepJitter } from './common.js';

const programmeSlug = __ENV.PROGRAMME_SLUG;
const discussionId = __ENV.DISCUSSION_ID;

if (!programmeSlug) {
  throw new Error('QUEUE_BACKLOG config missing: set PROGRAMME_SLUG');
}

export const options = {
  scenarios: {
    queue_backlog_spike: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 40),
      timeUnit: '1s',
      duration: __ENV.DURATION || '3m',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 80),
      maxVUs: Number(__ENV.MAX_VUS || 400),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.1'],
    http_req_duration: ['p(95)<1500', 'p(99)<3500'],
  },
};

function enqueueExport() {
  const format = __ENV.EXPORT_FORMAT || 'json';
  const url = `${BASE_URL}/programmes/${programmeSlug}/export?json=1&format=${encodeURIComponent(format)}`;
  const res = http.get(url, { headers: authHeaders() });
  check(res, {
    'export enqueue returns expected status': (r) => [202, 401, 403, 404, 429].includes(r.status),
  });
}

function triggerConsensus() {
  if (!discussionId) return;
  const url = `${BASE_URL}/discussions/${discussionId}/consensus/analyze`;
  const res = http.post(url, null, {
    headers: {
      ...authHeaders(),
      // Many form handlers treat this as AJAX request path.
      'X-Requested-With': 'XMLHttpRequest',
    },
    redirects: 0,
  });
  check(res, {
    'consensus trigger status is expected': (r) => [200, 302, 401, 403, 404, 429].includes(r.status),
  });
}

export default function () {
  enqueueExport();
  triggerConsensus();
  sleep(sleepJitter());
}
