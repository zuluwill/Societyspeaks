"""
Briefing Ingestion Module

Handles content extraction from various source types:
- PDF files
- DOCX files
- Web pages
- RSS feeds (via SourceIngester)
"""

from app.briefing.ingestion.pdf_extractor import extract_text_from_pdf
from app.briefing.ingestion.docx_extractor import extract_text_from_docx
from app.briefing.ingestion.webpage_scraper import scrape_webpage

__all__ = ['extract_text_from_pdf', 'extract_text_from_docx', 'scrape_webpage']
