"""Focused API orchestration for v2-managed catalog source lifecycle."""

from __future__ import annotations

from typing import Any, Mapping

from ..services.actorops.binding_service import (
    ActorOpsBindingError,
    ActorOpsBindingService,
)
from ..services.actorops.repository import ActorOpsNotFound, ActorOpsRepository
from ..services.source_type_registry import is_youtube_channel_config


class ActorOpsSourceLifecycle:
    def __init__(self, store: Any, *, workspace_id: str) -> None:
        self.store = store
        self.workspace_id = str(workspace_id)
        self.bindings = ActorOpsBindingService(
            store, workspace_id=self.workspace_id
        )

    def is_managed(self, source_type: str, config: object) -> bool:
        if not isinstance(config, Mapping):
            return False
        if source_type == "rss":
            return is_youtube_channel_config(config)
        if source_type != "apify_social":
            return False
        profile_id = str(config.get("profile_id") or "").strip()
        if profile_id:
            return True
        return (
            str(config.get("platform") or "").casefold(),
            str(config.get("kind") or "").casefold(),
        ) in {("x", "profile"), ("instagram", "profile")}

    def normalize_config(
        self,
        source_type: str,
        config: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """Remove a persisted Route id while preserving its v2 RouteKey."""

        normalized = dict(config)
        profile_id = str(normalized.pop("profile_id", "") or "").strip()
        if source_type != "apify_social" or not profile_id:
            return normalized
        try:
            route = ActorOpsRepository(
                self.store.connect(), self.workspace_id
            ).get_route(profile_id)
        except ActorOpsNotFound as exc:
            if source_id is None:
                raise ActorOpsBindingError("actorops_v2_route_not_found") from exc
            try:
                binding = self.bindings.repository.get_binding(source_id)
                route = self.bindings.repository.get_route(binding.route_id)
            except ActorOpsNotFound as binding_exc:
                raise ActorOpsBindingError(
                    "actorops_v2_route_not_found"
                ) from binding_exc
        normalized["platform"] = route.route_key.platform
        normalized["kind"] = route.route_key.target_type
        return normalized

    def after_create(self, source_id: str) -> dict[str, Any]:
        self._require_transaction()
        source = self._source(source_id)
        if self.is_managed(str(source["type"]), source.get("config")):
            self.bindings.ensure(source_id)
        return self._source(source_id)

    def after_update(
        self,
        source_id: str,
        *,
        previous_config: object,
        requested_enabled: bool | None,
    ) -> dict[str, Any]:
        self._require_transaction()
        source = self._source(source_id)
        if not self.is_managed(str(source["type"]), source.get("config")):
            return source
        try:
            previous_binding = self.bindings.repository.get_binding(source_id)
        except ActorOpsNotFound:
            previous_binding = None
        binding = self.bindings.ensure(source_id)
        if source.get("config") != previous_config:
            binding = self.bindings.rebind(source_id)
        if requested_enabled is False:
            # Rebinding already advances the version and leaves the Binding
            # pending.  A simultaneous "enabled=false" request must not turn
            # that one target change into two lifecycle transitions.
            if (
                previous_binding is None
                or binding.binding_version == previous_binding.binding_version
            ):
                binding = self.bindings.disable(source_id)
        elif requested_enabled is True:
            if binding.status == "disabled":
                binding = self.bindings.reenable(source_id)
            elif binding.status == "ready":
                self.bindings.enable_ready(source_id)
            else:
                self.store.update_source(source_id, enabled=False, commit=False)
        return self._source(source_id)

    def soft_delete(self, source_id: str) -> dict[str, Any]:
        self._require_transaction()
        source = self._source(source_id)
        if self.is_managed(str(source["type"]), source.get("config")):
            self.bindings.ensure(source_id)
            self.bindings.soft_delete(source_id)
        else:
            self.store.update_source(source_id, enabled=False, commit=False)
        return self._source(source_id)

    def _source(self, source_id: str) -> dict[str, Any]:
        source = self.store.get_source(source_id)
        if source is None or str(source.get("workspace_id")) != self.workspace_id:
            raise ActorOpsBindingError("actorops_v2_source_not_found")
        return source

    def _require_transaction(self) -> None:
        if not self.store.connect().in_transaction:
            raise RuntimeError("ActorOps source lifecycle requires a transaction")


def assert_actorops_subscription_enable_allowed(
    store: Any, *, workspace_id: str, source_id: str
) -> None:
    lifecycle = ActorOpsSourceLifecycle(store, workspace_id=workspace_id)
    source = lifecycle._source(source_id)
    if not lifecycle.is_managed(str(source["type"]), source.get("config")):
        return
    state = lifecycle.bindings.execution_state(source_id)
    if not bool(source.get("enabled")) or not state.allowed:
        raise ActorOpsBindingError("actorops_v2_binding_not_ready")


__all__ = [
    "ActorOpsSourceLifecycle",
    "assert_actorops_subscription_enable_allowed",
]
