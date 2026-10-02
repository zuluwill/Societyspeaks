// A room of people answering one consultation at once, mostly from one IP.
//
// Models the "QR code on a slide" case: every participant loads /c/<token>,
// then answers each statement a few seconds apart. All virtual users share
// the load generator's IP, as a room shares one Wi-Fi address, so this also
// proves the per-device rate limit is not tripped by a shared address.
//
//   BASE_URL=https://staging.example TOKEN=<access token> VUS=1000 k6 run consultation_room.js
//
// Run against a consultation created for the test. Pass thresholds before
// promising any room size.
import http from 'k6/http';
import { check, sleep } from 'k6';
import { BASE_URL, randomInt } from './common.js';

const token = __ENV.TOKEN;
if (!token) {
  throw new Error('Set TOKEN to the access token of a live consultation');
}

export const options = {
  scenarios: {
    room: {
      executor: 'per-vu-iterations',
      vus: Number(__ENV.VUS || 200),
      iterations: 1,
      // Everyone scans within the first half-minute.
      startTime: '0s',
      maxDuration: __ENV.MAX_DURATION || '6m',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:page}': ['p(95)<800'],
    'http_req_duration{name:vote}': ['p(95)<300', 'p(99)<800'],
    'checks{check:not_rate_limited}': ['rate>0.999'],
  },
};

export default function () {
  // Arrivals spread over ~30 seconds.
  sleep(Math.random() * 30);

  const jar = http.cookieJar();
  const page = http.get(`${BASE_URL}/c/${token}`, { tags: { name: 'page' } });
  check(page, { 'page loads': (r) => r.status === 200 });

  const match = page.body.match(/id="consultation-data" type="application\/json">([\s\S]*?)<\/script>/);
  if (!match) {
    return;
  }
  const statements = JSON.parse(match[1]).statements;

  // The voter cookie is Secure; over plain http k6 will not send it back, so pass it explicitly.
  const voter = jar.cookiesForURL(`${BASE_URL}/`)['ss_voter_client_id'];
  const headers = { 'Content-Type': 'application/json' };
  if (voter && voter.length) {
    headers['Cookie'] = `ss_voter_client_id=${voter[0]}`;
  }

  for (const statement of statements) {
    sleep(randomInt(2, 6)); // reading time
    const vote = [-1, 0, 1][randomInt(0, 2)];
    const res = http.post(
      `${BASE_URL}/c/${token}/vote`,
      JSON.stringify({ statement_id: statement.id, vote }),
      { headers, tags: { name: 'vote' } },
    );
    check(res, { 'vote saved': (r) => r.status === 200 });
    check(res, { not_rate_limited: (r) => r.status !== 429 }, { check: 'not_rate_limited' });
  }
}
