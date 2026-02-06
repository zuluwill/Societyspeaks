"""
Partner embed constants.

Single source of truth for theme presets and allowed fonts used by:
- Partner hub embed generator (theme picker)
- Embed route (theme styling, font allowlist)
"""
# Theme presets: generic styles that work for any publisher.
# 'primary' and 'bg' are hex without #. 'font' is a CSS font-family hint (empty = system default).
EMBED_THEMES = [
    {'id': 'default',   'name': 'Default',   'primary': '1e40af', 'bg': 'ffffff', 'font': ''},
    {'id': 'dark',      'name': 'Dark',      'primary': '60a5fa', 'bg': '1a1a2e', 'font': ''},
    {'id': 'editorial', 'name': 'Editorial', 'primary': '0d1b2a', 'bg': 'fdf6e3', 'font': 'Georgia'},
    {'id': 'minimal',   'name': 'Minimal',   'primary': '000000', 'bg': 'ffffff', 'font': ''},
    {'id': 'bold',      'name': 'Bold',      'primary': 'dc2626', 'bg': 'ffffff', 'font': ''},
    {'id': 'muted',     'name': 'Muted',     'primary': '475569', 'bg': 'f8fafc', 'font': ''},
]

# Fonts allowed for embed custom theming (plan §3.5a: web-safe + named fonts)
EMBED_ALLOWED_FONTS = [
    'system-ui',
    'Georgia',
    'Inter',
    'Lato',
    'Open Sans',
    'Source Serif Pro',
    'sans-serif',
    'serif',
]
