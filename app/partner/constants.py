"""
Partner embed constants.

Single source of truth for theme presets and allowed fonts used by:
- Partner hub embed generator (theme picker)
- Embed route (theme styling, font allowlist)
"""
# Theme presets for embed and generator (id, display name, primary hex for generator swatch)
EMBED_THEMES = [
    {'id': 'default', 'name': 'Society Speaks', 'primary': '1e40af'},
    {'id': 'observer', 'name': 'Observer', 'primary': '000000'},
    {'id': 'time', 'name': 'TIME', 'primary': 'e90606'},
    {'id': 'ted', 'name': 'TED', 'primary': 'e62b1e'},
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
