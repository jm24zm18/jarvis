import asyncio

from jarvis.db.connection import get_conn
from jarvis.tasks.agent import _build_registry


def test_skill_tools_registered_and_operational() -> None:
    with get_conn() as conn:
        registry = _build_registry(
            conn,
            trace_id="trc_skills_tools",
            thread_id="thr_1",
            actor_id="coder",
        )

        schemas = registry.schemas()
        tool_names = {item["name"] for item in schemas}
        assert "skill_list" in tool_names
        assert "skill_read" in tool_names
        assert "skill_write" in tool_names

        write_tool = registry.get("skill_write")
        read_tool = registry.get("skill_read")
        list_tool = registry.get("skill_list")

        assert write_tool is not None
        assert read_tool is not None
        assert list_tool is not None

        first = asyncio.run(
            write_tool.handler(
                {
                    "slug": "workflow-note",
                    "title": "Workflow Note",
                    "content": "Keep commits small",
                    "scope": "global",
                    "pinned": False,
                }
            )
        )
        second = asyncio.run(
            write_tool.handler(
                {
                    "slug": "workflow-note",
                    "title": "Workflow Note",
                    "content": "Coder-specific workflow",
                    "scope": "coder",
                    "pinned": True,
                }
            )
        )

        read_result = asyncio.run(read_tool.handler({"slug": "workflow-note"}))
        list_result = asyncio.run(list_tool.handler({}))
        pinned_result = asyncio.run(list_tool.handler({"pinned_only": True}))

    assert "skill" in first and first["skill"]["scope"] == "global"
    assert "skill" in second and second["skill"]["scope"] == "coder"
    assert read_result["skill"] is not None
    assert read_result["skill"]["scope"] == "coder"
    assert any(item["scope"] == "global" for item in list_result["skills"])
    assert any(item["scope"] == "coder" for item in list_result["skills"])
    assert len(pinned_result["skills"]) == 1
    assert pinned_result["skills"][0]["scope"] == "coder"
