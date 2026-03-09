import { check, sleep } from 'k6';
import { authHeaders, getJson, sleepJitter } from './common.js';

const programmeSlug = __ENV.PROGRAMME_SLUG;

if (!programmeSlug) {
  throw new Error('EXPORT config missing: set PROGRAMME_SLUG env var');
}

export const options = {
  scenarios: {
    export_burst: {
      executor: 'constant-arrival-rate',
      rate: Number(__ENV.RATE || 10),
      timeUnit: '1s',
      duration: __ENV.DURATION || '1m',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 20),
      maxVUs: Number(__ENV.MAX_VUS || 100),
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.05'],
    http_req_duration: ['p(95)<800', 'p(99)<2000'],
  },
};

export default function () {
  const format = __ENV.EXPORT_FORMAT || 'json';
  const cohort = __ENV.COHORT_SLUG;
  const res = getJson(`/programmes/${programmeSlug}/export`, authHeaders(), {
    format,
    json: 1,
    cohort: cohort || undefined,
  });

  check(res, {
    'export enqueue status is expected': (r) => [202, 401, 403, 404].includes(r.status),
    'export success payload includes job_id': (r) => {
      if (r.status !== 202) return true;
      try {
        const body = r.json();
        return body && body.success === true && !!body.job_id;
      } catch (_err) {
        return false;
      }
    },
  });

  sleep(sleepJitter());
}
