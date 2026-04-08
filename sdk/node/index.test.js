const test = require("node:test");
const assert = require("node:assert/strict");
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
