"""Agent bundle data models."""

from dataclasses import dataclass


@dataclass(slots=True)
class AgentBundle:
    agent_id: str
    identity_markdown: str
    soul_markdown: str
    heartbeat_markdown: str
    allowed_tools: list[str]
    risk_tier: str = "low"
    max_actions_per_step: int = 4
    allowed_paths: tuple[str, ...] = ()
    can_request_privileged_change: bool = False
    tools_markdown: str = ""
