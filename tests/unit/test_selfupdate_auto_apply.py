"""Tests for SELFUPDATE_AUTO_APPLY_DEV/PROD config wiring behavior."""

import os

from jarvis.config import get_settings


def test_selfupdate_auto_apply_dev_default_is_enabled() -> None:
    """Default: SELFUPDATE_AUTO_APPLY_DEV=1 means auto-apply is on in dev."""
    os.environ.pop("SELFUPDATE_AUTO_APPLY_DEV", None)
    get_settings.cache_clear()
    settings = get_settings()
    assert int(settings.selfupdate_auto_apply_dev) == 1


def test_selfupdate_auto_apply_prod_default_is_disabled() -> None:
    """Default: SELFUPDATE_AUTO_APPLY_PROD=0 means prod requires approval."""
    os.environ.pop("SELFUPDATE_AUTO_APPLY_PROD", None)
    get_settings.cache_clear()
    settings = get_settings()
    assert int(settings.selfupdate_auto_apply_prod) == 0


def test_selfupdate_auto_apply_dev_can_be_disabled() -> None:
    """SELFUPDATE_AUTO_APPLY_DEV=0 means dev will require approval too."""
    os.environ["SELFUPDATE_AUTO_APPLY_DEV"] = "0"
    get_settings.cache_clear()
    settings = get_settings()
    # Logic: requires_approval = int(settings.selfupdate_auto_apply_dev) != 1
    assert int(settings.selfupdate_auto_apply_dev) != 1


def test_selfupdate_auto_apply_prod_can_be_enabled() -> None:
    """SELFUPDATE_AUTO_APPLY_PROD=1 means prod skips approval (opt-in)."""
    os.environ["SELFUPDATE_AUTO_APPLY_PROD"] = "1"
    get_settings.cache_clear()
    settings = get_settings()
    # Logic: requires_approval = int(settings.selfupdate_auto_apply_prod) != 1
    assert int(settings.selfupdate_auto_apply_prod) == 1


def test_requires_approval_logic_dev() -> None:
    """Verify the logic expression used in self_update_apply for dev env."""
    # requires_approval = int(settings.selfupdate_auto_apply_dev) != 1
    for value, expected_requires in [("0", True), ("1", False)]:
        os.environ["SELFUPDATE_AUTO_APPLY_DEV"] = value
        get_settings.cache_clear()
        settings = get_settings()
        requires_approval = int(settings.selfupdate_auto_apply_dev) != 1
        assert requires_approval is expected_requires, (
            f"DEV={value} → requires_approval={requires_approval}, expected {expected_requires}"
        )


def test_requires_approval_logic_prod() -> None:
    """Verify the logic expression used in self_update_apply for prod env."""
    # requires_approval = int(settings.selfupdate_auto_apply_prod) != 1
    for value, expected_requires in [("0", True), ("1", False)]:
        os.environ["SELFUPDATE_AUTO_APPLY_PROD"] = value
        get_settings.cache_clear()
        settings = get_settings()
        requires_approval = int(settings.selfupdate_auto_apply_prod) != 1
        assert requires_approval is expected_requires, (
            f"PROD={value} → requires_approval={requires_approval}, expected {expected_requires}"
        )
