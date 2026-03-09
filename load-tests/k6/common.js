import http from 'k6/http';
import { check } from 'k6';

export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:5000').replace(/\/+$/, '');

export function authHeaders() {
  const headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  };
  if (__ENV.AUTH_COOKIE) {
    headers['Cookie'] = __ENV.AUTH_COOKIE;
  }
  return headers;
}

export function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export function sleepJitter() {
  // small natural jitter between iterations
  const ms = randomInt(100, 900);
  return ms / 1000;
}

export function checkStatusOk(res, okStatuses, name) {
  check(res, {
    [`${name} status in ${okStatuses.join('/')}`]: (r) => okStatuses.includes(r.status),
  });
}

export function getJson(path, headers = {}, params = {}) {
  const query = new URLSearchParams(params).toString();
  const url = query ? `${BASE_URL}${path}?${query}` : `${BASE_URL}${path}`;
  return http.get(url, { headers });
}
