/**
 * Lightweight Society Speaks Partner API client.
 * Backend/server usage only (never expose API keys in browser code).
 */

const { randomUUID } = require("crypto");

class PartnerApiError extends Error {
  constructor(statusCode, error, message) {
    super(`${statusCode} ${error}: ${message}`);
    this.statusCode = statusCode;
    this.error = error;
    this.message = message;
  }
}

class SocietyspeaksPartnerClient {
  constructor({ baseUrl, apiKey, timeoutMs = 15000, maxRetries = 2 }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
    this.maxRetries = maxRetries;
  }

  async _request(method, path, { body, params, headers } = {}) {
    const url = new URL(`${this.baseUrl}${path}`);
    if (params) {
      Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
      });
    }
    const mergedHeaders = {
      "X-API-Key": this.apiKey,
      "Content-Type": "application/json",
      ...(headers || {}),
    };
    let attempt = 0;
    let response;
    while (attempt <= this.maxRetries) {
      attempt += 1;
      const signal = AbortSignal.timeout(this.timeoutMs);
      response = await fetch(url.toString(), {
        method,
        headers: mergedHeaders,
        body: body ? JSON.stringify(body) : undefined,
        signal,
      });
      if (response.status < 500 || attempt > this.maxRetries) break;
      await new Promise((r) => setTimeout(r, 500 * attempt));
    }

    const isJson = (response.headers.get("content-type") || "").includes("application/json");
    const payload = isJson ? await response.json() : await response.text();
    if (response.ok) return payload;
    const err = isJson ? payload : {};
    throw new PartnerApiError(
      response.status,
      err.error || "request_failed",
      err.message || "Request failed."
    );
  }

  lookupByArticleUrl(url) {
    return this._request("GET", "/api/discussions/by-article-url", { params: { url } });
  }

  createDiscussion({
    title,
    articleUrl,
    externalId,
    excerpt,
    seedStatements,
    sourceName,
    idempotencyKey,
  }) {
    if (!articleUrl && !externalId) {
      throw new Error("Provide at least one identifier: articleUrl or externalId.");
    }
    if (!excerpt && !seedStatements) {
      throw new Error("Provide excerpt or seedStatements.");
    }
    return this._request("POST", "/api/partner/discussions", {
      headers: {
        "Idempotency-Key": idempotencyKey || `idem_${randomUUID().replaceAll("-", "")}`,
      },
      body: {
        title,
        article_url: articleUrl,
        external_id: externalId,
        excerpt,
        seed_statements: seedStatements,
        source_name: sourceName,
      },
    });
  }

  getDiscussionByExternalId(externalId, env) {
    return this._request("GET", "/api/partner/discussions/by-external-id", {
      params: { external_id: externalId, env },
    });
  }

  exportUsage({ days = 30, env = "all", page = 1, perPage = 100 } = {}) {
    return this._request("GET", "/api/partner/analytics/usage-export", {
      params: { days, env, format: "json", page, per_page: perPage },
    });
  }
}

module.exports = {
  SocietyspeaksPartnerClient,
  PartnerApiError,
};
