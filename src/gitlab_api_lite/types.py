from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Response:
    """HTTP response returned by a :class:`Transport`.

    Header lookup is case-insensitive.
    """

    status: int
    headers: Mapping[str, str]
    body: bytes

    def __getitem__(self, key: str) -> str:
        for k, v in self.headers.items():
            if k.lower() == key.lower():
                return v
        raise KeyError(key)

    def get(self, key: str, default: str | None = None) -> str | None:
        """Return header value case-insensitively, or *default* if missing."""
        try:
            return self[key]
        except KeyError:
            return default


@runtime_checkable
class Transport(Protocol):
    """Protocol for sending HTTP requests."""

    def send(self, method: str, url: str, headers: Mapping[str, str]) -> Response:
        """Send an HTTP request and return the response."""
        ...
