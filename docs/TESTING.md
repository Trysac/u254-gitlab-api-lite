# Testing

## Running

The repository contains pytest tests in `tests/test___PY_MODULE__.py`. Run them from the repository root:

```sh
pytest tests/test___PY_MODULE__.py
```

## Policy

- Tests use the public API and inject `FakeTransport`; they do not open sockets or read the wall clock. Where retries are tested, `sleep` and `clock` are injected.
- Assertions cover exact request URLs, returned objects, raised `GitLabError.code` and `status`, `sleep`/`clock` calls, and `on_event` payloads.
- Tests are deterministic and do not depend on test order.

## Tiers

All tests in `tests/test___PY_MODULE__.py` are unit tests. There is no external-service or download tier in this repository. The module defines `FakeTransport` and `make_response` locally.

## Layout

Tests live in `tests/test___PY_MODULE__.py`; helper classes and functions are defined in the same file.

## What the tests cover

- `test_project_path`: `group/sub/my.project` becomes `group%2Fsub%2Fmy.project`; empty input raises `invalid_path`.
- `test_response_case_insensitive_headers`: `Response` header lookup ignores case and `get` returns defaults.
- `test_get_returns_dict` and `test_get_returns_list`: `get` returns decoded JSON objects and arrays.
- `test_offset_pagination_exact_urls_and_spaces`: offset pagination sends exact `page`, `per_page` and `state` query strings and handles `X-Next-Page` values with surrounding spaces.
- `test_keyset_pagination_follows_link_and_same_origin`: keyset pagination follows a same-origin `Link: rel=next` URL verbatim.
- `test_keyset_foreign_link_raises_without_sending`: a foreign next link raises `foreign_link` without a second request.
- `test_unauthorized_emits_error_event_without_token` and `test_foreign_link_emits_error_event_without_token`: `error` events carry the path without query string and never the token.
- `test_rate_limit_retry_after_integer`, `test_rate_limit_fallback_to_ratelimit_reset` and `test_rate_limit_clamping`: 429 wait calculation uses `Retry-After`, falls back to `RateLimit-Reset - clock()`, and clamps to `1.0..60.0`.
- `test_rate_limit_max_retries_exceeded`: after `max_retries`, a further 429 raises `rate_limited`.
- `test_error_statuses`: 401 raises `unauthorized`, 404 raises `not_found`, and 500 raises `http_error` with status 500.
- `test_no_token_leak_in_errors_or_events`: token strings are absent from error text and event payloads.
- `test_response_too_large`, `test_invalid_json`, `test_max_pages_limit_offset` and `test_max_pages_limit_keyset`: response size, JSON decode and page-count limits raise the matching codes.
