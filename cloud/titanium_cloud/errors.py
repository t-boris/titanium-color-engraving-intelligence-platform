"""The refusals of the API, one class per status code, raised by the repository and the checks and answered as JSON
``{"error": message, "code": code}`` by the application."""
from __future__ import annotations


class ApiError(Exception):
    status = 400

    def __init__(self, message: str, code: str = "bad_request"):
        super().__init__(message)
        self.code = code


class Unauthorized(ApiError):
    status = 401

    def __init__(self, message: str = "sign in to do this", code: str = "unauthorized"):
        super().__init__(message, code)


class Forbidden(ApiError):
    status = 403

    def __init__(self, message: str = "only the laboratory's owner can do this", code: str = "forbidden"):
        super().__init__(message, code)


class NotFound(ApiError):
    status = 404

    def __init__(self, message: str = "there is no such laboratory or release", code: str = "not_found"):
        super().__init__(message, code)


class Conflict(ApiError):
    status = 409

    def __init__(self, message: str, code: str = "conflict"):
        super().__init__(message, code)


class Gone(ApiError):
    status = 410

    def __init__(self, message: str, code: str = "gone"):
        super().__init__(message, code)


class TooLarge(ApiError):
    status = 413

    def __init__(self, message: str, code: str = "too_large"):
        super().__init__(message, code)


class Invalid(ApiError):
    status = 422

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message, code)
