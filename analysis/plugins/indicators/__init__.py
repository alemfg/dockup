# Auto-import so plugins self-register on import
from analysis.plugins.indicators.indicators import RSIPlugin, MACDPlugin, BollingerBandsPlugin

__all__ = ["RSIPlugin", "MACDPlugin", "BollingerBandsPlugin"]
