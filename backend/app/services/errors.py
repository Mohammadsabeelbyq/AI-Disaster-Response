"""Domain errors. Services raise these; app/main.py turns them into HTTP responses
({"message": "...", "errors": [...]}). Internal details are logged, never returned."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []


class ValidationFailed(AppError):
    status_code = 422


class ImportFormatError(AppError):      # malformed JSON / CSV as a whole
    status_code = 400


class ImageRejected(AppError):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message, [message])
        self.status_code = status_code


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class StorageFailure(AppError):
    status_code = 500
