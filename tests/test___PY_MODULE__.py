from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

import pytest

from gitlab_api_lite import (
    GitLabClient,
    GitLabError,
    Response,
    UrllibTransport,
    project_path,
)
from gitlab_api_lite.client import (
    _find_next_link,
    _parse_link_header,
    _parse_retry_after,
    _same_origin,
)


def make_response(
    status: int = 200,
    headers: Mapping[str, str] | None = None,
    body: bytes | str | object = b"",
) -> Response:
    if isinstance(body, str):
        body = body.encode()
    elif not isinstance(body, bytes):
        body = json.dumps(body).encode()
    return Response(status=status, headers=headers or {}, body=body)


class FakeTransport:
    def __init__(
        self, responses: list[Response | Callable[[str, str, Mapping[str, str]], Response]]
    ):
        self.responses = responses
        self.requests: list[tuple[str, str, Mapping[str, str]]] = []

    def send(self, method: str, url: str, headers: Mapping[str, str]) -> Response:
        self.requests.append((method, url, headers))
        resp = self.responses.pop(0)
        if callable(resp):
            return resp(method, url, headers)
        return resp


def test_project_path() -> None:
    assert project_path("group/sub/my.project") == "group%2Fsub%2Fmy.project"
    with pytest.raises(GitLabError) as exc_info:
        project_path("")
    assert exc_info.value.code == "invalid_path"
    with pytest.raises(GitLabError) as exc_info:
        project_path("   ")
    assert exc_info.value.code == "invalid_path"


def test_response_case_insensitive_headers() -> None:
    resp = make_response(headers={"X-Next-Page": "2"})
    assert resp["x-next-page"] == "2"
    assert resp.get("X-NEXT-PAGE") == "2"
    assert resp.get("Missing", "default") == "default"
    with pytest.raises(KeyError):
        _ = resp["missing"]


def test_get_returns_dict() -> None:
    transport = FakeTransport([make_response(body={"id": 1})])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    result = client.get("/projects/1")
    assert result == {"id": 1}
    assert len(transport.requests) == 1
    method, url, headers = transport.requests[0]
    assert method == "GET"
    assert url == "https://gitlab.example.com/api/v4/projects/1?per_page=100"
    assert headers["PRIVATE-TOKEN"] == "glpat-secret"
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"] == "gitlab-api-lite"


def test_get_returns_list() -> None:
    transport = FakeTransport([make_response(body=[{"id": 1}, {"id": 2}])])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    result = client.get("/projects")
    assert isinstance(result, list)
    assert len(result) == 2


def test_offset_pagination_exact_urls_and_spaces() -> None:
    responses = [
        make_response(body=[{"iid": 1}, {"iid": 2}], headers={"X-Next-Page": " 2 "}),
        make_response(body=[{"iid": 3}], headers={"X-Next-Page": " "}),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    items = list(client.paginate("/projects/1/issues", {"state": "opened"}))
    assert len(items) == 3
    assert [item["iid"] for item in items] == [1, 2, 3]
    assert len(transport.requests) == 2
    # Verify exact URLs: sorted params, per_page, page
    expected1 = (
        "https://gitlab.example.com/api/v4/projects/1/issues?page=1&per_page=100&state=opened"
    )
    expected2 = (
        "https://gitlab.example.com/api/v4/projects/1/issues?page=2&per_page=100&state=opened"
    )
    assert transport.requests[0][1] == expected1
    assert transport.requests[1][1] == expected2


def test_keyset_pagination_follows_link_and_same_origin() -> None:
    link_header = '<https://gitlab.example.com/api/v4/projects?id_after=42&pagination=keyset&per_page=100>; rel="next"'
    responses = [
        make_response(body=[{"id": 1}], headers={"Link": link_header}),
        make_response(body=[{"id": 2}], headers={}),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    items = list(client.paginate("/projects", keyset=True))
    assert len(items) == 2
    # First request should include pagination=keyset and per_page=100
    first_url = transport.requests[0][1]
    assert first_url.startswith("https://gitlab.example.com/api/v4/projects?")
    assert "pagination=keyset" in first_url
    assert "per_page=100" in first_url
    # Second request uses the next link verbatim
    assert (
        transport.requests[1][1]
        == "https://gitlab.example.com/api/v4/projects?id_after=42&pagination=keyset&per_page=100"
    )


def test_keyset_foreign_link_raises_without_sending() -> None:
    evil_link = '<https://evil.example/api/v4/projects>; rel="next"'
    responses = [
        make_response(body=[{"id": 1}], headers={"Link": evil_link}),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    iterator = client.paginate("/projects", keyset=True)
    assert next(iterator) == {"id": 1}
    with pytest.raises(GitLabError) as exc_info:
        next(iterator)
    assert exc_info.value.code == "foreign_link"
    assert len(transport.requests) == 1  # second request not sent


def test_unauthorized_emits_error_event_without_token() -> None:
    events: list[dict[str, object]] = []
    transport = FakeTransport([make_response(status=401)])
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        on_event=lambda e: events.append(e),
    )
    with pytest.raises(GitLabError) as exc_info:
        client.get("/projects/1")
    assert exc_info.value.code == "unauthorized"
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["method"] == "GET"
    assert error_events[0]["path"] == "https://gitlab.example.com/api/v4/projects/1"
    assert error_events[0]["status"] == 401
    for event in events:
        for value in event.values():
            if isinstance(value, str):
                assert "glpat-secret" not in value


def test_foreign_link_emits_error_event_without_token() -> None:
    events: list[dict[str, object]] = []
    evil_link = '<https://evil.example/api/v4/projects>; rel="next"'
    transport = FakeTransport([make_response(body=[{"id": 1}], headers={"Link": evil_link})])
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        on_event=lambda e: events.append(e),
    )
    iterator = client.paginate("/projects", keyset=True)
    assert next(iterator) == {"id": 1}
    with pytest.raises(GitLabError) as exc_info:
        next(iterator)
    assert exc_info.value.code == "foreign_link"
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert error_events[0]["path"] == "https://evil.example/api/v4/projects"
    assert error_events[0]["status"] is None
    assert len(transport.requests) == 1
    for event in events:
        for value in event.values():
            if isinstance(value, str):
                assert "glpat-secret" not in value


def test_rate_limit_retry_after_integer() -> None:
    sleep_calls: list[float] = []
    responses = [
        make_response(status=429, headers={"Retry-After": "7"}),
        make_response(body=[{"id": 1}]),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        sleep=lambda s: sleep_calls.append(s),
    )
    result = client.get("/items")
    assert result == [{"id": 1}]
    assert sleep_calls == [7.0]
    assert len(transport.requests) == 2


def test_rate_limit_fallback_to_ratelimit_reset() -> None:
    sleep_calls: list[float] = []
    responses = [
        make_response(status=429, headers={"RateLimit-Reset": "1700000010"}),
        make_response(body=[]),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        sleep=lambda s: sleep_calls.append(s),
        clock=lambda: 1700000000.0,
    )
    result = client.get("/items")
    assert result == []
    assert sleep_calls == [10.0]


def test_rate_limit_clamping() -> None:
    # Test lower clamp
    sleep_calls: list[float] = []
    responses = [
        make_response(status=429, headers={"Retry-After": "0"}),
        make_response(body=[]),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        sleep=lambda s: sleep_calls.append(s),
    )
    client.get("/items")
    assert sleep_calls == [1.0]

    # Test upper clamp
    sleep_calls = []
    responses = [
        make_response(status=429, headers={"Retry-After": "120"}),
        make_response(body=[]),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        sleep=lambda s: sleep_calls.append(s),
    )
    client.get("/items")
    assert sleep_calls == [60.0]


def test_rate_limit_max_retries_exceeded() -> None:
    responses = [
        make_response(status=429, headers={"Retry-After": "1"}),
        make_response(status=429, headers={"Retry-After": "1"}),
        make_response(status=429, headers={"Retry-After": "1"}),
        make_response(status=429, headers={"Retry-After": "1"}),  # fourth 429
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        sleep=lambda s: None,
        max_retries=3,
    )
    with pytest.raises(GitLabError) as exc_info:
        client.get("/items")
    assert exc_info.value.code == "rate_limited"
    assert len(transport.requests) == 4


def test_error_statuses() -> None:
    # 401
    transport = FakeTransport([make_response(status=401)])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    with pytest.raises(GitLabError) as exc_info:
        client.get("/unauthorized")
    assert exc_info.value.code == "unauthorized"

    # 404
    transport = FakeTransport([make_response(status=404)])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    with pytest.raises(GitLabError) as exc_info:
        client.get("/missing")
    assert exc_info.value.code == "not_found"

    # 500
    transport = FakeTransport([make_response(status=500)])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    with pytest.raises(GitLabError) as exc_info:
        client.get("/error")
    assert exc_info.value.code == "http_error"
    assert exc_info.value.status == 500


def test_no_token_leak_in_errors_or_events() -> None:
    events: list[dict[str, object]] = []
    transport = FakeTransport([make_response(status=401)])
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        on_event=lambda e: events.append(e),
    )
    with pytest.raises(GitLabError) as exc_info:
        client.get("/projects/1")
    error_str = str(exc_info.value)
    assert "glpat-secret" not in error_str
    # Check events
    assert len(events) >= 1
    for event in events:
        for value in event.values():
            if isinstance(value, str):
                assert "glpat-secret" not in value


def test_response_too_large() -> None:
    transport = FakeTransport([make_response(body=b"x" * (10_485_760 + 1))])
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        max_body_bytes=10_485_760,
    )
    with pytest.raises(GitLabError) as exc_info:
        client.get("/large")
    assert exc_info.value.code == "response_too_large"


def test_invalid_json() -> None:
    transport = FakeTransport([make_response(body=b"not json")])
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    with pytest.raises(GitLabError) as exc_info:
        client.get("/bad")
    assert exc_info.value.code == "invalid_json"


def test_max_pages_limit_offset() -> None:
    # We return a next page header infinity; with max_pages=2 should raise after 2 pages
    responses = [
        make_response(body=[{"id": 1}], headers={"X-Next-Page": "2"}),
        make_response(body=[{"id": 2}], headers={"X-Next-Page": "3"}),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        max_pages=2,
    )
    iterator = client.paginate("/items")
    assert next(iterator) == {"id": 1}
    assert next(iterator) == {"id": 2}
    with pytest.raises(GitLabError) as exc_info:
        next(iterator)
    assert exc_info.value.code == "too_many_pages"


def test_max_pages_limit_keyset() -> None:
    link = '<https://gitlab.example.com/api/v4/items?page=2&pagination=keyset&per_page=100>; rel="next"'
    responses = [
        make_response(body=[{"id": 1}], headers={"Link": link}),
        make_response(body=[{"id": 2}], headers={"Link": link}),
    ]
    transport = FakeTransport(responses)
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        max_pages=2,
    )
    iterator = client.paginate("/items", keyset=True)
    assert next(iterator) == {"id": 1}
    assert next(iterator) == {"id": 2}
    with pytest.raises(GitLabError) as exc_info:
        next(iterator)
    assert exc_info.value.code == "too_many_pages"


def test_allow_http_flag() -> None:
    # default rejects http
    with pytest.raises(GitLabError) as exc_info:
        GitLabClient("http://gitlab.example.com", "token", transport=FakeTransport([]))
    assert exc_info.value.code == "insecure_url"
    # allow_http=True allows
    transport = FakeTransport([make_response(body={})])
    client = GitLabClient(
        "http://gitlab.example.com",
        "token",
        transport=transport,
        allow_http=True,
    )
    assert client.get("/test") == {}


def test_invalid_base_url() -> None:
    with pytest.raises(GitLabError):
        GitLabClient("ftp://example.com", "token", transport=FakeTransport([]))
    with pytest.raises(GitLabError):
        GitLabClient("https://example.com/path", "token", transport=FakeTransport([]))


def test_on_event_called() -> None:
    events: list[dict[str, object]] = []
    transport = FakeTransport([make_response(body=[])])
    client = GitLabClient(
        "https://gitlab.example.com",
        "glpat-secret",
        transport=transport,
        on_event=lambda e: events.append(e),
    )
    client.get("/items")
    assert len(events) >= 1
    first_event = events[0]
    assert first_event["event"] == "request"
    assert first_event["method"] == "GET"
    assert first_event["path"] == "https://gitlab.example.com/api/v4/items"
    assert "status" in first_event


def test_parse_link_header_multiple() -> None:
    header = (
        '<https://a/prev>; rel="prev", <https://a/next>; rel="next", <https://a/last>; rel="last"'
    )
    links = _parse_link_header(header)
    assert len(links) == 3
    assert _find_next_link(header) == "https://a/next"


def test_parse_retry_after_http_date_ignored() -> None:
    headers = {"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
    assert _parse_retry_after(headers) is None


def test_same_origin() -> None:
    assert _same_origin("https://a/b", "https://a")
    assert not _same_origin("https://a/b", "https://b")
    assert not _same_origin("http://a/b", "https://a")
    assert not _same_origin("https://a:8080/b", "https://a")


def test_urllib_transport_success(monkeypatch: pytest.MonkeyPatch) -> None:
    read_sizes: list[int] = []

    class FakeResponse:
        status: ClassVar[int] = 200
        headers: ClassVar[dict[str, str]] = {"Content-Type": "application/json"}

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return b'{"ok": true}'

        def __enter__(self) -> FakeResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def fake_open(req: Any, timeout: float) -> FakeResponse:
        return FakeResponse()

    transport = UrllibTransport(timeout_s=1.0, max_body_bytes=10)
    monkeypatch.setattr(transport._opener, "open", fake_open)
    resp = transport.send("GET", "https://example.com", {})
    assert resp.status == 200
    assert resp.body == b'{"ok": true}'
    # Bounded read: at most max_body_bytes + 1 bytes are requested.
    assert read_sizes == [11]


def test_urllib_transport_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_open(req: Any, timeout: float) -> Any:
        raise urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, io.BytesIO(b"not found")
        )

    transport = UrllibTransport(max_body_bytes=100)
    monkeypatch.setattr(transport._opener, "open", fake_open)
    resp = transport.send("GET", "https://example.com", {})
    assert resp.status == 404
    assert resp.body == b"not found"


def test_cross_origin_redirect_is_blocked() -> None:
    from gitlab_api_lite.transport import _SameOriginRedirect

    handler = _SameOriginRedirect()
    req = urllib.request.Request(
        "https://gitlab.example.com/api/v4/projects",
        headers={"PRIVATE-TOKEN": "glpat-secret"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(
            req,
            io.BytesIO(b""),
            302,
            "Found",
            {},
            "https://evil.example/api/v4/projects",
        )
    assert exc_info.value.code == 302


def test_same_origin_redirect_is_allowed() -> None:
    from gitlab_api_lite.transport import _SameOriginRedirect

    handler = _SameOriginRedirect()
    req = urllib.request.Request("https://gitlab.example.com/api/v4/projects")
    new_req = handler.redirect_request(
        req,
        io.BytesIO(b""),
        302,
        "Found",
        {},
        "https://gitlab.example.com/api/v4/projects?page=2",
    )
    assert new_req is not None
    assert new_req.full_url == "https://gitlab.example.com/api/v4/projects?page=2"


def test_redirect_status_is_an_error() -> None:
    transport = FakeTransport(
        [make_response(status=302, headers={"Location": "https://evil.example/"})]
    )
    client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=transport)
    with pytest.raises(GitLabError) as exc_info:
        client.get("/projects")
    assert exc_info.value.code == "http_error"
    assert exc_info.value.status == 302
