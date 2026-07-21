# Fonts for the OG share cards

Social share cards (`/discussions/<id>/og.png`, `/daily/<date>/og.png`,
`/brief/<date>/og.png`, `/profile/.../og.png`, and the Tradeoffs game card) are
rendered with Pillow by `app/lib/og_card_render.py`.

## Bundled fonts (committed here, OFL-licensed)

| File | Used for | Source |
|------|----------|--------|
| `Fraunces.ttf` | Headlines / wordmark (loaded as **Bold**) | https://fonts.google.com/specimen/Fraunces — OFL |
| `Inter.ttf` | Badge, footer, vote-bar labels (Medium / SemiBold) | https://fonts.google.com/specimen/Inter — OFL |

Both are **variable** fonts; the renderer selects the weight at load time via
`ImageFont.set_variation_by_name(...)`. The OFL permits shipping them in the repo.

## Fallback chain (used automatically if the bundled files are missing)

Display (Fraunces) → Georgia (macOS) → DejaVuSerif-Bold (Linux) → PIL default
Body (Inter) → Helvetica Neue (macOS) → DejaVu Sans (Linux) → PIL default

PIL's default is a crude bitmap font — the fallbacks exist only so the route
never 500s. Keep the bundled `.ttf` files in place for brand-correct output.

## Notes

- OG PNGs are cached (Redis + HTTP). After a font/design change, bump the cache
  or `redis-cli FLUSHDB` to invalidate stale renders during testing.
- Local rendering needs a working Pillow. If your local Pillow wheel is the wrong
  architecture, the render tests skip visibly rather than fail.
