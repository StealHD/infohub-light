"""RouteKey-to-adapter registration without platform conditionals."""

from __future__ import annotations

from .domain import RouteKey
from .ports import ActorRouteAdapter


class AdapterRegistryError(LookupError):
    pass


class AdapterAlreadyRegistered(AdapterRegistryError):
    pass


class AdapterNotRegistered(AdapterRegistryError):
    pass


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[RouteKey, ActorRouteAdapter] = {}

    def register(self, adapter: ActorRouteAdapter) -> None:
        route_key = adapter.route_key
        if route_key in self._adapters:
            raise AdapterAlreadyRegistered(str(route_key))
        self._adapters[route_key] = adapter

    def require(self, route_key: RouteKey) -> ActorRouteAdapter:
        try:
            return self._adapters[route_key]
        except KeyError as error:
            raise AdapterNotRegistered(str(route_key)) from error

    def registered_keys(self) -> tuple[RouteKey, ...]:
        return tuple(sorted(self._adapters, key=str))
