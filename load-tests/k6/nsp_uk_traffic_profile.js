import http from 'k6/http';
import { check, sleep } from 'k6';
import exec from 'k6/execution';
import { BASE_URL, authHeaders, randomInt, sleepJitter } from './common.js';

// UK-style mixed traffic profile with rush-hour bias.
// Weighted mix (default):
// - reads: 60%
// - votes: 25%
// - partner lookups: 12%
// - exports: 3%
export const options = {
  scenarios: {
    uk_profile: {
      executor: 'ramping-arrival-rate',
      startRate: Number(__ENV.START_RATE || 100),
      timeUnit: '1s',
      preAllocatedVUs: Number(__ENV.PRE_VUS || 150),
      maxVUs: Number(__ENV.MAX_VUS || 1200),
      stages: [
        // warmup
        { target: Number(__ENV.RATE_MORNING || 400), duration: __ENV.STAGE_MORNING || '5m' },
        // daytime peak
        { target: Number(__ENV.RATE_DAY_PEAK || 1200), duration: __ENV.STAGE_DAY_PEAK || '10m' },
        // evening peak
        { target: Number(__ENV.RATE_EVENING_PEAK || 1800), duration: __ENV.STAGE_EVENING_PEAK || '10m' },
        // cool-down soak
        { target: Number(__ENV.RATE_SOAK || 600), duration: __ENV.STAGE_SOAK || '10m' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.03'],
    http_req_duration: ['p(95)<700', 'p(99)<1500'],
  },
};

const statementId = __ENV.STATEMENT_ID;
const discussionId = __ENV.DISCUSSION_ID;
const discussionSlug = __ENV.DISCUSSION_SLUG;
const programmeSlug = __ENV.PROGRAMME_SLUG;
const articleUrl = __ENV.ARTICLE_URL;

function weightedPick() {
  const readWeight = Number(__ENV.W_READ || 60);
  const voteWeight = Number(__ENV.W_VOTE || 25);
  const partnerWeight = Number(__ENV.W_PARTNER || 12);
  const exportWeight = Number(__ENV.W_EXPORT || 3);
  const total = readWeight + voteWeight + partnerWeight + exportWeight;
  const roll = randomInt(1, total);
  if (roll <= readWeight) return 'read';
  if (roll <= readWeight + voteWeight) return 'vote';
  if (roll <= readWeight + voteWeight + partnerWeight) return 'partner';
  return 'export';
}

export default function () {
  const action = weightedPick();
  if (action === 'read') {
    if (!discussionId) {
      return;
    }
    const page = randomInt(1, Number(__ENV.MAX_PAGE || 10));
    const sorts = ['progressive', 'most_voted', 'recent', 'best', 'controversial'];
    const sort = sorts[randomInt(0, sorts.length - 1)];
    const pageRes = http.get(
      `${BASE_URL}/api/discussions/${discussionId}/statements?page=${page}&sort=${sort}`,
      { headers: authHeaders() }
    );
    check(pageRes, {
      'uk/read api status is expected': (r) => [200, 404].includes(r.status),
    });
    if (discussionSlug) {
      const discussionRes = http.get(
        `${BASE_URL}/discussions/${discussionId}/${discussionSlug}`,
        { headers: authHeaders() }
      );
      check(discussionRes, {
        'uk/read page status is expected': (r) => [200, 302, 404].includes(r.status),
      });
    }
  } else if (action === 'vote') {
    if (!statementId) {
      return;
    }
    const votes = [-1, 0, 1];
    const vote = votes[randomInt(0, votes.length - 1)];
    const voteRes = http.post(
      `${BASE_URL}/statements/${statementId}/vote`,
      JSON.stringify({
        vote,
        confidence: randomInt(1, 5),
        ref: __ENV.PARTNER_REF || 'loadtest',
      }),
      {
        headers: {
          ...authHeaders(),
          'X-Embed-Request': 'true',
        },
      }
    );
    check(voteRes, {
      'uk/vote status is expected': (r) => [200, 409, 429].includes(r.status),
    });
  } else if (action === 'partner') {
    if (!articleUrl) {
      return;
    }
    const ref = __ENV.PARTNER_REF || 'loadtest';
    const encoded = encodeURIComponent(articleUrl);
    const headers = {};
    if (__ENV.PARTNER_API_KEY) {
      headers['X-API-Key'] = __ENV.PARTNER_API_KEY;
    }
    const partnerRes = http.get(
      `${BASE_URL}/api/discussions/by-article-url?url=${encoded}&ref=${encodeURIComponent(ref)}`,
      { headers }
    );
    check(partnerRes, {
      'uk/partner status is expected': (r) => [200, 400, 401, 403, 404, 429].includes(r.status),
    });
  } else {
    if (!programmeSlug) {
      return;
    }
    const format = __ENV.EXPORT_FORMAT || 'json';
    const exportRes = http.get(
      `${BASE_URL}/programmes/${programmeSlug}/export?json=1&format=${encodeURIComponent(format)}`,
      { headers: authHeaders() }
    );
    check(exportRes, {
      'uk/export status is expected': (r) => [202, 401, 403, 404].includes(r.status),
    });
  }

  // Add periodic jitter based on arrival sequence to reduce lock-step spikes.
  if (exec.scenario.iterationInTest % 3 === 0) {
    sleep(sleepJitter());
  }
}
