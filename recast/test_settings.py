"""Isolated local checks; never import deployment credentials or services."""
import atexit
import secrets
import sys
import tempfile
from pathlib import Path
from types import ModuleType

_test_directory = tempfile.TemporaryDirectory(prefix="recast-tests-")
atexit.register(_test_directory.cleanup)
_test_root = Path(_test_directory.name)
_server = ModuleType("recast.server_settings")
_server.DEBUG = False
_server.SECRET_KEY = secrets.token_urlsafe(48)
_server.ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
_server.DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": str(_test_root / "db.sqlite3")}}
_server.STATIC_ROOT = str(_test_root / "static")
_server.CLOUDFLARE_TOKEN = None
_server.CLOUDFLARE_ZONE = None
_server.FEEDS_SERVER = "http://testserver"
_server.FEEDS_CLOUDFLARE_WORKER = None
sys.modules["recast.server_settings"] = _server

from recast.settings import *  # noqa: E402,F403

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "recast-tests"}}
MEDIA_ROOT = str(_test_root / "media")
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
