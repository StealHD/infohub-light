"""ActorOps v2 domain and persistence foundation.

Phase 1 intentionally exports no runtime service and starts no external work.
"""

from .domain import RouteKey
from .registry import AdapterRegistry

__all__ = ["AdapterRegistry", "RouteKey"]
