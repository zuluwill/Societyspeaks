import { check, sleep } from 'k6';
import { authHeaders, getJson, randomInt, sleepJitter } from './common.js';

const discussionId = __ENV.DISCUSSION_ID;
const discussionSlug = __ENV.DISCUSSION_SLUG;

if (!discussionId) {
  throw new Error('READ config missing: set DISCUSSION_ID env var');
}

export const options = {
  scenarios: {
    read_storm: {
      executor: 'ramping-arrival-rate',
      startRate: Number(__ENV.START_RATE || 50),
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 50),
      maxVUs: Number(__ENV.MAX_VUS || 300),
      stages: [
        { target: Number(__ENV.RATE_STEP_1 || 100), duration: __ENV.STAGE_1 || '1m' },
        { target: Number(__ENV.RATE_STEP_2 || 200), duration: __ENV.STAGE_2 || '2m' },
        { target: Number(__ENV.RATE_STEP_3 || 200), duration: __ENV.STAGE_3 || '1m' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.02'],
    http_req_duration: ['p(95)<500', 'p(99)<1200'],
  },
};

export default function () {
  const page = randomInt(1, Number(__ENV.MAX_PAGE || 10));
  const sorts = ['progressive', 'most_voted', 'recent', 'best', 'controversial'];
  const sort = sorts[randomInt(0, sorts.length - 1)];

  const pageRes = getJson(`/api/discussions/${discussionId}/statements`, authHeaders(), { page, sort });
  check(pageRes, {
    'statement page status is 200/404': (r) => [200, 404].includes(r.status),
  });

  if (discussionSlug) {
    const discussionRes = getJson(`/discussions/${discussionId}/${discussionSlug}`, authHeaders());
    check(discussionRes, {
      'discussion page status is 200/302/404': (r) => [200, 302, 404].includes(r.status),
    });
  }

  sleep(sleepJitter());
}
