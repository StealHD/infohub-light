"""Short-transaction Attempt event sink used by remote clients."""

from __future__ import annotations

from .domain import AttemptStatus, FailureClass
from .ports import AttemptEventSink
from .repository import ActorOpsConflict, ActorOpsRepository


class RepositoryAttemptEvents(AttemptEventSink):
    def __init__(self, repository: ActorOpsRepository, attempt_id: str) -> None:
        self.repository = repository
        self.attempt_id = attempt_id

    def _row(self):
        return self.repository.get_attempt(self.attempt_id)

    def starting(self, *, secret_ref_id, secret_version, pool_generation) -> None:
        row = self._row()
        with self.repository.transaction():
            if str(row["status"]) == AttemptStatus.CREATED.value:
                self.repository.update_attempt_start(
                    self.attempt_id,
                    expected_generation=int(row["generation"]),
                    secret_ref_id=secret_ref_id,
                    secret_version=secret_version,
                    pool_generation=pool_generation,
                )
            elif str(row["status"]) == AttemptStatus.STARTING.value:
                self.repository.replace_attempt_credential(
                    self.attempt_id,
                    expected_generation=int(row["generation"]),
                    secret_ref_id=secret_ref_id,
                    secret_version=secret_version,
                    pool_generation=pool_generation,
                )
            else:
                raise ActorOpsConflict("attempt cannot acquire another credential")

    def registered(self, *, remote_run_id: str, dataset_id: str | None) -> None:
        row = self._row()
        with self.repository.transaction():
            self.repository.register_attempt_run(
                self.attempt_id,
                expected_generation=int(row["generation"]),
                remote_run_id=remote_run_id,
                dataset_id=dataset_id,
            )

    def running(self) -> None:
        row = self._row()
        with self.repository.transaction():
            self.repository.transition_attempt(
                self.attempt_id,
                AttemptStatus.REGISTERED,
                AttemptStatus.RUNNING,
                expected_generation=int(row["generation"]),
            )

    def start_unknown(self, *, error_code: str) -> None:
        row = self._row()
        with self.repository.transaction():
            self.repository.transition_attempt(
                self.attempt_id,
                AttemptStatus.STARTING,
                AttemptStatus.START_UNKNOWN,
                error_class=FailureClass.REMOTE_UNKNOWN.value,
                error_code=error_code,
                expected_generation=int(row["generation"]),
            )

    def remote_unknown(self, *, error_code: str) -> None:
        with self.repository.transaction():
            self.repository.annotate_attempt(
                self.attempt_id,
                failure_class=FailureClass.REMOTE_UNKNOWN.value,
                error_code=error_code,
            )
