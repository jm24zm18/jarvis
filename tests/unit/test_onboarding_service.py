import asyncio
import json
from pathlib import Path

from jarvis.db.connection import get_conn
from jarvis.db.queries import create_thread, ensure_channel, ensure_user
from jarvis.onboarding.service import maybe_handle_onboarding_message, reset_onboarding_state
from jarvis.providers.base import ModelResponse


class _FakeRouter:
    def __init__(self, responses: list[ModelResponse]) -> None:
        self._responses = responses
        self.calls = 0
        self.messages_by_call: list[list[dict[str, str]]] = []

    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del tools, temperature, max_tokens, priority
        self.messages_by_call.append(messages)
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx], "primary", None


class _ErrorRouter:
    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, object]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        priority: str = "normal",
    ) -> tuple[ModelResponse, str, str | None]:
        del messages, tools, temperature, max_tokens, priority
        raise RuntimeError("quota exceeded 429")


def _identity_md(agent_id: str, allowed_tools: list[str], title: str) -> str:
    tools_lines = "\n".join(f"  - {tool}" for tool in allowed_tools)
    return (
        "---\n"
        f"agent_id: {agent_id}\n"
        "allowed_tools:\n"
        f"{tools_lines}\n"
        "---\n\n"
        f"# {title}\n"
    )


def _valid_finalize_args() -> dict[str, object]:
    return {
        "assistant_name": "Friday",
        "user_name": "Justin",
        "agents": {
            "main": {
                "identity_md": _identity_md(
                    "main",
                    [
                        "echo",
                        "session_list",
                        "session_history",
                        "session_send",
                        "web_search",
                        "exec_host",
                        "skill_list",
                        "skill_read",
                        "skill_write",
                        "update_persona",
                    ],
                    "Friday Main Agent",
                ),
                "soul_md": "# Main Soul\n",
            },
            "researcher": {
                "identity_md": _identity_md(
                    "researcher",
                    [
                        "echo",
                        "web_search",
                        "session_send",
                        "skill_list",
                        "skill_read",
                        "skill_write",
                    ],
                    "Researcher Agent",
                ),
                "soul_md": "# Researcher Soul\n",
            },
            "planner": {
                "identity_md": _identity_md(
                    "planner", ["echo", "skill_list", "skill_read", "skill_write"], "Planner Agent"
                ),
                "soul_md": "# Planner Soul\n",
            },
            "coder": {
                "identity_md": _identity_md(
                    "coder",
                    ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
                    "Coder Agent",
                ),
                "soul_md": "# Coder Soul\n",
            },
        },
    }


def test_conversation_returns_llm_text(tmp_path: Path) -> None:
    router = _FakeRouter([ModelResponse(text="What should I call you?", tool_calls=[])])
    agent_root = tmp_path / "agents"

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-1")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="hello",
                agent_root=agent_root,
            )
        )

        assert reply == "What should I call you?"
        row = conn.execute(
            "SELECT status, conversation_json FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "in_progress"
    saved = json.loads(str(row["conversation_json"]))
    assert saved[0]["role"] == "user"
    assert saved[0]["content"] == "hello"
    assert saved[1]["role"] == "assistant"
    assert saved[1]["content"] == "What should I call you?"


def test_finalize_writes_bundles(tmp_path: Path) -> None:
    finalize_call = {
        "name": "finalize_onboarding",
        "arguments": _valid_finalize_args(),
    }
    router = _FakeRouter([ModelResponse(text="", tool_calls=[finalize_call])])
    agent_root = tmp_path / "agents"

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-2")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="Let's do it",
                agent_root=agent_root,
            )
        )

        assert reply is not None
        assert "onboarding complete" in reply.lower()

        row = conn.execute(
            "SELECT status, answers_json FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "completed"
    answers = json.loads(str(row["answers_json"]))
    assert answers["assistant_name"] == "Friday"
    assert answers["user_name"] == "Justin"

    for agent_id in ("main", "researcher", "planner", "coder"):
        assert (agent_root / agent_id / "identity.md").is_file()
        assert (agent_root / agent_id / "soul.md").is_file()
        assert (agent_root / agent_id / "heartbeat.md").is_file()


def test_finalize_validation_rejects_bad_args(tmp_path: Path) -> None:
    bad_args = _valid_finalize_args()
    assert isinstance(bad_args["agents"], dict)
    bad_args["agents"].pop("coder")

    first = ModelResponse(
        text="",
        tool_calls=[{"name": "finalize_onboarding", "arguments": bad_args}],
    )
    second = ModelResponse(text="I still need one more detail.", tool_calls=[])
    router = _FakeRouter([first, second])

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-3")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="ready",
                agent_root=tmp_path / "agents",
            )
        )

        assert reply == "I still need one more detail."
        row = conn.execute(
            "SELECT status FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "in_progress"
    assert router.calls == 2


def test_completed_returns_none(tmp_path: Path) -> None:
    finalize_call = {
        "name": "finalize_onboarding",
        "arguments": _valid_finalize_args(),
    }
    router = _FakeRouter([ModelResponse(text="", tool_calls=[finalize_call])])
    agent_root = tmp_path / "agents"

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-4")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        _ = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="finish onboarding",
                agent_root=agent_root,
            )
        )

        calls_before = router.calls
        again = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="real question",
                agent_root=agent_root,
            )
        )

    assert again is None
    assert router.calls == calls_before


def test_reset_clears_conversation(tmp_path: Path) -> None:
    router = _FakeRouter([ModelResponse(text="What's your goal?", tool_calls=[])])

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-5")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        _ = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="hello",
                agent_root=tmp_path / "agents",
            )
        )

        reset_onboarding_state(conn, user_id, thread_id)

        row = conn.execute(
            "SELECT status, conversation_json FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert row is not None
    assert row["status"] == "required"
    assert row["conversation_json"] == "[]"


def test_conversation_history_persists(tmp_path: Path) -> None:
    router = _FakeRouter(
        [
            ModelResponse(text="What should I call you?", tool_calls=[]),
            ModelResponse(text="What are your main goals?", tool_calls=[]),
        ]
    )

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-6")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        _ = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="hello",
                agent_root=tmp_path / "agents",
            )
        )
        _ = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="Justin",
                agent_root=tmp_path / "agents",
            )
        )

    assert len(router.messages_by_call) == 2
    second_call_messages = router.messages_by_call[1]
    contents = [item["content"] for item in second_call_messages]
    assert any(content == "hello" for content in contents)
    assert any(content == "What should I call you?" for content in contents)
    assert any(content == "Justin" for content in contents)


def test_conversation_strips_control_tokens_from_model_output(tmp_path: Path) -> None:
    noisy = (
        "Got it, Justin! What should I call your assistant?<|end|><|start|>"
        "assistant<|channel|>analysis<|message|>hidden"
    )
    router = _FakeRouter([ModelResponse(text=noisy, tool_calls=[])])

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-7")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="Justin",
                agent_root=tmp_path / "agents",
            )
        )
        row = conn.execute(
            "SELECT conversation_json FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert reply == "Got it, Justin! What should I call your assistant?"
    assert row is not None
    saved = json.loads(str(row["conversation_json"]))
    assert saved[-1]["content"] == "Got it, Justin! What should I call your assistant?"


def test_finalize_is_blocked_before_minimum_exchanges(tmp_path: Path) -> None:
    finalize_call = {
        "name": "finalize_onboarding",
        "arguments": _valid_finalize_args(),
    }
    router = _FakeRouter(
        [
            ModelResponse(text="", tool_calls=[finalize_call]),
            ModelResponse(text="Let's continue with your goals.", tool_calls=[]),
        ]
    )

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-min-1")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,
                user_id=user_id,
                thread_id=thread_id,
                user_message="Hi",
                agent_root=tmp_path / "agents",
            )
        )
        row = conn.execute(
            "SELECT status FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert reply == "Let's continue with your goals."
    assert row is not None
    assert row["status"] == "in_progress"
    assert router.calls == 2


def test_onboarding_provider_error_is_recovered_without_losing_user_message(tmp_path: Path) -> None:
    router = _ErrorRouter()

    with get_conn() as conn:
        user_id = ensure_user(conn, "onboarding-user-v2-err-1")
        channel_id = ensure_channel(conn, user_id, "web")
        thread_id = create_thread(conn, user_id, channel_id)

        reply = asyncio.run(
            maybe_handle_onboarding_message(
                conn=conn,
                router=router,  # type: ignore[arg-type]
                user_id=user_id,
                thread_id=thread_id,
                user_message="Justin",
                agent_root=tmp_path / "agents",
            )
        )
        row = conn.execute(
            "SELECT status, conversation_json FROM onboarding_states WHERE user_id=?",
            (user_id,),
        ).fetchone()

    assert reply is not None
    assert "saved your last answer" in reply.lower()
    assert row is not None
    assert row["status"] == "in_progress"
    conversation = json.loads(str(row["conversation_json"]))
    assert conversation[0]["role"] == "user"
    assert conversation[0]["content"] == "Justin"
