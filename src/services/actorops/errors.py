"""ActorOps v2 runtime error vocabulary."""

from __future__ import annotations

from .domain import FailureClass


class ActorOpsRuntimeError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        failure_class: FailureClass,
        proven_no_start: bool = False,
        retryable: bool | None = None,
    ) -> None:
        self.code = code
        self.failure_class = failure_class
        self.proven_no_start = bool(proven_no_start)
        self.retryable = (
            failure_class not in {
                FailureClass.CONFIGURATION,
                FailureClass.TARGET,
            }
            if retryable is None
            else bool(retryable)
        )
        super().__init__(code.replace("_", " "))


__all__ = ["ActorOpsRuntimeError"]
