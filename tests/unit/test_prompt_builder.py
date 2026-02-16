from jarvis.orchestrator.prompt_builder import (
    build_prompt,
    build_prompt_parts,
    build_prompt_with_report,
)


def test_prompt_builder_includes_sections_within_budget() -> None:
    prompt = build_prompt(
        system_context="system",
        summary_short="short",
        summary_long="long",
        memory_chunks=["m1", "m2"],
        tail=["user: hi", "assistant: hello"],
        token_budget=200,
        max_memory_items=2,
    )
    assert "[system]" in prompt
    assert "[summary.short]" in prompt
    assert "[summary.long]" in prompt
    assert "[context]" in prompt
    assert "[tail]" in prompt


def test_prompt_builder_clips_when_budget_tiny() -> None:
    prompt = build_prompt(
        system_context="x" * 1000,
        summary_short="y" * 1000,
        summary_long="z" * 1000,
        memory_chunks=["m" * 1000],
        tail=["u" * 1000],
        token_budget=8,
        max_memory_items=1,
    )
    assert len(prompt) > 0
    assert "…" in prompt


def test_build_prompt_parts_splits_system_and_user() -> None:
    system_part, user_part = build_prompt_parts(
        system_context="system-context",
        summary_short="short",
        summary_long="long",
        memory_chunks=["m1"],
        tail=["user: hi"],
        token_budget=200,
        max_memory_items=1,
    )
    assert "system-context" in system_part
    assert "## Tooling" in system_part
    assert "[summary.short]" in user_part
    assert "[tail]" in user_part


def test_build_prompt_with_report_includes_section_metrics() -> None:
    _system, _user, report = build_prompt_with_report(
        system_context="system-context",
        summary_short="short",
        summary_long="long",
        memory_chunks=["ctx1", "ctx2"],
        tail=["user: hi", "assistant: hello"],
        token_budget=120,
        max_memory_items=2,
        prompt_mode="full",
        available_tools=[{"name": "echo", "description": "Echo text"}],
        skill_catalog=[{"slug": "jarvis-project", "title": "Jarvis Project", "pinned": True}],
    )
    assert report["prompt_mode"] == "full"
    sections = report["sections"]
    assert isinstance(sections, dict)
    assert "summary.short" in sections
    assert "tail" in sections
