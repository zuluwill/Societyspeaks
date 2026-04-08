# Society Speaks Partner SDK (Lightweight)

Official lightweight wrappers for backend partner integrations.

- `python/societyspeaks_partner.py`
- `node/index.js`

## Supported helper methods

- `lookupByArticleUrl` / `lookup_by_article_url`
- `createDiscussion` / `create_discussion`
- `listDiscussions` / `list_discussions`
- `patchDiscussion` / `patch_discussion`
- `getDiscussionByExternalId` / `get_discussion_by_external_id`
- `listWebhooks` / `list_webhooks`
- `createWebhook` / `create_webhook`
- `updateWebhook` / `update_webhook`
- `deleteWebhook` / `delete_webhook`
- `rotateWebhookSecret` / `rotate_webhook_secret`
- `exportUsage` / `export_usage`

## Notes

- Server-side use only. Never expose `X-API-Key` in browser code.
- `createDiscussion` sets an idempotency key by default.
- `createDiscussion` / `create_discussion` supports `embed_statement_submissions_enabled` (default false).
- Retries only happen for `5xx` errors with short exponential backoff.
- SDK throws normalized errors:
  - Python: `PartnerApiError`
  - Node: `PartnerApiError`
  - Both expose `retry_after` / `retryAfter` when API returns `Retry-After` (for rate limits).

## Python examples

```python
from sdk.python.societyspeaks_partner import SocietyspeaksPartnerClient, PartnerApiError

client = SocietyspeaksPartnerClient(
    base_url="https://societyspeaks.io",
    api_key="sspk_live_your_key_here",
)

try:
    created = client.create_discussion(
        title="Should our city pedestrianise the high street?",
        external_id="observer-cms-482991",
        seed_statements=[
            {"content": "Pedestrianisation improves local air quality and footfall.", "position": "pro"},
            {"content": "Pedestrianisation risks reducing access for disabled residents.", "position": "con"},
        ],
        embed_statement_submissions_enabled=False,  # Recommended default for article pages
    )

    updated = client.patch_discussion(
        created["discussion_id"],
        integrity_mode=True,
        embed_statement_submissions_enabled=True,  # Enable for high-engagement workflows
    )

    hook = client.create_webhook(
        url="https://observer.example.com/webhooks/societyspeaks",
        event_types=["discussion.created", "discussion.updated", "consensus.updated"],
    )
    webhooks = client.list_webhooks()

except PartnerApiError as err:
    # Use retry_after to back off safely on 429 responses.
    print(err.status_code, err.error, err.message, err.retry_after)
```

## Node.js examples

```javascript
const { SocietyspeaksPartnerClient, PartnerApiError } = require("./sdk/node/index.js");

const client = new SocietyspeaksPartnerClient({
  baseUrl: "https://societyspeaks.io",
  apiKey: "sspk_live_your_key_here",
});

async function run() {
  try {
    const created = await client.createDiscussion({
      title: "Should our city pedestrianise the high street?",
      externalId: "observer-cms-482991",
      seedStatements: [
        { content: "Pedestrianisation improves local air quality and footfall.", position: "pro" },
        { content: "Pedestrianisation risks reducing access for disabled residents.", position: "con" },
      ],
      embedStatementSubmissionsEnabled: false, // Recommended default for article pages
    });

    const updated = await client.patchDiscussion(created.discussion_id, {
      integrityMode: true,
      embedStatementSubmissionsEnabled: true, // Enable for high-engagement workflows
    });

    const hook = await client.createWebhook({
      url: "https://observer.example.com/webhooks/societyspeaks",
      eventTypes: ["discussion.created", "discussion.updated", "consensus.updated"],
    });
    const webhooks = await client.listWebhooks();
  } catch (err) {
    if (err instanceof PartnerApiError) {
      // Use retryAfter to back off safely on 429 responses.
      console.error(err.statusCode, err.error, err.message, err.retryAfter);
    } else {
      throw err;
    }
  }
}

run();
```

## Testing

Run SDK-focused checks from repository root:

```bash
# Python SDK tests
python3 -m pytest tests/test_sdk_python_client.py

# Node SDK tests (built-in node:test runner)
node --test sdk/node/index.test.js
```

## Versioning and release hygiene

- SDKs follow semantic versioning.
- Keep `SDK_VERSION` aligned in:
  - `sdk/python/societyspeaks_partner.py`
  - `sdk/node/index.js`
- Record changes in `sdk/CHANGELOG.md` for each release.
