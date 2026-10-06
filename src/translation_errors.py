"""Safe translation errors shared by the adapter, service and API layers."""

class TranslationError(RuntimeError):
    retryable = False

    def __init__(self, code, message, status_code=409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
