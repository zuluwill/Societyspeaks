# SDK Changelog

All notable changes to the Society Speaks Partner SDKs are documented here.

## 0.2.0

- Added discussion policy support on create:
  - Python: `embed_statement_submissions_enabled`
  - Node: `embedStatementSubmissionsEnabled`
- Added discussion management helpers:
  - list discussions
  - patch discussion (`is_closed`, `integrity_mode`, embed submissions policy)
- Added webhook lifecycle helpers:
  - list/create/update/delete/rotate secret
- Normalized retry metadata in errors:
  - Python: `PartnerApiError.retry_after`
  - Node: `PartnerApiError.retryAfter`
- Added SDK tests:
  - `tests/test_sdk_python_client.py`
  - `sdk/node/index.test.js`
- Added explicit SDK version exports:
  - Python: `SDK_VERSION` and `sdk_version`
  - Node: `SDK_VERSION` and `sdkVersion`
