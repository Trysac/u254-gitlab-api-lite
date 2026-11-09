# gitlab-api-lite

[![PyPI version](https://img.shields.io/pypi/v/trysac-gitlab-api-lite)](https://pypi.org/project/trysac-gitlab-api-lite/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-gitlab-api-lite)](LICENSE)
[![CI](https://github.com/Trysac/u254-gitlab-api-lite/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u254-gitlab-api-lite/actions/workflows/ci.yml)

Minimal GitLab REST v4 client over an injected transport: offset and keyset pagination, encoded project paths, RateLimit and Retry-After handling and same-origin next links

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-gitlab-api-lite
# or
uv add trysac-gitlab-api-lite
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import gitlab_api_lite

# normalize() trims surrounding whitespace and lower-cases the text.
print(gitlab_api_lite.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    gitlab_api_lite.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
