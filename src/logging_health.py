"""Process-local sink health; recovery evidence is attached to the next write."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any, Literal


FailureKind = Literal["validation", "write"]
_LOCK = Lock()
CHANNELS = ("runtime", "operations")
_STATE: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def reset_health() -> None:
    with _LOCK:
        for channel in CHANNELS:
            _STATE[channel] = dict(
                configured=False, healthy=False, last_success=None, last_failure=None,
                last_failure_kind=None, validation_failures=0, write_failures=0,
                recovery_count=0, last_recovery=None,
            )


def mark_failure(channel: str, kind: FailureKind) -> None:
    with _LOCK:
        state = _STATE[channel]
        state.update(healthy=False, last_failure=_now(), last_failure_kind=kind)
        state[f"{kind}_failures"] += 1


def mark_success(channel: str) -> None:
    with _LOCK:
        state = _STATE[channel]
        now = _now()
        if not state["healthy"] and state["last_failure"] is not None:
            state["recovery_count"] += 1
            state["last_recovery"] = now
        state.update(configured=True, healthy=True, last_success=now)


def recovery_evidence(channel: str) -> dict[str, Any] | None:
    with _LOCK:
        state = _STATE[channel]
        if state["healthy"] or state["last_failure"] is None:
            return None
        return {key: state[key] for key in (
            "last_failure", "last_failure_kind", "validation_failures", "write_failures",
        )}


def logging_health_status() -> dict[str, Any]:
    with _LOCK:
        channels = {
            channel: {
                "status": "ready" if state["configured"] and state["healthy"] else "degraded",
                **{key: value for key, value in state.items() if key not in {"configured", "healthy"}},
            }
            for channel, state in _STATE.items()
        }
    return {
        "status": "ready" if all(s["status"] == "ready" for s in channels.values()) else "degraded",
        "channels": channels,
    }


reset_health()
