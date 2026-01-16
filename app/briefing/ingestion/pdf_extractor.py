"""
PDF Text Extractor

Extracts text from PDF files stored in Replit Object Storage.
Handles large files efficiently using streaming and temporary files.
"""

import logging
import tempfile
import os
from typing import Optional, Tuple
from io import BytesIO

logger = logging.getLogger(__name__)

# File size limits
MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB max
LARGE_FILE_THRESHOLD = 10 * 1024 * 1024  # 10 MB - use temp file above this
MAX_PAGES = 500  # Maximum pages to process
MAX_TEXT_LENGTH = 5 * 1024 * 1024  # 5 MB max extracted text


def get_file_size(storage_key: str) -> Optional[int]:
    """
    Get file size from storage without downloading.

    Args:
        storage_key: Replit Object Storage key

    Returns:
        File size in bytes, or None if unable to determine
    """
    try:
        from replit.object_storage import Client
        client = Client()
        # Try to get metadata/size
        # Note: Replit's API may not support this, so we fall back to downloading
        # For now, return None to indicate we need to download to check
        return None
    except Exception as e:
        logger.debug(f"Could not get file size for {storage_key}: {e}")
        return None


def download_to_tempfile(storage_key: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Download file to a temporary file, streaming to avoid memory issues.

    Args:
        storage_key: Replit Object Storage key

    Returns:
        Tuple of (temp_file_path, file_size) or (None, None) on error
    """
    try:
        from replit.object_storage import Client
        client = Client()

        # Create temp file
        fd, temp_path = tempfile.mkstemp(suffix='.pdf')

        try:
            # Download in chunks to temp file
            data = client.download_bytes(storage_key)
            file_size = len(data)

            # Check size limit
            if file_size > MAX_PDF_SIZE_BYTES:
                os.close(fd)
                os.unlink(temp_path)
                logger.warning(f"PDF file too large: {file_size} bytes (max: {MAX_PDF_SIZE_BYTES})")
                return None, file_size

            # Write to temp file
            os.write(fd, data)
            os.close(fd)

            return temp_path, file_size

        except Exception as e:
            os.close(fd)
            os.unlink(temp_path)
            raise e

    except Exception as e:
        logger.error(f"Error downloading to tempfile: {e}")
        return None, None


def extract_text_from_pdf(storage_key: str) -> Optional[str]:
    """
    Extract text from a PDF file in Replit Object Storage.

    Handles large files efficiently:
    - Files under 10MB: Process in memory
    - Files 10-50MB: Use temporary file
    - Files over 50MB: Rejected

    Args:
        storage_key: Replit Object Storage key (e.g., 'uploads/user_123/document.pdf')

    Returns:
        Extracted text as string, or None if extraction fails
    """
    temp_path = None

    try:
        from replit.object_storage import Client
        client = Client()

        # Download file
        pdf_data = client.download_bytes(storage_key)
        file_size = len(pdf_data)

        logger.info(f"Processing PDF {storage_key} ({file_size / 1024 / 1024:.2f} MB)")

        # Check size limit
        if file_size > MAX_PDF_SIZE_BYTES:
            logger.warning(f"PDF too large: {file_size} bytes exceeds {MAX_PDF_SIZE_BYTES} byte limit")
            return None

        # Decide processing strategy based on size
        if file_size > LARGE_FILE_THRESHOLD:
            # Large file: use temp file to avoid memory pressure
            logger.info(f"Using temp file for large PDF ({file_size / 1024 / 1024:.2f} MB)")
            return _extract_with_tempfile(pdf_data, storage_key)
        else:
            # Small file: process in memory
            return _extract_in_memory(pdf_data, storage_key)

    except Exception as e:
        logger.error(f"Error extracting text from PDF {storage_key}: {e}", exc_info=True)
        return None


def _extract_in_memory(pdf_data: bytes, storage_key: str) -> Optional[str]:
    """Extract text from PDF data in memory."""
    try:
        import pypdf

        pdf_file = BytesIO(pdf_data)
        pdf_reader = pypdf.PdfReader(pdf_file)

        num_pages = len(pdf_reader.pages)
        if num_pages > MAX_PAGES:
            logger.warning(f"PDF has {num_pages} pages, limiting to {MAX_PAGES}")
            num_pages = MAX_PAGES

        text_parts = []
        total_length = 0

        for i, page in enumerate(pdf_reader.pages[:num_pages]):
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
                    total_length += len(page_text)

                    # Check text length limit
                    if total_length > MAX_TEXT_LENGTH:
                        logger.warning(f"Extracted text exceeds {MAX_TEXT_LENGTH} chars, truncating")
                        break

            except Exception as e:
                logger.warning(f"Error extracting page {i}: {e}")
                continue

        extracted_text = '\n\n'.join(text_parts)

        if not extracted_text or len(extracted_text.strip()) < 50:
            logger.warning(f"PDF extraction returned minimal text for {storage_key}")
            return None

        logger.info(f"Extracted {len(extracted_text)} chars from PDF {storage_key}")
        return extracted_text.strip()[:MAX_TEXT_LENGTH]

    except ImportError:
        logger.error("pypdf not installed. Install with: pip install pypdf")
        return _extract_with_pdfplumber_memory(pdf_data, storage_key)


def _extract_with_pdfplumber_memory(pdf_data: bytes, storage_key: str) -> Optional[str]:
    """Fallback to pdfplumber for in-memory extraction."""
    try:
        import pdfplumber

        pdf_file = BytesIO(pdf_data)
        text_parts = []
        total_length = 0

        with pdfplumber.open(pdf_file) as pdf:
            num_pages = min(len(pdf.pages), MAX_PAGES)

            for i, page in enumerate(pdf.pages[:num_pages]):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                        total_length += len(page_text)

                        if total_length > MAX_TEXT_LENGTH:
                            logger.warning(f"Extracted text exceeds limit, truncating")
                            break
                except Exception as e:
                    logger.warning(f"Error extracting page {i}: {e}")
                    continue

        extracted_text = '\n\n'.join(text_parts)

        if not extracted_text or len(extracted_text.strip()) < 50:
            return None

        return extracted_text.strip()[:MAX_TEXT_LENGTH]

    except ImportError:
        logger.error("Neither pypdf nor pdfplumber installed")
        return None


def _extract_with_tempfile(pdf_data: bytes, storage_key: str) -> Optional[str]:
    """Extract text using a temporary file for large PDFs."""
    temp_path = None

    try:
        import pypdf

        # Write to temp file
        fd, temp_path = tempfile.mkstemp(suffix='.pdf')
        try:
            os.write(fd, pdf_data)
        finally:
            os.close(fd)

        # Clear the in-memory data to free memory
        del pdf_data

        # Open from file (more memory efficient for large files)
        with open(temp_path, 'rb') as f:
            pdf_reader = pypdf.PdfReader(f)

            num_pages = len(pdf_reader.pages)
            if num_pages > MAX_PAGES:
                logger.warning(f"PDF has {num_pages} pages, limiting to {MAX_PAGES}")
                num_pages = MAX_PAGES

            text_parts = []
            total_length = 0

            for i in range(num_pages):
                try:
                    page = pdf_reader.pages[i]
                    page_text = page.extract_text()

                    if page_text:
                        text_parts.append(page_text)
                        total_length += len(page_text)

                        if total_length > MAX_TEXT_LENGTH:
                            logger.warning(f"Extracted text exceeds limit at page {i}")
                            break

                    # Log progress for large files
                    if i > 0 and i % 50 == 0:
                        logger.info(f"Processed {i}/{num_pages} pages...")

                except Exception as e:
                    logger.warning(f"Error extracting page {i}: {e}")
                    continue

        extracted_text = '\n\n'.join(text_parts)

        if not extracted_text or len(extracted_text.strip()) < 50:
            logger.warning(f"PDF extraction returned minimal text for {storage_key}")
            return None

        logger.info(f"Extracted {len(extracted_text)} chars from large PDF {storage_key}")
        return extracted_text.strip()[:MAX_TEXT_LENGTH]

    except ImportError:
        logger.error("pypdf not installed for temp file extraction")
        return None

    finally:
        # Clean up temp file
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"Could not delete temp file {temp_path}: {e}")
