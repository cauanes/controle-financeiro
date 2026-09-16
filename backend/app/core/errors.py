class DomainError(Exception):
    def __init__(self, message: str, code: str = "VALIDATION_ERROR", status: int = 422):
        self.message, self.code, self.status = message, code, status
        super().__init__(message)


def require(condition, message, code="VALIDATION_ERROR", status=422):
    if not condition:
        raise DomainError(message, code, status)
