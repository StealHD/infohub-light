"""Compatibility facade for the shared ActorOps source lifecycle."""

from ..services.actorops.source_lifecycle import (
    ActorOpsSourceLifecycle,
    assert_actorops_subscription_enable_allowed,
)


__all__ = [
    "ActorOpsSourceLifecycle",
    "assert_actorops_subscription_enable_allowed",
]
