"""Render a report as a PDF.

WeasyPrint needs system libraries (Pango) that the production image installs.
Where they are missing, ``render_report_pdf`` returns None and the report page
offers the browser's print-to-PDF instead.
"""
import logging
import os
import secrets
from typing import Optional
from urllib.parse import unquote, urlparse

from flask import current_app, render_template

from app import db
from app.storage_utils import download_bytes_from_object_storage, upload_bytes_to_object_storage

logger = logging.getLogger(__name__)


def _weasyprint():
    try:
        import weasyprint
        return weasyprint
    except Exception:  # ImportError, or OSError when Pango is not installed
        return None


def _refuse_unless_local(url: str, static_root: str) -> None:
    """Raise unless ``url`` is inline data or a file inside our static folder."""
    parsed = urlparse(url)
    if parsed.scheme == 'data':
        return
    if parsed.scheme == 'file':
        path = os.path.realpath(unquote(parsed.path))
        if os.path.commonpath([static_root, path]) == static_root:
            return
    raise ValueError(f'Refused to fetch a {parsed.scheme or "relative"} URL while rendering a report')


def _local_files_only(weasyprint):
    """A URL fetcher for the report. It is built from our own template and
    stylesheet, so nothing in it may make the server fetch an address,
    whatever the text contains."""
    static_root = os.path.realpath(current_app.static_folder)

    class LocalFilesOnly(weasyprint.urls.URLFetcher):
        def fetch(self, url, headers=None):
            _refuse_unless_local(url, static_root)
            return super().fetch(url, headers)

    return LocalFilesOnly(allowed_protocols=('file', 'data'), allow_redirects=False)


def pdf_rendering_available() -> bool:
    return _weasyprint() is not None


def render_report_pdf(report) -> Optional[bytes]:
    weasyprint = _weasyprint()
    if weasyprint is None:
        return None
    from app.consultations.report import report_view_context

    from flask_babel import get_locale

    html = render_template(
        'consultations/report_pdf.html',
        # Rendered outside a request, under the host's forced locale.
        current_lang=str(get_locale() or 'en'),
        **report_view_context(
            report.data, report.narrative, report.narrative_source,
            is_interim=report.kind == report.KIND_INTERIM,
        ),
    )
    return weasyprint.HTML(
        string=html, base_url=current_app.static_folder, url_fetcher=_local_files_only(weasyprint),
    ).write_pdf()


def report_pdf(report) -> Optional[bytes]:
    """The report's PDF, rendering and storing it on first use."""
    if report.pdf_storage_key:
        stored = download_bytes_from_object_storage(report.pdf_storage_key)
        if stored:
            return stored
    pdf = render_report_pdf(report)
    if pdf is None:
        return None
    # Unguessable: the key is the only thing protecting the file in storage.
    key = f'consultations/reports/{report.id}-{secrets.token_hex(16)}.pdf'
    if upload_bytes_to_object_storage(key, pdf):
        report.pdf_storage_key = key
        db.session.commit()
    return pdf
