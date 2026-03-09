import { check, sleep } from 'k6';
import { BASE_URL, randomInt, sleepJitter } from './common.js';
import http from 'k6/http';

const articleUrl = __ENV.ARTICLE_URL;

if (!articleUrl) {
  throw new Error('PARTNER config missing: set ARTICLE_URL env var');
}

export const options = {
  scenarios: {
    partner_lookup_burst: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 60),
      timeUnit: '1s',
      duration: __ENV.DURATION || '2m',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 50),
      maxVUs: Number(__ENV.MAX_VUS || 300),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<500', 'p(99)<1200'],
  },
};

export default function () {
  const ref = __ENV.PARTNER_REF || 'loadtest';
  const suffix = __ENV.RANDOMIZE_URL === 'true' ? `?v=${randomInt(1, 1000000)}` : '';
  const encoded = encodeURIComponent(`${articleUrl}${suffix}`);
  const url = `${BASE_URL}/api/discussions/by-article-url?url=${encoded}&ref=${encodeURIComponent(ref)}`;
  const headers = {};
  if (__ENV.PARTNER_API_KEY) {
    headers['X-API-Key'] = __ENV.PARTNER_API_KEY;
  }
  const res = http.get(url, { headers });

  check(res, {
    'lookup status is expected': (r) => [200, 400, 401, 403, 404, 429].includes(r.status),
  });

  sleep(sleepJitter());
}
