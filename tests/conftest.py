import os
from pathlib import Path

import pytest

from jarvis.channels.registry import _reset as _reset_channels
from jarvis.channels.registry import register_channel
from jarvis.channels.whatsapp.adapter import WhatsAppAdapter
from jarvis.config import get_settings
from jarvis.db.migrations.runner import run_migrations


@pytest.fixture(autouse=True)
def test_env(tmp_path: Path):
    db = tmp_path / "test.db"
    patch_dir = tmp_path / "patches"
    os.environ["APP_DB"] = str(db)
    os.environ["SELFUPDATE_PATCH_DIR"] = str(patch_dir)
    os.environ["WHATSAPP_VERIFY_TOKEN"] = "test-token"
    os.environ["EVOLUTION_API_URL"] = ""
    os.environ["WHATSAPP_AUTO_CREATE_ON_STARTUP"] = "0"
    os.environ["MAINTENANCE_ENABLED"] = "0"
    get_settings.cache_clear()
    run_migrations()
    _reset_channels()
    register_channel(WhatsAppAdapter())
    yield
    get_settings.cache_clear()
    _reset_channels()
