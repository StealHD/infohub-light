"""Safe exception locations for probe failures; never include upstream text."""
import logging
from ...logging_diagnostics import log_exception


def record_remote_exception(exception, error_code):
    log_exception(logging.getLogger(__name__), stage='actorops_probe',
                  error_code=error_code, exception=exception)


def unexpected_remote_error(exception, error_code):
    from .errors import ActorOpsRuntimeError
    from .domain import FailureClass
    record_remote_exception(exception, error_code)
    return ActorOpsRuntimeError(error_code, failure_class=FailureClass.INTERNAL)
