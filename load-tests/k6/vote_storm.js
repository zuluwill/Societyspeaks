import http from 'k6/http';
import { check, sleep } from 'k6';
import { authHeaders, BASE_URL, randomInt, sleepJitter } from './common.js';

const statementId = __ENV.STATEMENT_ID;

if (!statementId) {
  throw new Error('STMT config missing: set STATEMENT_ID env var');
}

export const options = {
  scenarios: {
    vote_storm: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 50),
      timeUnit: '1s',
      duration: __ENV.DURATION || '2m',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 50),
      maxVUs: Number(__ENV.MAX_VUS || 200),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<200', 'p(99)<500'],
  },
};

function pickVote() {
  const votes = [-1, 0, 1];
  return votes[randomInt(0, votes.length - 1)];
}

export default function () {
  const vote = pickVote();
  const payload = JSON.stringify({
    vote,
    confidence: randomInt(1, 5),
    ref: __ENV.PARTNER_REF || 'loadtest',
    cohort: __ENV.COHORT_SLUG || undefined,
  });

  const res = http.post(
    `${BASE_URL}/statements/${statementId}/vote`,
    payload,
    {
      headers: {
        ...authHeaders(),
        // Vote route accepts embed requests without CSRF.
        'X-Embed-Request': 'true',
      },
    }
  );

  check(res, {
    'vote status is success/limited/conflict': (r) => [200, 409, 429].includes(r.status),
    'vote payload has expected shape': (r) => {
      if (r.status !== 200) return true;
      try {
        const body = r.json();
        return body && body.success === true;
      } catch (_err) {
        return false;
      }
    },
  });

  sleep(sleepJitter());
}
