"""Public read-only market data adapters."""

from .base import AdapterCapabilities, FetchRequest, PublicHttpClient, ReadOnlyAdapter
from .binance_spot import BinanceSpotAdapter
from .databento_futures import DatabentoCompatibleFuturesAdapter, build_volume_rolled_series
from .polymarket import PolymarketAdapter, PolymarketBookState

__all__ = [
    "AdapterCapabilities",
    "BinanceSpotAdapter",
    "DatabentoCompatibleFuturesAdapter",
    "FetchRequest",
    "PolymarketAdapter",
    "PolymarketBookState",
    "PublicHttpClient",
    "ReadOnlyAdapter",
    "build_volume_rolled_series",
]
