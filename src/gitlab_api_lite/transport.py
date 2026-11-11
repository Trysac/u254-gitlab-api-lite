from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import IO, Any
from urllib.parse import urlsplit

from .types import Response, Transport

MAX_BODY_BYTES_DEFAULT = 10_485_760


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that refuses to follow redirects to another origin."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urlsplit(newurl)[:2] != urlsplit(req.full_url)[:2]:
            raise urllib.error.HTTPError(newurl, code, "cross-origin redirect blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrllibTransport(Transport):
    """Default transport using :mod:`urllib.request`.

    Redirects are followed only within the original origin, so the request
    headers (including ``PRIVATE-TOKEN``) are never forwarded to another host.

    Args:
        timeout_s: Timeout in seconds for each request.
        max_body_bytes: Maximum number of body bytes to read; one extra byte is
            read so the client can detect an over-limit body.
    """

    def __init__(
        self, timeout_s: float = 30.0, max_body_bytes: int = MAX_BODY_BYTES_DEFAULT
    ) -> None:
        self.timeout_s = timeout_s
        self.max_body_bytes = max_body_bytes
        self._opener = urllib.request.build_opener(_SameOriginRedirect())

    def send(self, method: str, url: str, headers: Mapping[str, str]) -> Response:
        # The URL always comes from GitLabClient, which only builds http(s) URLs.
        req = urllib.request.Request(url, method=method, headers=dict(headers))  # noqa: S310
        limit = self.max_body_bytes + 1
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                body = resp.read(limit)
                return Response(status=resp.status, headers=dict(resp.headers), body=body)
        except urllib.error.HTTPError as exc:
            body = exc.read(limit)
            return Response(status=exc.code, headers=dict(exc.headers), body=body)
