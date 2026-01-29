# Security (open-source repo)

This repo is public. Keep it safe by never committing:

- **Secrets**: `.env`, `.env.local`, or any file with real API keys, passwords, or tokens
- **Session data**: `flask_session/` is gitignored; do not add it
- **Internal docs**: `docs/` is gitignored (planning, credentials guides, strategy)

Use **environment variables** for all secrets. See `.env.brief.example` for required vars (placeholders only—no real values).

**Production:** Set `SECRET_KEY`, `DATABASE_URL`, and all API keys in your environment. Do not rely on config defaults (e.g. `SECRET_KEY='dev'`).

To report a vulnerability, contact the maintainers privately (e.g. via GitHub Security Advisories or the contact email in the repo).
