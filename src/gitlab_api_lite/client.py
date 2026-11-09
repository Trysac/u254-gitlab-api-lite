from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any, NoReturn
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from .errors import ErrorCode, GitLabError
from .types import Response, Transport

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

MAX_BODY_BYTES_DEFAULT = 10_485_760
MAX_RETRIES_DEFAULT = 3
MAX_PAGES_DEFAULT = 100


def project_path(path_with_namespace: str) -> str:
    """URL-encode a GitLab project path (e.g. ``group/subgroup/project``).

    Raises:
        GitLabError: if ``path_with_namespace`` is empty or whitespace, with code
            ``"invalid_path"``.
    """
    if not path_with_namespace.strip():
        raise GitLabError("invalid_path")
    return quote(path_with_namespace, safe="")


def _get_header_case_insensitive(headers: Mapping[str, str], name: str) -> str | None:
    name_low = name.lower()
    for k, v in headers.items():
        if k.lower() == name_low:
            return v
    return None


def _parse_retry_after(headers: Mapping[str, str]) -> float | None:
    retry_after = _get_header_case_insensitive(headers, "Retry-After")
    if retry_after is None:
        return None
    # Only non-negative integers are accepted; HTTP dates are ignored.
    if retry_after.isdigit() or (retry_after.startswith("-") and retry_after[1:].isdigit()):
        parsed = int(retry_after)
        if parsed >= 0:
            return float(parsed)
    return None


def _strip_query(url: str) -> str:
    split = urlsplit(url)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))


def _same_origin(url: str, base_url: str) -> bool:
    u = urlsplit(url)
    b = urlsplit(base_url)
    return u.scheme == b.scheme and u.netloc == b.netloc


def _parse_link_header(header: str) -> list[tuple[str, dict[str, str]]]:
    """Parse an RFC 8288 Link header.

    Returns a list of ``(url, params)`` tuples. Parameter names are lowercased;
    quoted values are unquoted. This is a best-effort parser suitable for GitLab's
    pagination links.
    """
    links: list[tuple[str, dict[str, str]]] = []
    parts = header.split(",")
    for part in parts:
        part = part.strip()
        if not part or not part.startswith("<"):
            continue
        end = part.find(">")
        if end == -1:
            continue
        url = part[1:end]
        rest = part[end + 1 :].strip()
        params: dict[str, str] = {}
        if rest:
            for param in rest.split(";"):
                param = param.strip()
                if not param:
                    continue
                if "=" in param:
                    name, value = param.split("=", 1)
                    name = name.strip().lower()
                    value = value.strip()
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    params[name] = value
                else:
                    params[param.strip().lower()] = ""
        links.append((url, params))
    return links


def _find_next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    links = _parse_link_header(link_header)
    for url, params in links:
        rel = params.get("rel", "")
        rel_tokens = rel.split()
        if "next" in rel_tokens:
            return url
    return None


def _clamp_wait(wait: float) -> float:
    return max(1.0, min(wait, 60.0))


class GitLabClient:
    """Minimal GitLab REST API v4 client.

    All requests are sent to ``{base_url}/api/v4{path}``. Pagination follows
    GitLab's documented offset (``X-Next-Page``) and keyset (``Link`` header)
    mechanisms. Retries are performed only on HTTP 429.

    Args:
        base_url: GitLab instance origin, e.g. ``https://gitlab.example.com``.
        token: Secret token; sent as ``PRIVATE-TOKEN`` header.
        transport: Object with a ``send`` method implementing :class:`Transport`.
        sleep: Callable used to wait before retries.
        clock: Callable returning current Unix time.
        max_retries: Maximum number of retries for 429 responses.
        max_pages: Maximum number of pages to fetch in a single pagination call.
        max_body_bytes: Maximum response body size in bytes.
        allow_http: If ``False`` (default), ``http://`` base URLs are rejected.
        on_event: Optional callback receiving event dicts.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        max_retries: int = MAX_RETRIES_DEFAULT,
        max_pages: int = MAX_PAGES_DEFAULT,
        max_body_bytes: int = MAX_BODY_BYTES_DEFAULT,
        allow_http: bool = False,
        on_event: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise GitLabError("insecure_url")
        if parsed.scheme == "http" and not allow_http:
            raise GitLabError("insecure_url")
        if parsed.path not in ("", "/"):
            raise GitLabError("insecure_url")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.transport = transport
        self.sleep = sleep
        self.clock = clock
        self.max_retries = max_retries
        self.max_pages = max_pages
        self.max_body_bytes = max_body_bytes
        self.on_event = on_event
        self._common_headers: dict[str, str] = {
            "PRIVATE-TOKEN": token,
            "Accept": "application/json",
            "User-Agent": "gitlab-api-lite",
        }

    def _emit(self, event: str, method: str, path: str, status: int | None) -> None:
        if self.on_event is not None:
            self.on_event({"event": event, "method": method, "path": path, "status": status})

    def _fail(
        self,
        code: ErrorCode,
        *,
        method: str = "GET",
        url: str = "",
        status: int | None = None,
    ) -> NoReturn:
        """Emit an ``error`` event (never containing the token) and raise."""
        self._emit("error", method, _strip_query(url), status)
        raise GitLabError(code, status=status)

    def _request(self, method: str, url: str) -> Response:
        headers = dict(self._common_headers)
        self._emit("request", method, _strip_query(url), None)
        logger.debug("Sending %s %s", method, _strip_query(url))
        return self.transport.send(method, url, headers)

    def _request_with_retry(self, method: str, url: str) -> Response:
        retries = 0
        while True:
            response = self._request(method, url)
            if response.status == 429:
                if retries >= self.max_retries:
                    self._fail("rate_limited", method=method, url=url, status=429)
                wait = self._compute_wait(response.headers)
                retries += 1
                self._emit("retry", method, _strip_query(url), 429)
                logger.debug("Retrying after %.1fs (attempt %d)", wait, retries)
                self.sleep(wait)
                continue
            if response.status == 401:
                self._fail("unauthorized", method=method, url=url, status=401)
            if response.status == 404:
                self._fail("not_found", method=method, url=url, status=404)
            if response.status >= 300:
                self._fail("http_error", method=method, url=url, status=response.status)
            return response

    def _compute_wait(self, headers: Mapping[str, str]) -> float:
        retry_after = _parse_retry_after(headers)
        if retry_after is not None:
            return _clamp_wait(retry_after)
        rate_limit_reset = _get_header_case_insensitive(headers, "RateLimit-Reset")
        if rate_limit_reset is not None:
            try:
                reset_time = float(rate_limit_reset)
                now = self.clock()
                wait = reset_time - now
                if wait > 0:
                    return _clamp_wait(wait)
            except ValueError:
                pass
        return 1.0

    def _build_url(
        self,
        path: str,
        params: Mapping[str, str | int] | None,
        page: int | None,
        keyset: bool = False,
    ) -> str:
        base = self.base_url + "/api/v4" + path
        query_params: dict[str, str] = {}
        if params:
            for k, v in params.items():
                query_params[str(k)] = str(v)
        if keyset:
            query_params["pagination"] = "keyset"
            query_params["per_page"] = "100"
        else:
            query_params["per_page"] = "100"
            if page is not None:
                query_params["page"] = str(page)
        if query_params:
            sorted_items = sorted(query_params.items())
            encoded = urlencode(sorted_items)
            base += "?" + encoded
        return base

    def get(self, path: str, params: Mapping[str, str | int] | None = None) -> object:
        """Send a GET request and return the decoded JSON object."""
        url = self._build_url(path, params, page=None, keyset=False)
        response = self._request_with_retry("GET", url)
        return self._decode_response(response, url)

    def paginate(
        self,
        path: str,
        params: Mapping[str, str | int] | None = None,
        *,
        keyset: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Iterate over all items, following GitLab pagination.

        Yields each item as a dictionary. For offset pagination, follows
        ``X-Next-Page``; for keyset, follows the ``Link`` header with
        ``rel=next``.
        """
        if keyset:
            yield from self._paginate_keyset(path, params)
        else:
            yield from self._paginate_offset(path, params)

    def _decode_response(self, response: Response, url: str = "") -> object:
        if len(response.body) > self.max_body_bytes:
            self._fail("response_too_large", url=url, status=response.status)
        try:
            data: object = json.loads(response.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._fail("invalid_json", url=url, status=response.status)
        return data

    def _paginate_offset(
        self,
        path: str,
        params: Mapping[str, str | int] | None,
    ) -> Iterator[dict[str, Any]]:
        page = 1
        pages_fetched = 0
        while True:
            url = self._build_url(path, params, page, keyset=False)
            if pages_fetched >= self.max_pages:
                self._fail("too_many_pages", url=url)
            response = self._request_with_retry("GET", url)
            data = self._decode_response(response, url)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        self._fail("invalid_json", url=url, status=response.status)
                    yield item
            elif isinstance(data, dict):
                yield data
            else:
                self._fail("invalid_json", url=url, status=response.status)
            pages_fetched += 1
            next_page = response.get("X-Next-Page")
            if next_page is None or next_page.strip() == "":
                break
            try:
                page = int(next_page.strip())
            except ValueError:
                break
            if page < 1:
                break

    def _paginate_keyset(
        self,
        path: str,
        params: Mapping[str, str | int] | None,
    ) -> Iterator[dict[str, Any]]:
        url = self._build_url(path, params, None, keyset=True)
        pages_fetched = 0
        while True:
            if pages_fetched >= self.max_pages:
                self._fail("too_many_pages", url=url)
            response = self._request_with_retry("GET", url)
            data = self._decode_response(response, url)
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        self._fail("invalid_json", url=url, status=response.status)
                    yield item
            elif isinstance(data, dict):
                yield data
            else:
                self._fail("invalid_json", url=url, status=response.status)
            pages_fetched += 1
            link_header = response.get("Link")
            next_url = _find_next_link(link_header)
            if next_url is None:
                break
            if not _same_origin(next_url, self.base_url):
                self._fail("foreign_link", url=next_url)
            url = next_url
