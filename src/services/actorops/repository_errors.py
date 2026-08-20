"""Stable ActorOps repository errors shared by focused SQL modules."""


class ActorOpsRepositoryError(RuntimeError):
    pass


class ActorOpsNotFound(ActorOpsRepositoryError):
    pass


class ActorOpsConflict(ActorOpsRepositoryError):
    pass
