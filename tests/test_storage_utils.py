"""Tests for object-storage provider helpers (no live S3/Replit required)."""
import os

import pytest

from app import storage_utils as su


@pytest.fixture(autouse=True)
def _reset_storage_provider(monkeypatch):
    su._provider = None
    su._s3_client = None
    su._replit_client = None
    # Force filesystem provider for unit tests
    monkeypatch.delenv('AWS_ACCESS_KEY_ID', raising=False)
    monkeypatch.delenv('AWS_SECRET_ACCESS_KEY', raising=False)
    monkeypatch.delenv('AWS_S3_BUCKET', raising=False)
    monkeypatch.delenv('REPL_ID', raising=False)
    monkeypatch.delenv('REPLIT_DB_URL', raising=False)
    yield
    su._provider = None
    su._s3_client = None
    su._replit_client = None


def test_filesystem_fallback_serves_repo_hero_image():
    data = su.download_bytes_from_object_storage('static_assets/images/hero-optimized.jpg')
    assert data is not None
    assert len(data) > 1000
    assert data[:2] == b'\xff\xd8'  # JPEG SOI


def test_filesystem_rejects_path_traversal():
    assert su.download_bytes_from_object_storage('static_assets/images/../../config.py') is None


def test_detect_provider_prefers_s3_when_configured(monkeypatch):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'AKIATEST')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'secret')
    monkeypatch.setenv('AWS_S3_BUCKET', 'societyspeaks-assets')
    su._provider = None
    assert su._detect_provider() == 's3'
