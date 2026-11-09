"""Behavior tests for the public API of gitlab_api_lite."""

from __future__ import annotations

import pytest

import gitlab_api_lite
from gitlab_api_lite import GitLabError, Response


def test_public_api_is_exported() -> None:
    expected = [
        "GitLabClient",
        "GitLabError",
        "Response",
        "Transport",
        "UrllibTransport",
        "project_path",
    ]
    assert gitlab_api_lite.__all__ == expected
    for name in expected:
        assert getattr(gitlab_api_lite, name) is not None


def test_project_path_is_exposed_at_package_level() -> None:
    assert gitlab_api_lite.project_path("group/sub/my.project") == "group%2Fsub%2Fmy.project"
    with pytest.raises(GitLabError) as exc_info:
        gitlab_api_lite.project_path("")
    assert exc_info.value.code == "invalid_path"


def test_error_carries_code_and_status() -> None:
    error = GitLabError("not_found", status=404)
    assert error.code == "not_found"
    assert error.status == 404
    assert "not_found" in str(error)
    assert "404" in str(error)


def test_response_header_lookup_is_case_insensitive() -> None:
    response = Response(status=200, headers={"X-Next-Page": "2"}, body=b"[]")
    assert response["x-next-page"] == "2"
    assert response.get("X-NEXT-PAGE") == "2"
    assert response.get("missing") is None
    with pytest.raises(KeyError):
        _ = response["missing"]
