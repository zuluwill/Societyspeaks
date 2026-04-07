# Society Speaks Partner SDK (Lightweight)

Official lightweight wrappers for backend partner integrations.

- `python/societyspeaks_partner.py`
- `node/index.js`

## Supported helper methods

- `lookupByArticleUrl` / `lookup_by_article_url`
- `createDiscussion` / `create_discussion`
- `getDiscussionByExternalId` / `get_discussion_by_external_id`
- `exportUsage` / `export_usage`

## Notes

- Server-side use only. Never expose `X-API-Key` in browser code.
- `createDiscussion` sets an idempotency key by default.
- Retries only happen for `5xx` errors with short exponential backoff.
- SDK throws normalized errors:
  - Python: `PartnerApiError`
  - Node: `PartnerApiError`
