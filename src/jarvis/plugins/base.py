"""Plugin base class and context for the Jarvis plugin SDK."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from jarvis.tools.registry import ToolRegistry


@dataclass(slots=True)
class PluginContext:
    """Context passed to plugin lifecycle methods."""

    conn: sqlite3.Connection | None = None
    actor_id: str = "main"
    trace_id: str = ""
    thread_id: str = ""


class JarvisPlugin:
    """Base class for Jarvis plugins.

    Subclass this and override `register_tools()` to add tools.
    Optionally override `on_startup()` / `on_shutdown()` for lifecycle hooks.
    """

    name: str = ""
    description: str = ""
    version: str = "0.1.0"

    def register_tools(
        self,
        registry: ToolRegistry,
        ctx: PluginContext,
    ) -> None:
        """Register tools with the tool registry. Override in subclasses."""

    def on_startup(self) -> None:
        """Called when the plugin is loaded. Override for initialization."""

    def on_shutdown(self) -> None:
        """Called when the plugin is unloaded. Override for cleanup."""

    def enabled_for_agent(self, agent_id: str) -> bool:
        """Return True if this plugin should be active for the given agent.

        Default: enabled for all agents. Override to restrict.
        """
        return True
