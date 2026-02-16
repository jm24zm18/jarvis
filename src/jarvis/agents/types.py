"""Agent bundle data models."""

from dataclasses import dataclass


@dataclass(slots=True)
class AgentBundle:
    agent_id: str
    identity_markdown: str
    soul_markdown: str
    heartbeat_markdown: str
    allowed_tools: list[str]
    tools_markdown: str = ""
