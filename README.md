# gitlab-api-lite

[![PyPI version](https://img.shields.io/pypi/v/trysac-gitlab-api-lite)](https://pypi.org/project/trysac-gitlab-api-lite/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-gitlab-api-lite)](LICENSE)
[![CI](https://github.com/Trysac/u254-gitlab-api-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u254-gitlab-api-lite/actions/workflows/ci.yml)

Minimal GitLab REST v4 client over an injected transport: offset and keyset pagination, encoded project paths, RateLimit and Retry-After handling and same-origin next links

## Problem

Scripts that read GitLab issues, merge requests or pipelines re-implement the same plumbing: X-Next-Page offset pagination, keyset Link headers, URL-encoded project paths and 429 handling. Mistakes return only the first page or follow a next link to another host with the token attached. This library does that plumbing once over an injected transport, so it is testable without a network.

## Install

```sh
pip install trysac-gitlab-api-lite
# or
uv add trysac-gitlab-api-lite
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
from gitlab_api_lite import GitLabClient, UrllibTransport, project_path

client = GitLabClient("https://gitlab.example.com", "glpat-secret", transport=UrllibTransport())
for issue in client.paginate("/projects/1/issues", {"state": "opened"}):
    print(issue["title"])
print(project_path("group/sub/my.project"))  # group%2Fsub%2Fmy.project
```

## Public API

`from gitlab_api_lite import GitLabClient, GitLabError, Response, Transport, UrllibTransport, project_path`

- `GitLabClient(base_url, token, *, transport, sleep=time.sleep, clock=time.time, max_retries=3, max_pages=100, max_body_bytes=10_485_760, allow_http=False, on_event=None)`: builds requests to `{base_url}/api/v4{path}`. `get(path, params=None) -> object` returns decoded JSON. `paginate(path, params=None, *, keyset=False) -> Iterator[dict[str, Any]]` yields items from list responses (or the dict when the response is a dict).
- `project_path(path_with_namespace) -> str`: `urllib.parse.quote(..., safe='')`; empty or whitespace input raises `GitLabError('invalid_path')`.
- `Response(status: int, headers: Mapping[str, str], body: bytes)`: frozen dataclass; `response['Header-Name']` and `response.get('Header-Name')` are case-insensitive.
- `Transport`: runtime-checkable protocol with `send(method: str, url: str, headers: Mapping[str, str]) -> Response`.
- `UrllibTransport(timeout_s=30.0, max_body_bytes=10_485_760)`: default transport; follows redirects only within the original origin and reads at most `max_body_bytes + 1` body bytes.
- `GitLabError(code, status=None)`: `code` is one of `invalid_path`, `insecure_url`, `foreign_link`, `rate_limited`, `unauthorized`, `not_found`, `http_error`, `response_too_large`, `invalid_json`, `too_many_pages`; `status` is the HTTP status when one applies.

Options and limits:

- Query parameters are sorted and URL-encoded. `per_page=100` is always sent; offset pagination adds `page=n`, keyset adds `pagination=keyset`.
- `base_url` must be `http` or `https` with a host and an empty or `/` path; `http` is rejected with `insecure_url` unless `allow_http=True`.
- Offset pagination follows `X-Next-Page` and stops when it is missing or empty after stripping; a non-integer or value below 1 stops pagination. Keyset pagination follows the `Link` header `rel=next` and stops when no next link exists; a next link whose scheme, host or port differs from `base_url` raises `foreign_link` before the request is sent.
- Only HTTP 429 is retried. The wait is a non-negative integer `Retry-After` in seconds, else `RateLimit-Reset` minus `clock()`, else `1.0`, clamped to `1.0..60.0`; after `max_retries` retries a further 429 raises `rate_limited`. HTTP 401 raises `unauthorized`, 404 raises `not_found`, and any other status at or above 300 raises `http_error` with the status.
- `max_pages` defaults to 100 and raises `too_many_pages` before fetching page 101. `max_body_bytes` defaults to `10_485_760` and raises `response_too_large` when `len(body)` exceeds it. UTF-8 decode or JSON parse failures raise `invalid_json`; pagination responses must be a list of dicts or a dict.
- `on_event` receives dicts with `event` (`request`, `retry` or `error`), `method`, `path` (the URL without query string) and `status`. Error strings and event payloads never include the token.

## Why not python-gitlab

`python-gitlab` is the best-known full GitLab API client. This library is deliberately smaller: it has no runtime dependencies, exposes a transport protocol that tests can replace with a fake, and enforces same-origin `Link: rel=next` pagination so the `PRIVATE-TOKEN` header is never sent to another host. It also handles GitLab-specific `X-Next-Page` offset pagination, keyset `Link` pagination and namespaced project paths (`group/sub/project`).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
