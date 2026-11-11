# Use injected transport and strict same-origin pagination

Status: accepted (generated, pending human review)

## Context

The library must be testable without network access and must never send the private token to a foreign host when following pagination links.

## Decision

Implement an in-memory Transport protocol, default UrllibTransport, and validate every keyset 'next' link against the base URL's scheme and netloc. Offset pagination relies on X-Next-Page, which is relative to the same origin by definition.

## Consequences

Tests use a fake transport that records requests. The client can be used with any HTTP backend. Same-origin enforcement prevents token leakage but may reject legitimate cross-origin redirects, which are out of scope.
