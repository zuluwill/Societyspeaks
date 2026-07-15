"""
Structural guard: every brief-producing scheduler path must call the shared
brief→question wiring helper (prevents side-door dormancy).
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_PATH = REPO_ROOT / 'app' / 'scheduler.py'

REQUIRED_WIRE_LABELS = (
    'primary_skip',
    'primary_generate',
    'safety_net_1_skip',
    'safety_net_1_generate',
    'safety_net_1_heal',
    'safety_net_2_skip',
    'safety_net_2_generate',
    'safety_net_2_heal',
    'emergency_skip_published',
    'emergency_generate',
)


def test_scheduler_brief_paths_all_wire_tomorrow_question():
    source = SCHEDULER_PATH.read_text(encoding='utf-8')
    assert '_wire_daily_question_after_brief(' in source
    for label in REQUIRED_WIRE_LABELS:
        assert f"'{label}'" in source, (
            f"scheduler.py missing _wire_daily_question_after_brief(..., '{label}')"
        )


def test_wire_helper_delegates_to_auto_selection():
    source = SCHEDULER_PATH.read_text(encoding='utf-8')
    assert 'wire_tomorrow_question_from_brief' in source
