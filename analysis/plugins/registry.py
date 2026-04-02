"""
Plugin Registry — all analysis plugins register here at import time.
The SignalAggregator discovers enabled plugins from the registry.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type

from messaging.logging import get_logger
from messaging.models import PluginResult

logger = get_logger("analysis.registry")

_plugins: Dict[str, "AnalysisPlugin"] = {}


def register(plugin_class: Type["AnalysisPlugin"]) -> Type["AnalysisPlugin"]:
    """Decorator / function to register a plugin class."""
    instance = plugin_class()
    _plugins[instance.name] = instance
    logger.debug(f"Plugin registered: {instance.name}")
    return plugin_class


def get_all() -> List["AnalysisPlugin"]:
    return list(_plugins.values())


def get_enabled(plugin_configs: Dict[str, dict]) -> List["AnalysisPlugin"]:
    """Return plugins that are enabled in the provided config dict."""
    enabled = []
    for plugin in _plugins.values():
        cfg = plugin_configs.get(plugin.name, {})
        if cfg.get("enabled", plugin.enabled_by_default):
            plugin.apply_config(cfg)
            enabled.append(plugin)
    return enabled


def get_plugin(name: str) -> Optional["AnalysisPlugin"]:
    return _plugins.get(name)


# ─── Base Plugin ─────────────────────────────────────────────────────────────

class AnalysisPlugin(ABC):
    """
    Base class for all analysis plugins.
    Subclasses must set `name` and implement `run()`.
    Plugins self-register by calling register(MyPlugin) or using @register.
    """

    name: str = "base"
    enabled_by_default: bool = True

    def __init__(self):
        self._weight: float = 0.15
        self._params: dict  = {}

    def apply_config(self, config: dict) -> None:
        """Apply per-plugin config (weight, params)."""
        self._weight = config.get("weight", self._weight)
        self._params = config.get("params", {})

    @property
    def weight(self) -> float:
        return self._weight

    @abstractmethod
    async def run(
        self,
        exchange: str,
        pair: str,
        prices: List[float],
        candles: Optional[Dict[str, List[dict]]] = None,
        extra: Optional[dict] = None,
    ) -> Optional[PluginResult]:
        """
        Run analysis for a specific (exchange, pair) context.
        Return None if insufficient data or plugin not applicable.
        """
        ...

    def __repr__(self) -> str:
        return f"<Plugin: {self.name} weight={self._weight}>"
