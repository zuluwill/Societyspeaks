import os

from cachelib.file import FileSystemCache
from flask_session.cachelib import CacheLibSessionInterface


def test_create_app_uses_cachelib_session_fallback(tmp_path):
    from config import Config

    original_uri = Config.SQLALCHEMY_DATABASE_URI
    original_engine = Config.SQLALCHEMY_ENGINE_OPTIONS
    original_ratelimit_url = getattr(Config, "RATELIMIT_STORAGE_URL", None)
    original_ratelimit_uri = getattr(Config, "RATELIMIT_STORAGE_URI", None)
    original_session_type = Config.SESSION_TYPE
    original_session_redis = getattr(Config, "SESSION_REDIS", None)
    original_session_cachelib = getattr(Config, "SESSION_CACHELIB", None)
    original_flask_env = os.environ.get("FLASK_ENV")

    Config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    Config.SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    Config.RATELIMIT_STORAGE_URL = "memory://"
    Config.RATELIMIT_STORAGE_URI = "memory://"
    Config.SESSION_TYPE = "cachelib"
    Config.SESSION_REDIS = None
    Config.SESSION_CACHELIB = FileSystemCache(cache_dir=str(tmp_path / "flask_session"))
    os.environ["FLASK_ENV"] = "development"

    try:
        from app import create_app

        app = create_app()

        assert app.config["SESSION_TYPE"] == "cachelib"
        assert isinstance(app.config["SESSION_CACHELIB"], FileSystemCache)
        assert isinstance(app.session_interface, CacheLibSessionInterface)
    finally:
        Config.SQLALCHEMY_DATABASE_URI = original_uri
        Config.SQLALCHEMY_ENGINE_OPTIONS = original_engine
        Config.RATELIMIT_STORAGE_URL = original_ratelimit_url
        Config.RATELIMIT_STORAGE_URI = original_ratelimit_uri
        Config.SESSION_TYPE = original_session_type
        Config.SESSION_REDIS = original_session_redis
        Config.SESSION_CACHELIB = original_session_cachelib
        if original_flask_env is None:
            os.environ.pop("FLASK_ENV", None)
        else:
            os.environ["FLASK_ENV"] = original_flask_env
