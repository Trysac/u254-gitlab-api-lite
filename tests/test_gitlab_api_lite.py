"""Behavior tests for the public API of gitlab_api_lite."""

from __future__ import annotations

import pytest

import gitlab_api_lite


def test_normalize_trims_and_lowercases() -> None:
    assert gitlab_api_lite.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        gitlab_api_lite.normalize(value)


def test_version_is_semver() -> None:
    parts = gitlab_api_lite.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
