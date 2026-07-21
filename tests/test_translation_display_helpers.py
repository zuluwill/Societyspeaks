"""Contract tests: translation cache dicts must use display helpers, not attribute access."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCUSSION_TEMPLATES = ROOT / 'app' / 'templates' / 'discussions'
PROGRAMME_TEMPLATES = ROOT / 'app' / 'templates' / 'programmes'
INIT_PATH = ROOT / 'app' / '__init__.py'


def _glob_html(directory: Path) -> list[Path]:
    return sorted(directory.glob('**/*.html'))


def test_jinja_globals_register_translation_display_helpers():
    source = INIT_PATH.read_text(encoding='utf-8')
    assert "app.jinja_env.globals['discussion_display_title']" in source
    assert "app.jinja_env.globals['discussion_display_description']" in source
    assert "app.jinja_env.globals['programme_display_name']" in source
    assert "app.jinja_env.globals['programme_display_description']" in source


def test_discussion_templates_do_not_use_raw_translation_attribute_access():
    forbidden = (
        'discussion_translation.title',
        'discussion_translation.description',
        '_tr.title if _tr',
        '_tr.description if _tr',
    )
    for path in _glob_html(DISCUSSION_TEMPLATES):
        source = path.read_text(encoding='utf-8')
        for pattern in forbidden:
            assert pattern not in source, f'{path.name} still uses {pattern!r}'


def test_programme_templates_do_not_use_raw_translation_attribute_access():
    forbidden = (
        'programme_translation.name',
        'programme_translation.description',
        '_op.name if _op',
        '_op.description if _op',
    )
    for path in _glob_html(PROGRAMME_TEMPLATES):
        source = path.read_text(encoding='utf-8')
        for pattern in forbidden:
            assert pattern not in source, f'{path.name} still uses {pattern!r}'
