/**
 * Lightweight Society Speaks Partner API client.
 * Backend/server usage only (never expose API keys in browser code).
 */

const { randomUUID } = require("crypto");
const SDK_VERSION = "0.2.0";

class PartnerApiError extends Error {
  constructor(statusCode, error, message, retryAfter = null) {
    super(`${statusCode} ${error}: ${message}`);
    this.statusCode = statusCode;
    this.error = error;
    this.message = message;
    this.retryAfter = retryAfter;
  }
}

class SocietyspeaksPartnerClient {
  constructor({ baseUrl, apiKey, timeoutMs = 15000, maxRetries = 2 }) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.apiKey = apiKey;
    this.timeoutMs = timeoutMs;
    this.maxRetries = maxRetries;
  }

  get sdkVersion() {
    return SDK_VERSION;
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
      try {
        const signal = AbortSignal.timeout(this.timeoutMs);
        response = await fetch(url.toString(), {
          method,
          headers: mergedHeaders,
          body: body ? JSON.stringify(body) : undefined,
          signal,
        });
      } catch (err) {
        if (attempt > this.maxRetries) {
          throw new PartnerApiError(0, "network_error", err?.message || "Network request failed.");
        }
        await new Promise((r) => setTimeout(r, 500 * attempt));
        continue;
      }
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
      err.message || "Request failed.",
      Number.isFinite(Number(response.headers.get("retry-after")))
        ? Number(response.headers.get("retry-after"))
        : null
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
    embedStatementSubmissionsEnabled,
  }) {
    if (!articleUrl && !externalId) {
      throw new Error("Provide at least one identifier: articleUrl or externalId.");
    }
    if (!excerpt && !seedStatements) {
      throw new Error("Provide excerpt or seedStatements.");
    }
    if (
      embedStatementSubmissionsEnabled !== undefined &&
      typeof embedStatementSubmissionsEnabled !== "boolean"
    ) {
      throw new Error("embedStatementSubmissionsEnabled must be a boolean when provided.");
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
        embed_statement_submissions_enabled: embedStatementSubmissionsEnabled,
      },
    });
  }

  getDiscussionByExternalId(externalId, env) {
    return this._request("GET", "/api/partner/discussions/by-external-id", {
      params: { external_id: externalId, env },
    });
  }

  listDiscussions({ env = "all", page = 1, perPage = 30 } = {}) {
    return this._request("GET", "/api/partner/discussions", {
      params: { env, page, per_page: perPage },
    });
  }

  patchDiscussion(
    discussionId,
    { isClosed, integrityMode, embedStatementSubmissionsEnabled } = {}
  ) {
    const body = {};
    if (isClosed !== undefined) {
      if (typeof isClosed !== "boolean") throw new Error("isClosed must be a boolean when provided.");
      body.is_closed = isClosed;
    }
    if (integrityMode !== undefined) {
      if (typeof integrityMode !== "boolean") throw new Error("integrityMode must be a boolean when provided.");
      body.integrity_mode = integrityMode;
    }
    if (embedStatementSubmissionsEnabled !== undefined) {
      if (typeof embedStatementSubmissionsEnabled !== "boolean") {
        throw new Error("embedStatementSubmissionsEnabled must be a boolean when provided.");
      }
      body.embed_statement_submissions_enabled = embedStatementSubmissionsEnabled;
    }
    if (Object.keys(body).length === 0) {
      throw new Error("Provide at least one field to patch.");
    }
    return this._request("PATCH", `/api/partner/discussions/${discussionId}`, { body });
  }

  listWebhooks() {
    return this._request("GET", "/api/partner/webhooks");
  }

  createWebhook({ url, eventTypes }) {
    return this._request("POST", "/api/partner/webhooks", {
      body: { url, event_types: eventTypes },
    });
  }

  updateWebhook(endpointId, { status, eventTypes } = {}) {
    const body = {};
    if (status !== undefined) body.status = status;
    if (eventTypes !== undefined) body.event_types = eventTypes;
    if (Object.keys(body).length === 0) {
      throw new Error("Provide status and/or eventTypes to update.");
    }
    return this._request("PATCH", `/api/partner/webhooks/${endpointId}`, { body });
  }

  deleteWebhook(endpointId) {
    return this._request("DELETE", `/api/partner/webhooks/${endpointId}`);
  }

  rotateWebhookSecret(endpointId) {
    return this._request("POST", `/api/partner/webhooks/${endpointId}/rotate-secret`);
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
  SDK_VERSION,
};
