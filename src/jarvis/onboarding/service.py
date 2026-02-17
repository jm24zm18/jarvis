"""Conversational onboarding flow for agent bundle setup."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from jarvis.db.queries import now_iso
from jarvis.providers.router import ProviderRouter

logger = logging.getLogger(__name__)


class _OnboardingState(TypedDict):
    status: str
    step: int
    answers: dict[str, str]
    conversation: list[dict[str, str]]

AGENT_IDS = (
    "main",
    "researcher",
    "planner",
    "coder",
    "tester",
    "lintfixer",
    "api_guardian",
    "data_migrator",
    "web_builder",
    "security_reviewer",
    "docs_keeper",
    "release_ops",
)
REQUIRED_FILES = ("identity.md", "soul.md", "heartbeat.md")
MAX_CONVERSATION_EXCHANGES = 20
MIN_CONVERSATION_EXCHANGES = 5

ALLOWED_TOOLS_BY_AGENT: dict[str, list[str]] = {
    "main": [
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
    "researcher": ["echo", "web_search", "session_send", "skill_list", "skill_read", "skill_write"],
    "planner": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "coder": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "tester": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "lintfixer": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "api_guardian": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "data_migrator": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "web_builder": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "security_reviewer": [
        "echo", "exec_host", "web_search", "skill_list", "skill_read", "skill_write",
    ],
    "docs_keeper": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
    "release_ops": ["echo", "exec_host", "skill_list", "skill_read", "skill_write"],
}

ONBOARDING_STATUS_PROMPT = "Onboarding is required."
ONBOARDING_START_INSTRUCTION = (
    "Start onboarding now. Ask only the first question. "
    "Do not call finalize_onboarding yet."
)

ONBOARDING_SYSTEM_PROMPT = (
    "You are running personalized onboarding for a new assistant workspace. "
    "Have a natural conversation and gather enough detail "
    "to produce final agent bundle markdown files. "
    "Cover these topics conversationally, one at a time, "
    "with follow-up questions when answers are vague:\n"
    "1) assistant_name (what to call the assistant),\n"
    "2) user_name (what to call the user),\n"
    "3) user goals and recurring work types,\n"
    "4) preferred communication tone/style (formality, humor, verbosity, emoji use),\n"
    "5) delegation preferences for the agent team.\n\n"
    "Do not dump a checklist. Ask one focused question per turn. "
    "You MUST ask about all 5 topics and collect answers over at least 5 user exchanges "
    "before using finalize_onboarding. "
    "Keep the exchange concise and friendly. "
    "Once you have enough detail, call the finalize_onboarding tool "
    "with complete markdown for all agents.\n\n"
    "For each agent (main, researcher, planner, coder, tester, lintfixer, "
    "api_guardian, data_migrator, web_builder, security_reviewer, docs_keeper, release_ops), "
    "provide identity_md and soul_md in the tool args. "
    "identity_md MUST include YAML frontmatter with agent_id and allowed_tools exactly matching:\n"
    "- main: echo, session_list, session_history, session_send, web_search, exec_host, "
    "skill_list, skill_read, skill_write, update_persona\n"
    "- researcher: echo, web_search, session_send, skill_list, skill_read, skill_write\n"
    "- planner: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- coder: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- tester: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- lintfixer: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- api_guardian: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- data_migrator: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- web_builder: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- security_reviewer: echo, exec_host, web_search, skill_list, skill_read, skill_write\n"
    "- docs_keeper: echo, exec_host, skill_list, skill_read, skill_write\n"
    "- release_ops: echo, exec_host, skill_list, skill_read, skill_write\n\n"
    "The markdown should be personalized prose, not key-value templates. "
    "Also include assistant_name and user_name in the tool args."
)

FINALIZE_TOOL_SCHEMA: dict[str, object] = {
    "name": "finalize_onboarding",
    "description": "Finalize onboarding and write all agent bundles from generated markdown.",
    "parameters": {
        "type": "object",
        "properties": {
            "assistant_name": {"type": "string"},
            "user_name": {"type": "string"},
            "agents": {
                "type": "object",
                "properties": {
                    "main": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "researcher": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "planner": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "coder": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "tester": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "lintfixer": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "api_guardian": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "data_migrator": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "web_builder": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "security_reviewer": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "docs_keeper": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                    "release_ops": {
                        "type": "object",
                        "properties": {
                            "identity_md": {"type": "string"},
                            "soul_md": {"type": "string"},
                        },
                        "required": ["identity_md", "soul_md"],
                    },
                },
                "required": [
                    "main", "researcher", "planner", "coder",
                    "tester", "lintfixer", "api_guardian", "data_migrator",
                    "web_builder", "security_reviewer", "docs_keeper", "release_ops",
                ],
            },
        },
        "required": ["assistant_name", "user_name", "agents"],
    },
}


def get_assistant_name(agent_root: Path = Path("agents")) -> str:
    """Resolve the user-facing assistant name from main agent identity markdown."""
    identity_path = agent_root / "main" / "identity.md"
    fallback = "Jarvis"
    try:
        raw = identity_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return fallback
    except OSError:
        return fallback
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped.startswith("# "):
            continue
        heading = stripped[2:].strip()
        suffix = " Main Agent"
        if heading.endswith(suffix):
            name = heading[: -len(suffix)].strip()
            return name or fallback
        return heading or fallback
    return fallback


def get_user_name(conn: sqlite3.Connection, user_id: str, fallback: str = "user") -> str:
    """Resolve the user-facing name from onboarding answers."""
    state = _get_state(conn, user_id)
    if state is None:
        return fallback
    raw = str(state["answers"].get("user_name", "")).strip()
    return raw or fallback


def onboarding_required(agent_root: Path = Path("agents")) -> bool:
    for agent_id in AGENT_IDS:
        bundle_dir = agent_root / agent_id
        for filename in REQUIRED_FILES:
            if not (bundle_dir / filename).is_file():
                return True
    return False


def is_onboarding_active(
    conn: sqlite3.Connection,
    user_id: str,
    agent_root: Path = Path("agents"),
) -> bool:
    state = _get_state(conn, user_id)
    required = onboarding_required(agent_root=agent_root)

    if state is not None and state["status"] == "completed" and not required:
        return False
    if state is None and not required:
        return False
    return True


async def maybe_handle_onboarding_message(
    conn: sqlite3.Connection,
    router: ProviderRouter,
    user_id: str,
    thread_id: str,
    user_message: str,
    agent_root: Path = Path("agents"),
) -> str | None:
    state = _get_state(conn, user_id)
    required = onboarding_required(agent_root=agent_root)

    if state is not None and state["status"] == "completed" and not required:
        return None
    if state is None and not required:
        return None

    conversation = state["conversation"] if state is not None else []
    status = str(state["status"]) if state is not None else "required"
    answers = state["answers"] if state is not None else {}

    if status == "required":
        conversation = []
        status = "in_progress"

    user_text = user_message.strip()
    if user_text:
        conversation.append({"role": "user", "content": user_text})

    if _conversation_exchanges(conversation) >= MAX_CONVERSATION_EXCHANGES:
        conversation.append(
            {
                "role": "user",
                "content": (
                    "Please finalize onboarding now. Use the finalize_onboarding tool "
                    "with complete markdown for all agents."
                ),
            }
        )

    response = await _safe_onboarding_turn(router=router, conversation=conversation)
    if (
        response["action"] == "finalize"
        and _conversation_exchanges(conversation) < MIN_CONVERSATION_EXCHANGES
    ):
        correction_conversation = conversation + [
            {
                "role": "user",
                "content": (
                    "Do not finalize yet. Cover all 5 onboarding topics first and continue with "
                    "focused follow-up questions."
                ),
            },
        ]
        response = await _safe_onboarding_turn(router=router, conversation=correction_conversation)

    if response["action"] == "reply":
        assistant_text = _sanitize_assistant_text(str(response["text"]))
        if assistant_text:
            conversation.append({"role": "assistant", "content": assistant_text})
        _upsert_state(
            conn,
            user_id=user_id,
            thread_id=thread_id,
            status="in_progress",
            conversation=conversation,
            answers=answers,
        )
        return assistant_text or "I need a bit more detail before I can finalize onboarding."

    finalize_args: dict[str, object] = (
        dict(response["args"]) if isinstance(response["args"], dict) else {}
    )
    validation_error = _validate_finalize_args(finalize_args)
    if validation_error is not None:
        conversation.append(
            {
                "role": "user",
                "content": (
                    "Validation error for finalize_onboarding: "
                    f"{validation_error}. Retry and call finalize_onboarding with corrected args."
                ),
            }
        )
        retry = await _safe_onboarding_turn(router=router, conversation=conversation)
        if retry["action"] == "reply":
            assistant_text = _sanitize_assistant_text(str(retry["text"]))
            if assistant_text:
                conversation.append({"role": "assistant", "content": assistant_text})
            _upsert_state(
                conn,
                user_id=user_id,
                thread_id=thread_id,
                status="in_progress",
                conversation=conversation,
                answers=answers,
            )
            return assistant_text or "I still need more detail to finalize onboarding."

        finalize_args = dict(retry["args"]) if isinstance(retry["args"], dict) else {}
        validation_error = _validate_finalize_args(finalize_args)
        if validation_error is not None:
            fallback_text = (
                "I couldn't finalize onboarding yet because the generated bundle was invalid. "
                "Please answer a bit more detail and I'll try again."
            )
            conversation.append({"role": "assistant", "content": fallback_text})
            _upsert_state(
                conn,
                user_id=user_id,
                thread_id=thread_id,
                status="in_progress",
                conversation=conversation,
                answers=answers,
            )
            return fallback_text

    _write_bundles_from_llm(agent_root, finalize_args)
    assistant_name = str(finalize_args.get("assistant_name", "")).strip() or "Jarvis"
    user_name = str(finalize_args.get("user_name", "")).strip() or "user"
    final_answers = {"assistant_name": assistant_name, "user_name": user_name}

    complete_text = (
        "Onboarding complete. Agent markdown files were created. "
        "Send your next message and I will start helping."
    )
    conversation.append({"role": "assistant", "content": complete_text})
    _upsert_state(
        conn,
        user_id=user_id,
        thread_id=thread_id,
        status="completed",
        conversation=conversation,
        answers=final_answers,
    )
    return complete_text


async def start_onboarding_prompt(
    conn: sqlite3.Connection,
    router: ProviderRouter,
    user_id: str,
    thread_id: str,
    agent_root: Path = Path("agents"),
) -> str | None:
    state = _get_state(conn, user_id)
    required = onboarding_required(agent_root=agent_root)

    if not required and (state is None or state["status"] == "completed"):
        return None

    if state is None or state["status"] == "required":
        prompt = await _generate_opening_prompt(router)
        _upsert_state(
            conn,
            user_id=user_id,
            thread_id=thread_id,
            status="in_progress",
            conversation=[{"role": "assistant", "content": prompt}],
            answers={},
        )
        return prompt

    if state["status"] == "completed":
        return None

    conversation = state["conversation"]
    last_assistant = next(
        (
            msg
            for msg in reversed(conversation)
            if msg.get("role") == "assistant" and str(msg.get("content", "")).strip()
        ),
        None,
    )
    if last_assistant is not None:
        prompt = _sanitize_assistant_text(str(last_assistant["content"]))
        if prompt:
            return prompt

    prompt = await _generate_opening_prompt(router)
    conversation.append({"role": "assistant", "content": prompt})
    _upsert_state(
        conn,
        user_id=user_id,
        thread_id=thread_id,
        status="in_progress",
        conversation=conversation,
        answers=state["answers"],
    )
    return prompt


def reset_onboarding_state(conn: sqlite3.Connection, user_id: str, thread_id: str) -> None:
    _upsert_state(
        conn,
        user_id=user_id,
        thread_id=thread_id,
        status="required",
        conversation=[],
        answers={},
    )


def get_onboarding_status(
    conn: sqlite3.Connection,
    user_id: str,
    agent_root: Path = Path("agents"),
) -> dict[str, object]:
    state = _get_state(conn, user_id)
    required = onboarding_required(agent_root=agent_root)

    if state is None:
        if required:
            return {
                "status": "required",
                "required": True,
                "question": ONBOARDING_STATUS_PROMPT,
            }
        return {
            "status": "not_required",
            "required": False,
            "question": None,
        }

    status = str(state["status"])
    if status == "completed":
        if required:
            return {
                "status": "required",
                "required": True,
                "question": ONBOARDING_STATUS_PROMPT,
            }
        return {
            "status": "completed",
            "required": False,
            "question": None,
        }

    if status == "required":
        return {
            "status": "required",
            "required": True,
            "question": ONBOARDING_STATUS_PROMPT,
        }

    conversation = state["conversation"]
    last_assistant = next(
        (
            msg
            for msg in reversed(conversation)
            if msg.get("role") == "assistant" and str(msg.get("content", "")).strip()
        ),
        None,
    )
    question = (
        _sanitize_assistant_text(str(last_assistant["content"]))
        if last_assistant is not None
        else ONBOARDING_STATUS_PROMPT
    )
    return {
        "status": "in_progress",
        "required": True,
        "question": question,
    }


def _get_state(conn: sqlite3.Connection, user_id: str) -> _OnboardingState | None:
    row = conn.execute(
        (
            "SELECT status, step, answers_json, conversation_json "
            "FROM onboarding_states WHERE user_id=? LIMIT 1"
        ),
        (user_id,),
    ).fetchone()
    if row is None:
        return None

    parsed_answers: dict[str, str] = {}
    raw_answers = row["answers_json"]
    if isinstance(raw_answers, str):
        try:
            decoded_answers = json.loads(raw_answers)
            if isinstance(decoded_answers, dict):
                parsed_answers = {str(k): str(v) for k, v in decoded_answers.items()}
        except json.JSONDecodeError:
            parsed_answers = {}

    parsed_conversation: list[dict[str, str]] = []
    raw_conversation = row["conversation_json"]
    if isinstance(raw_conversation, str):
        try:
            decoded_conversation = json.loads(raw_conversation)
            if isinstance(decoded_conversation, list):
                for item in decoded_conversation:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role", "")).strip().lower()
                    raw_content = str(item.get("content", ""))
                    content = (
                        _sanitize_assistant_text(raw_content)
                        if role == "assistant"
                        else raw_content.strip()
                    )
                    if role not in {"user", "assistant"}:
                        continue
                    if not content:
                        continue
                    parsed_conversation.append({"role": role, "content": content})
        except json.JSONDecodeError:
            parsed_conversation = []

    return _OnboardingState(
        status=str(row["status"]),
        step=int(row["step"]),
        answers=parsed_answers,
        conversation=parsed_conversation,
    )


def _upsert_state(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    thread_id: str,
    status: str,
    conversation: list[dict[str, str]],
    answers: dict[str, str],
) -> None:
    now = now_iso()
    conn.execute(
        """
        INSERT INTO onboarding_states(
          user_id, thread_id, status, step, answers_json, conversation_json, created_at, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
          thread_id=excluded.thread_id,
          status=excluded.status,
          step=excluded.step,
          answers_json=excluded.answers_json,
          conversation_json=excluded.conversation_json,
          updated_at=excluded.updated_at
        """,
        (
            user_id,
            thread_id,
            status,
            0,
            json.dumps(answers),
            json.dumps(conversation),
            now,
            now,
        ),
    )


def _conversation_exchanges(conversation: list[dict[str, str]]) -> int:
    user_messages = sum(1 for msg in conversation if msg.get("role") == "user")
    return user_messages


async def _run_onboarding_turn(
    *,
    router: ProviderRouter,
    conversation: list[dict[str, str]],
) -> dict[str, object]:
    model_messages = [{"role": "system", "content": ONBOARDING_SYSTEM_PROMPT}] + conversation
    response, _lane, _primary_error = await router.generate(
        model_messages,
        tools=[FINALIZE_TOOL_SCHEMA],
        temperature=0.2,
        max_tokens=4096,
        priority="normal",
    )

    for call in response.tool_calls:
        name = str(call.get("name", "")).strip()
        if name != "finalize_onboarding":
            continue
        args = call.get("arguments", {})
        return {
            "action": "finalize",
            "args": args if isinstance(args, dict) else {},
            "text": response.text,
        }

    return {"action": "reply", "text": response.text}


async def _safe_onboarding_turn(
    *,
    router: ProviderRouter,
    conversation: list[dict[str, str]],
) -> dict[str, object]:
    try:
        return await _run_onboarding_turn(router=router, conversation=conversation)
    except Exception as exc:
        logger.exception("Onboarding turn failed; continuing with fallback prompt")
        error_text = (
            "I hit a temporary model issue, but I saved your last answer. "
            "Please continue and I will pick up from there."
        )
        if "quota" in str(exc).lower() or "429" in str(exc):
            error_text = (
                "I hit a temporary model quota limit, but I saved your last answer. "
                "Please continue and I will pick up from there."
            )
        return {"action": "reply", "text": error_text}


async def _generate_opening_prompt(router: ProviderRouter) -> str:
    response, _lane, _primary_error = await router.generate(
        [
            {"role": "system", "content": ONBOARDING_SYSTEM_PROMPT},
            {"role": "user", "content": ONBOARDING_START_INSTRUCTION},
        ],
        tools=[],
        temperature=0.2,
        max_tokens=300,
        priority="normal",
    )
    prompt = _sanitize_assistant_text(str(response.text))
    if prompt:
        return prompt
    return "What should I call your assistant?"


def _sanitize_assistant_text(text: str) -> str:
    cleaned = text.replace("<|end|>", "").strip()
    control_markers = (
        "<|start|>",
        "<|channel|>",
        "<|message|>",
        "<|analysis|>",
        "<|final|>",
    )
    first_marker: int | None = None
    for marker in control_markers:
        idx = cleaned.find(marker)
        if idx == -1:
            continue
        first_marker = idx if first_marker is None else min(first_marker, idx)
    if first_marker is not None:
        cleaned = cleaned[:first_marker].strip()
    return cleaned


def _validate_finalize_args(args: object) -> str | None:
    if not isinstance(args, dict):
        return "arguments must be an object"

    assistant_name = args.get("assistant_name")
    user_name = args.get("user_name")
    agents = args.get("agents")

    if not isinstance(assistant_name, str) or not assistant_name.strip():
        return "assistant_name is required"
    if not isinstance(user_name, str) or not user_name.strip():
        return "user_name is required"
    if not isinstance(agents, dict):
        return "agents must be an object"

    for agent_id in AGENT_IDS:
        raw_agent = agents.get(agent_id)
        if not isinstance(raw_agent, dict):
            return f"agents.{agent_id} is required"
        identity_md = raw_agent.get("identity_md")
        soul_md = raw_agent.get("soul_md")
        if not isinstance(identity_md, str) or not identity_md.strip():
            return f"agents.{agent_id}.identity_md is required"
        if not isinstance(soul_md, str) or not soul_md.strip():
            return f"agents.{agent_id}.soul_md is required"

        parsed = _parse_identity_frontmatter(identity_md)
        if parsed is None:
            return f"agents.{agent_id}.identity_md frontmatter is missing or invalid"
        frontmatter_agent_id = parsed.get("agent_id")
        if frontmatter_agent_id != agent_id:
            return f"agents.{agent_id}.identity_md agent_id must be '{agent_id}'"

        allowed_tools = parsed.get("allowed_tools")
        if not isinstance(allowed_tools, list):
            return f"agents.{agent_id}.identity_md allowed_tools is missing"
        expected = ALLOWED_TOOLS_BY_AGENT[agent_id]
        if allowed_tools != expected:
            return (
                f"agents.{agent_id}.identity_md allowed_tools must be exactly "
                f"{expected}"
            )

    return None


def _parse_identity_frontmatter(markdown: str) -> dict[str, object] | None:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    try:
        end_idx = next(idx for idx in range(1, len(lines)) if lines[idx].strip() == "---")
    except StopIteration:
        return None

    frontmatter_lines = lines[1:end_idx]
    agent_id: str | None = None
    allowed_tools: list[str] = []
    parsing_allowed_tools = False

    for raw_line in frontmatter_lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("agent_id:"):
            parsing_allowed_tools = False
            agent_id = stripped.split(":", 1)[1].strip().strip('"').strip("'")
            continue
        if stripped.startswith("allowed_tools:"):
            parsing_allowed_tools = True
            continue
        if parsing_allowed_tools and stripped.startswith("-"):
            value = stripped[1:].strip().strip('"').strip("'")
            if value:
                allowed_tools.append(value)
            continue
        if ":" in stripped:
            parsing_allowed_tools = False

    if not agent_id:
        return None
    if not allowed_tools:
        return None
    return {"agent_id": agent_id, "allowed_tools": allowed_tools}


def _write_file(path: Path, content: str, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_bundles_from_llm(agent_root: Path, args: dict[str, object]) -> None:
    agents = args.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("agents missing")

    timestamp = datetime.now(UTC).isoformat()

    for agent_id in AGENT_IDS:
        raw_agent = agents.get(agent_id)
        if not isinstance(raw_agent, dict):
            raise ValueError(f"agents.{agent_id} missing")

        identity_md = str(raw_agent.get("identity_md", "")).strip()
        soul_md = str(raw_agent.get("soul_md", "")).strip()
        if not identity_md or not soul_md:
            raise ValueError(f"agents.{agent_id} identity_md/soul_md missing")

        bundle_dir = agent_root / agent_id
        _write_file(bundle_dir / "identity.md", identity_md + "\n", overwrite=True)
        _write_file(bundle_dir / "soul.md", soul_md + "\n", overwrite=True)
        _write_file(
            bundle_dir / "heartbeat.md",
            "---\n"
            f"agent_id: {agent_id}\n"
            f"updated_at: {timestamp}\n"
            "---\n\n"
            "## Last Action\n"
            "Onboarding completed.\n",
            overwrite=True,
        )
