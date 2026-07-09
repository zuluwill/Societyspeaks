"""AudioStorage contract: S3-backed via storage_utils, filesystem only in dev."""
import app.storage_utils as storage_utils
from app.brief.audio_storage import AudioStorage
from app.lib import deployed_env


def _force_provider(monkeypatch, provider):
    monkeypatch.setattr(storage_utils, '_detect_provider', lambda: provider)


def test_rejects_path_traversal_filenames(monkeypatch):
    storage = AudioStorage()
    for bad in ('', '../etc/passwd', 'a/b.wav', 'a\\b.wav'):
        assert storage.save(b'data', bad) is None
        assert storage.get(bad) is None
        assert storage.delete(bad) is False


def test_s3_provider_routes_through_storage_utils(monkeypatch):
    _force_provider(monkeypatch, 's3')
    calls = {}

    def _fake_upload(key, data):
        calls['upload'] = (key, data)
        return True

    def _fake_download(key):
        calls['download'] = key
        return b'audio-bytes'

    def _fake_delete(key):
        calls['delete'] = key
        return True

    monkeypatch.setattr(storage_utils, 'upload_bytes_to_object_storage', _fake_upload)
    monkeypatch.setattr(storage_utils, 'download_bytes_from_object_storage', _fake_download)
    monkeypatch.setattr(storage_utils, 'delete_bytes_from_object_storage', _fake_delete)

    storage = AudioStorage()
    assert storage.save(b'audio-bytes', 'brief.wav') == '/audio/brief.wav'
    assert storage.get('brief.wav') == b'audio-bytes'
    assert storage.delete('brief.wav') is True

    assert calls['upload'] == ('audio/brief.wav', b'audio-bytes')
    assert calls['download'] == 'audio/brief.wav'
    assert calls['delete'] == 'audio/brief.wav'


def test_production_without_s3_refuses_filesystem(monkeypatch):
    """Never write audio to the ephemeral container disk in production."""
    _force_provider(monkeypatch, 'filesystem')
    monkeypatch.setattr(deployed_env, 'is_deployed_production', lambda: True)

    storage = AudioStorage()
    assert storage.save(b'audio-bytes', 'brief.wav') is None
    assert storage.get('brief.wav') is None
    assert storage.delete('brief.wav') is False


def test_development_falls_back_to_filesystem(monkeypatch, tmp_path):
    _force_provider(monkeypatch, 'filesystem')
    monkeypatch.setattr(deployed_env, 'is_deployed_production', lambda: False)
    monkeypatch.chdir(tmp_path)

    storage = AudioStorage()
    assert storage.save(b'audio-bytes', 'brief.wav') == '/audio/brief.wav'
    assert storage.get('brief.wav') == b'audio-bytes'
    assert storage.delete('brief.wav') is True
    assert storage.get('brief.wav') is None
