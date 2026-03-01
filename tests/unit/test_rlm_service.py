import asyncio

from jarvis.config import get_settings
from jarvis.rlm.decomposer import ContextFile
from jarvis.rlm.service import AsyncRLMService

_VALID_PATHS = [
    "src/jarvis/tasks/feature_build_layer_0.py",
    "src/jarvis/tasks/feature_build_layer_1.py",
    "src/jarvis/tasks/feature_build_layer_2.py",
]


class _DummyResponse:
    def __init__(self, text: str):
        self.text = text


def _make_context() -> list[ContextFile]:
    return [
        ContextFile(
            path=path,
            content="def foo():\n    pass\n",
            reason="test",
            tokens=1,
        )
        for path in _VALID_PATHS
    ]


def _valid_plan() -> str:
    subtasks = [
        {
            "title": f"Task {idx}",
            "description": "Implementation",
            "acceptance_criteria": "Add tests",
            "target_files": [path],
            "estimated_lines": 5,
        }
        for idx, path in enumerate(_VALID_PATHS)
    ]
    return '{"subtasks": ' + str(subtasks).replace("'", '"') + "}"


def test_service_success(monkeypatch):
    service = AsyncRLMService(get_settings())
    async def stub_generate(*args, **kwargs):
        return _DummyResponse(_valid_plan()), "primary", None

    monkeypatch.setattr("jarvis.rlm.service.ProviderRouter.generate", stub_generate)
    result = asyncio.run(service.decompose("feat", "title", "desc", _make_context()))
    assert result["status"] == "success"
    assert len(result["subtasks"]) == 3
    assert result["attempts"] == 1


def test_service_timeout(monkeypatch):
    service = AsyncRLMService(get_settings())

    async def stub_generate(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("jarvis.rlm.service.ProviderRouter.generate", stub_generate)
    result = asyncio.run(service.decompose("feat", "title", "desc", _make_context()))
    assert result["status"] == "timeout"
    assert result["error"] == "rlm_decompose_timeout"


def test_service_repair(monkeypatch):
    service = AsyncRLMService(get_settings())
    calls = []

    async def stub_generate(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return _DummyResponse("not json"), "primary", None
        return _DummyResponse(_valid_plan()), "primary", None

    monkeypatch.setattr("jarvis.rlm.service.ProviderRouter.generate", stub_generate)
    result = asyncio.run(service.decompose("feat", "title", "desc", _make_context()))
    assert result["status"] == "success"
    assert result["attempts"] == 2
