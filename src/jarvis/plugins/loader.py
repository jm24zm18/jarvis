"""Plugin discovery and loading."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jarvis.plugins.base import JarvisPlugin

logger = logging.getLogger(__name__)

_loaded_plugins: list[JarvisPlugin] = []


def discover_plugins(plugins_dir: Path | None = None) -> list[type[JarvisPlugin]]:
    """Discover plugin classes from the builtin package and an optional external directory.

    Also discovers plugins registered via `jarvis_plugins` entry point group.
    """
    from jarvis.plugins.base import JarvisPlugin

    found: list[type[JarvisPlugin]] = []

    # 1. Scan builtin plugins
    try:
        import jarvis.plugins.builtin as builtin_pkg

        for _importer, modname, _ispkg in pkgutil.iter_modules(builtin_pkg.__path__):
            try:
                mod = importlib.import_module(f"jarvis.plugins.builtin.{modname}")
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, JarvisPlugin)
                        and attr is not JarvisPlugin
                    ):
                        found.append(attr)
            except Exception:
                logger.warning("Failed to load builtin plugin module: %s", modname, exc_info=True)
    except ImportError:
        pass

    # 2. Scan external plugins directory
    if plugins_dir is not None and plugins_dir.is_dir():
        import sys

        plugins_dir_str = str(plugins_dir)
        if plugins_dir_str not in sys.path:
            sys.path.insert(0, plugins_dir_str)
        for child in sorted(plugins_dir.iterdir()):
            if child.suffix != ".py" or child.name.startswith("_"):
                continue
            modname = child.stem
            try:
                mod = importlib.import_module(modname)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, JarvisPlugin)
                        and attr is not JarvisPlugin
                    ):
                        found.append(attr)
            except Exception:
                logger.warning("Failed to load external plugin: %s", modname, exc_info=True)

    # 3. Scan entry points (pyproject.toml [project.entry-points.jarvis_plugins])
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        group = (
            eps.get("jarvis_plugins", [])
            if isinstance(eps, dict)
            else eps.select(group="jarvis_plugins")
        )
        for ep in group:
            try:
                cls = ep.load()
                if isinstance(cls, type) and issubclass(cls, JarvisPlugin):
                    found.append(cls)
            except Exception:
                logger.warning("Failed to load entry point plugin: %s", ep.name, exc_info=True)
    except Exception:
        pass

    return found


def load_plugins(
    plugins_dir: Path | None = None,
    agent_id: str = "main",
) -> list[JarvisPlugin]:
    """Discover, instantiate, and start plugins for a given agent."""
    global _loaded_plugins
    classes = discover_plugins(plugins_dir)
    plugins: list[JarvisPlugin] = []
    for cls in classes:
        try:
            instance = cls()
            if instance.enabled_for_agent(agent_id):
                instance.on_startup()
                plugins.append(instance)
        except Exception:
            logger.warning("Failed to instantiate plugin: %s", cls.__name__, exc_info=True)
    _loaded_plugins = plugins
    return plugins


def get_loaded_plugins() -> list[JarvisPlugin]:
    """Return the currently loaded plugin instances."""
    return list(_loaded_plugins)


def shutdown_plugins() -> None:
    """Shut down all loaded plugins."""
    global _loaded_plugins
    for plugin in _loaded_plugins:
        try:
            plugin.on_shutdown()
        except Exception:
            logger.warning("Plugin shutdown failed: %s", plugin.name, exc_info=True)
    _loaded_plugins = []
