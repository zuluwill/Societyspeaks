const test = require("node:test");
const assert = require("node:assert/strict");
const { createHmac } = require("crypto");
const { SocietyspeaksPartnerClient, PartnerApiError, SDK_VERSION } = require("./index.js");

test("createDiscussion sends embed submission flag and idempotency key", async () => {
  let captured = null;
  global.fetch = async (url, options) => {
    captured = { url, options };
    return {
      ok: true,
      status: 201,
      headers: { get: () => "application/json" },
      json: async () => ({ discussion_id: 99 }),
      text: async () => "",
    };
  };

  const client = new SocietyspeaksPartnerClient({
    baseUrl: "https://societyspeaks.io",
    apiKey: "sspk_live_test",
  });

  const result = await client.createDiscussion({
    title: "Test discussion",
    externalId: "observer-cms-99",
    seedStatements: [{ content: "This is a valid seed statement.", position: "neutral" }],
    embedStatementSubmissionsEnabled: true,
    idempotencyKey: "idem-fixed",
  });

  assert.equal(result.discussion_id, 99);
  assert.equal(captured.options.headers["Idempotency-Key"], "idem-fixed");
  const body = JSON.parse(captured.options.body);
  assert.equal(body.embed_statement_submissions_enabled, true);
});

test("patchDiscussion requires at least one field", async () => {
  const client = new SocietyspeaksPartnerClient({
    baseUrl: "https://societyspeaks.io",
    apiKey: "sspk_live_test",
  });
  assert.throws(() => client.patchDiscussion(123, {}), /at least one field/i);
});

test("PartnerApiError includes retryAfter from response", async () => {
  global.fetch = async () => ({
    ok: false,
    status: 429,
    headers: {
      get: (name) => (name.toLowerCase() === "content-type" ? "application/json" : "60"),
    },
    json: async () => ({ error: "rate_limited", message: "Too many requests" }),
    text: async () => "",
  });

  const client = new SocietyspeaksPartnerClient({
    baseUrl: "https://societyspeaks.io",
    apiKey: "sspk_live_test",
    maxRetries: 0,
  });

  await assert.rejects(
    async () => client.listDiscussions(),
    (err) => err instanceof PartnerApiError && err.retryAfter === 60
  );
});

test("exports sdk version", () => {
  const client = new SocietyspeaksPartnerClient({
    baseUrl: "https://societyspeaks.io",
    apiKey: "sspk_live_test",
  });
  assert.equal(client.sdkVersion, SDK_VERSION);
});

test("verifyWebhookSignature returns true for valid signature", () => {
  const nowSec = 1_700_000_000;
  const originalNow = Date.now;
  Date.now = () => nowSec * 1000;
  try {
    const body = Buffer.from('{"id":"evt_123","type":"discussion.updated"}', "utf8");
    const ts = String(nowSec);
    const secret = "sswh_test_secret";
    const payload = Buffer.concat([Buffer.from(`${ts}.`, "utf8"), body]);
    const signature =
      "sha256=" + createHmac("sha256", secret).update(payload).digest("hex");

    assert.equal(
      SocietyspeaksPartnerClient.verifyWebhookSignature(
        body,
        signature,
        ts,
        secret
      ),
      true
    );
  } finally {
    Date.now = originalNow;
  }
});

test("verifyWebhookSignature returns false for invalid signature", () => {
  const nowSec = 1_700_000_000;
  const originalNow = Date.now;
  Date.now = () => nowSec * 1000;
  try {
    assert.equal(
      SocietyspeaksPartnerClient.verifyWebhookSignature(
        Buffer.from("{}", "utf8"),
        "sha256=deadbeef",
        String(nowSec),
        "sswh_test_secret"
      ),
      false
    );
  } finally {
    Date.now = originalNow;
  }
});

test("verifyWebhookSignature rejects stale timestamp", () => {
  const nowSec = 1_700_000_000;
  const originalNow = Date.now;
  Date.now = () => nowSec * 1000;
  try {
    assert.throws(
      () =>
        SocietyspeaksPartnerClient.verifyWebhookSignature(
          Buffer.from("{}", "utf8"),
          "sha256=deadbeef",
          String(nowSec - 301),
          "sswh_test_secret",
          300
        ),
      /replay attack/i
    );
  } finally {
    Date.now = originalNow;
  }
});

test("verifyWebhookSignature rejects malformed timestamp", () => {
  assert.throws(
    () =>
      SocietyspeaksPartnerClient.verifyWebhookSignature(
        Buffer.from("{}", "utf8"),
        "sha256=deadbeef",
        "not-a-ts",
        "sswh_test_secret"
      ),
    /invalid or missing/i
  );
});
