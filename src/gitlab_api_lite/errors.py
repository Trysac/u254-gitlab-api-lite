from __future__ import annotations

from typing import Literal

ErrorCode = Literal[
    "invalid_path",
    "insecure_url",
    "foreign_link",
    "rate_limited",
    "unauthorized",
    "not_found",
    "http_error",
    "response_too_large",
    "invalid_json",
    "too_many_pages",
]


class GitLabError(Exception):
    """Base error for gitlab-api-lite.

    Attributes:
        code: Machine-readable error category.
        status: Optional HTTP status code associated with the error.
    """

    def __init__(self, code: ErrorCode, status: int | None = None) -> None:
        self.code = code
        self.status = status
        super().__init__(code if status is None else f"{code} (HTTP {status})")
