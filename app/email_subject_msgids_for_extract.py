"""Register email subject strings for ``pybabel extract``.

Some Resend helpers carry subject copy through parameters (for example ``subject_msgid=``
on ``_send_transactional_email`` or ``subject=`` on ``_send_user_transactional_email``)
before they reach ``gettext`` at send time. The Python extractor does not follow those
indirections, so the same literals are listed here as dead ``gettext`` calls.

Positional ``_subject_for_user(user, '…')`` subjects are picked up automatically via
``keywords = _subject_for_user:2`` in ``babel.cfg`` — do not duplicate those here.

When you add or change a subject in ``app/resend_client.py`` that is not passed
directly as the second argument to ``_subject_for_user``, update this module and run
the usual extract/update workflow (see ``scripts/compile_translations.sh``).

Not executed at runtime; import has no side effects beyond defining this module.
"""

from __future__ import annotations

from flask_babel import gettext

if False:  # pragma: no cover — pybabel extract only (never runs)
    # --- _send_transactional_email(..., subject_msgid=...) -----------------
    gettext("Reset Your Password - Society Speaks")
    gettext("Your Society Speaks sign-in link")
    gettext("Welcome to Society Speaks!")
    gettext("Verify your Society Speaks email address")
    gettext("Activate Your Society Speaks Account")

    # --- _send_user_transactional_email(..., subject third positional) -----
    gettext("We've paused your briefings — come back any time")

    # --- Subjects built as f-strings today (not extractable as static msgids) ---
    # * send_trial_ending_email: day/plural copy is assembled in code.
    # * send_trial_mid_email: days_remaining interpolated in code.
    # Refactor to gettext + placeholders when you want those catalogued.
