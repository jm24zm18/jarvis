from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_web_install_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "web_install.py"
    spec = importlib.util.spec_from_file_location("web_install_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_failure_network_blocked_or_sandboxed() -> None:
    module = _load_web_install_module()
    category, hints = module._classify_failure(
        "npm ERR! errno EPERM\nnpm ERR! syscall connect\nnpm ERR! connect EPERM 127.0.0.1:9"
    )
    assert category == "network_blocked_or_sandboxed"
    assert any("non-restricted shell" in hint for hint in hints)


def test_extract_npm_debug_log_path() -> None:
    module = _load_web_install_module()
    output = (
        "A complete log of this run can be found in: "
        "/tmp/npm-cache/_logs/2026-02-18T15_08_56_287Z-debug-0.log"
    )
    assert (
        module._extract_npm_debug_log(output)
        == "/tmp/npm-cache/_logs/2026-02-18T15_08_56_287Z-debug-0.log"
    )

