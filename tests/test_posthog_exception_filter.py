"""Guard the PostHog before_send exception filter in layout.html.

The Outlook / Office WebView rejection is captured on $exception_list and
$exception_values. A filter that only reads $exception_message never matches
and lets thousands of events through.
"""

from pathlib import Path

LAYOUT = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'layout.html'


def test_posthog_before_send_reads_exception_list_and_values():
    source = LAYOUT.read_text(encoding='utf-8')
    assert 'before_send:' in source
    assert 'props.$exception_list' in source
    assert 'props.$exception_values' in source
    assert 'Object Not Found Matching Id' in source
    assert 'MethodName:update' in source
    assert 'Script error' in source
