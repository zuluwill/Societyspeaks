# Security (open-source repo)

This repo is public. Keep it safe by never committing:

- **Secrets**: `.env`, `.env.local`, or any file with real API keys, passwords, or tokens
- **Session data**: `flask_session/` is gitignored; do not add it
- **Internal docs**: `docs/` is gitignored (planning, credentials guides, strategy)

Use **environment variables** for all secrets. See `.env.brief.example` for required vars (placeholders only - no real values).

**Production:** Set `SECRET_KEY`, `DATABASE_URL`, and all API keys in your environment. Do not rely on config defaults (for example `SECRET_KEY='dev'`).

## Reporting a Vulnerability

Please do not open public issues for security vulnerabilities.

Report privately using:

1. GitHub Security Advisories (preferred):
   - https://github.com/zuluwill/Societyspeaks/security/advisories/new
2. Private maintainer contact listed in project documentation.

## Response Targets

- Initial response target: within 72 hours
- Status update target: within 7 days

Society Speaks is currently maintained by a single maintainer, so timelines are best-effort but taken seriously.
