from jarvis.rlm.config import RLMConfig
from jarvis.rlm.decomposer import (
    build_decompose_prompt,
    build_repair_prompt,
    compute_run_hash,
    parse_decompose_result,
    select_context_files,
    validate_plan,
)

_VALID_PATHS = [
    "src/jarvis/tasks/feature_build_layer_0.py",
    "src/jarvis/tasks/feature_build_layer_1.py",
    "src/jarvis/tasks/feature_build_layer_2.py",
]


def _test_rlm_config() -> RLMConfig:
    return RLMConfig(
        feature_build_use_rlm=True,
        rlm_enabled=True,
        context_files_limit=3,
        context_token_limit=2000,
        prompt_token_limit=2000,
        validation_attempts=2,
        max_attempts=2,
        max_refinements=1,
        timeout_s=10,
        budget_per_1k_tokens=0.0,
    )


def test_select_context_files_prefers_anchors():
    config = _test_rlm_config()
    description = "Update src/jarvis/tasks/feature_build.py to handle foo"
    files = select_context_files(description, config)
    assert any("feature_build.py" in cf.path for cf in files)


def test_build_decompose_prompt_includes_context():
    config = _test_rlm_config()
    context_files = select_context_files("feature build", config)
    prompt, allowed = build_decompose_prompt("Title", "Description", context_files)
    assert "Title" in prompt
    assert "Description" in prompt
    assert "- " in prompt
    assert allowed == [cf.path for cf in context_files]


def test_parse_decompose_result_accepts_fenced_json():
    raw = "Some text\n```json\n{\"subtasks\":[]}\n```\nExtra"
    parsed, snippet = parse_decompose_result(raw)
    assert parsed == {"subtasks": []}
    assert snippet.strip().startswith("{")


def test_validate_plan_fails_invalid_plan():
    errors, normalized = validate_plan(
        {
            "subtasks": [
                {
                    "title": "",
                    "description": "x",
                    "acceptance_criteria": "test",
                    "target_files": ["foo"],
                    "estimated_lines": 5,
                }
            ]
        },
        allowed_paths=[],
    )
    assert errors
    assert not normalized


def test_validate_plan_success():
    plan = {
        "subtasks": [
            {
                "title": f"A{i}",
                "description": "Do work",
                "acceptance_criteria": "Add tests",
                "target_files": [path],
                "estimated_lines": 10,
            }
            for i, path in enumerate(_VALID_PATHS)
        ]
    }
    errors, normalized = validate_plan(plan, allowed_paths=_VALID_PATHS)
    assert not errors
    assert len(normalized) == 3


def test_build_repair_prompt_mentions_errors_and_previous_json():
    prompt = build_repair_prompt('{"subtasks": []}', ["missing subtasks"], ["foo"])
    assert "missing subtasks" in prompt
    assert '"subtasks": []' in prompt


def test_compute_run_hash_is_deterministic():
    config = _test_rlm_config()
    context_files = select_context_files("feature build", config)
    hash1 = compute_run_hash("feat", "desc", context_files)
    hash2 = compute_run_hash("feat", "desc", context_files)
    assert hash1 == hash2
