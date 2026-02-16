"""Built-in web search plugin — wraps the existing web_search tool."""

from jarvis.plugins.base import JarvisPlugin, PluginContext
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.web_search import web_search


class WebSearchPlugin(JarvisPlugin):
    name = "web_search"
    description = "Search the web using SearXNG with DuckDuckGo fallback"
    version = "0.1.0"

    def register_tools(self, registry: ToolRegistry, ctx: PluginContext) -> None:
        registry.register(
            "web_search",
            "Search the web using SearXNG and return results",
            web_search,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results to return (default 5, max 20)",
                    },
                    "categories": {
                        "type": "string",
                        "description": "Search categories (default: general)",
                    },
                },
                "required": ["query"],
            },
        )
