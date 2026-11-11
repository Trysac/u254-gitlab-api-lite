# Architecture

## Purpose

`trysac-gitlab-api-lite` is a small, dependency-free Python library: Minimal GitLab REST v4 client over an injected transport: offset and keyset pagination, encoded project paths, RateLimit and Retry-After handling and same-origin next links

## Shape

```text
caller code --> gitlab_api_lite (public API in __init__.py)
                    |
                    +-- GitLabClient (URLs, pagination, retries, JSON decoding)
                    |       |
                    |       +-- Transport protocol (fake transport in tests)
                    |       +-- UrllibTransport (the only network I/O)
                    +-- project_path, GitLabError, Response
```

- **Public API**: the names listed in `__all__` of `src/gitlab_api_lite/__init__.py`. Anything else is
  internal and may change without a major version.
- **I/O**: all network access happens in `Transport.send`. `UrllibTransport` is the default real
  implementation; tests inject a fake transport and never touch the network.
- **Errors**: every failure is a `GitLabError(code, status)` carrying a machine-readable code; the
  library never prints or exits.
- **Side effects**: only logging through `logging.getLogger(__name__)` with a `NullHandler`, plus the
  optional `on_event` callback, whose payloads never contain the token.
- **Untrusted responses**: bodies are bounded by `max_body_bytes` before being decoded with the
  stdlib `json.loads`; pagination links must share scheme, host and port with `base_url`. The choice
  is recorded in [ADR 0002](decisions/0002-use-injected-transport-and-strict-same-origin-pagination.md).

## Quality contract

`scripts/check.py` is the single definition of the gates; `fabrica.json` tells the factory and CI
how to run it. See [TESTING.md](TESTING.md).

## Decisions

Architecture decisions are recorded in [decisions/](decisions/) as numbered ADRs.
