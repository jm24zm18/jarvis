"""Tests for plugin SDK."""

from jarvis.plugins.base import JarvisPlugin, PluginContext
from jarvis.plugins.loader import (
    discover_plugins,
    get_loaded_plugins,
    load_plugins,
    shutdown_plugins,
)
from jarvis.tools.registry import ToolRegistry


class DemoPlugin(JarvisPlugin):
    name = "demo"
    description = "A demo plugin for testing"
    version = "0.1.0"

    def register_tools(self, registry: ToolRegistry, ctx: PluginContext) -> None:
        async def demo_handler(args):
            return {"echo": args}

        registry.register("demo_tool", "Demo tool", demo_handler)

    def enabled_for_agent(self, agent_id: str) -> bool:
        return agent_id == "main"


class AlwaysPlugin(JarvisPlugin):
    name = "always"
    description = "Always enabled"

    def register_tools(self, registry: ToolRegistry, ctx: PluginContext) -> None:
        async def noop(args):
            return {}

        registry.register("always_tool", "Always tool", noop)


def test_plugin_register_tools() -> None:
    registry = ToolRegistry()
    plugin = DemoPlugin()
    ctx = PluginContext()
    plugin.register_tools(registry, ctx)
    assert registry.get("demo_tool") is not None


def test_plugin_enabled_for_agent() -> None:
    plugin = DemoPlugin()
    assert plugin.enabled_for_agent("main") is True
    assert plugin.enabled_for_agent("researcher") is False


def test_base_plugin_default_enabled() -> None:
    plugin = JarvisPlugin()
    assert plugin.enabled_for_agent("any_agent") is True


def test_discover_builtin_plugins() -> None:
    classes = discover_plugins()
    # Should find at least the WebSearchPlugin
    names = [cls.name for cls in classes if hasattr(cls, "name")]
    assert "web_search" in names


def test_load_and_shutdown_plugins() -> None:
    load_plugins()
    assert len(get_loaded_plugins()) > 0
    shutdown_plugins()
    assert len(get_loaded_plugins()) == 0
