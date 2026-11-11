# Security notes

## Threat model

`gitlab-api-lite` performs network I/O through `UrllibTransport` and decodes JSON returned by the GitLab server. The limits below are the defaults in the code.

### Defended

- **Token sent to a foreign host**: keyset `Link: rel=next` URLs must share scheme, host and port with `base_url`; otherwise the client raises `GitLabError('foreign_link')` before sending the request. `UrllibTransport` follows redirects only within the original origin and raises `HTTPError('cross-origin redirect blocked')` for a redirect to another origin.
- **Cleartext base URL**: `GitLabClient` accepts only `http` or `https` URLs with a host and an empty or `/` path; `http` is rejected with `GitLabError('insecure_url')` unless `allow_http=True` is passed explicitly.
- **Token leakage in logs, errors or events**: requests carry `PRIVATE-TOKEN`, `Accept: application/json` and `User-Agent: gitlab-api-lite`. `GitLabError` text contains only the code and optional HTTP status. `on_event` payloads contain `event`, `method`, `path` without query string, and `status`; the logger uses `logging.getLogger(__name__)` with a `NullHandler`. None of these payloads include the token.
- **Oversized responses**: the client raises `GitLabError('response_too_large')` when `len(response.body) > max_body_bytes` (default `10_485_760`). `UrllibTransport` reads at most `max_body_bytes + 1` bytes so the client can detect an over-limit body.
- **Malformed JSON**: bodies are decoded as UTF-8 and parsed with `json.loads`; `JSONDecodeError` or `UnicodeDecodeError` raises `GitLabError('invalid_json')`. No custom object hooks, `eval` or `exec` are used.
- **Pagination and retry bounds**: offset and keyset pagination stop at `max_pages` (default 100) with `too_many_pages`. Only HTTP 429 is retried, up to `max_retries` (default 3). The wait is a non-negative integer `Retry-After`, else `RateLimit-Reset - clock()`, else `1.0`, clamped to `1.0..60.0` seconds. Other statuses map to `unauthorized` (401), `not_found` (404) or `http_error` (>=300).

### Not defended

- The host in `base_url` is trusted with the token. A malicious or compromised GitLab server can read `PRIVATE-TOKEN`; the library cannot prevent that.
- `allow_http=True` permits cleartext HTTP. The library does not pin certificates and relies on `urllib`/Python TLS defaults for HTTPS verification.
- A custom `Transport` implementation can bypass the redirect and body-read limits enforced by `UrllibTransport`. The client still checks `len(body)` after the transport returns, so an unbounded transport can consume memory before that check.
- Same-origin redirects are followed. They may change the path but not the scheme, host or port.
- Endpoint authorization, token storage, token rotation, OAuth flows, write endpoints and GraphQL are out of scope.
- JSON content is parsed but not schema-validated.

## Publishing

The library does not manage release credentials or token storage. Report vulnerabilities through the repository security policy; do not include real tokens in reports.
