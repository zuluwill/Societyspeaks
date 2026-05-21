# Society Play — fonts for the OG share card

The PNG OG card (`/play/outcome/<uuid>/og.png`) is rendered with Pillow. It
looks for these fonts in order, falling back to the next candidate when one is
missing — so the route always works, but the typography degrades when the
preferred faces aren't present.

## Drop these files here for full brand fidelity

| Filename | Used for | Source |
|----------|----------|--------|
| `Fraunces-Bold.ttf` | Outcome headline, `Tradeoffs` wordmark | https://fonts.google.com/specimen/Fraunces — OFL, free for redistribution |
| `Inter-Medium.ttf` | Governance label, society name, footer URL | https://fonts.google.com/specimen/Inter — OFL, free for redistribution |

Both are downloadable as static `.ttf` files from Google Fonts. The OFL
license permits shipping them in the repo.

## Fallback chain (used automatically when the preferred fonts are missing)

Display (Fraunces) → Georgia (macOS) → DejaVuSerif-Bold (Linux/Replit) → PIL default
Body (Inter) → Helvetica Neue / Helvetica (macOS) → DejaVu Sans (Linux) → PIL default

PIL's default font is bitmap-only and looks crude — fine for dev, replace
before launch.

## Verification

After adding the files, the next render will pick them up automatically (no
restart needed — Pillow re-reads on each render). The OG card is cached for
7 days in Redis keyed by `run_uuid`; bump the cache prefix or call
`redis-cli FLUSHDB` if you need to invalidate after a font swap during testing.
