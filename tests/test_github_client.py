from __future__ import annotations

import os

import httpx
import pytest
from pytest_httpx import HTTPXMock

from repopilot.github.client import GitHubClient
from repopilot.github.errors import (
    GitHubAPIError,
    GitHubRateLimitError,
    InvalidRepositoryError,
    RepositoryNotFoundError,
)


def test_get_repository_success(httpx_mock: HTTPXMock, hello_world_payload: dict) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    with GitHubClient(token=None) as client:
        repo = client.get_repository("octocat", "Hello-World")
    assert repo.full_name == "octocat/Hello-World"
    assert repo.html_url == "https://github.com/octocat/Hello-World"
    assert repo.api_url == "https://api.github.com/repos/octocat/Hello-World"
    assert repo.stars == 2800
    assert repo.is_private is False
    assert repo.default_branch == "master"


def test_missing_repository_returns_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/does-not-exist",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(RepositoryNotFoundError) as exc:
            client.get_repository("octocat", "does-not-exist")
    assert exc.value.status_code == 404


def test_rate_limit_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        status_code=403,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1710000000"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(GitHubRateLimitError) as exc:
            client.get_repository("octocat", "Hello-World")
    assert exc.value.status_code == 403
    assert exc.value.reset_at == "1710000000"


def test_timeout_is_wrapped(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with GitHubClient(token=None, timeout=1.0) as client:
        with pytest.raises(GitHubAPIError, match="timed out"):
            client.get_repository("octocat", "Hello-World")


def test_invalid_input_does_not_call_api(httpx_mock: HTTPXMock) -> None:
    with GitHubClient(token=None) as client:
        with pytest.raises(InvalidRepositoryError):
            client.get_repository("../etc", "passwd")
    assert httpx_mock.get_requests() == []


def test_malformed_payload_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json={"description": "missing required fields"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(GitHubAPIError, match="incomplete"):
            client.get_repository("octocat", "Hello-World")


@pytest.mark.integration
def test_live_public_repository_metadata() -> None:
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to hit the live GitHub API")
    with GitHubClient() as client:
        repo = client.get_repository("octocat", "Hello-World")
    assert repo.full_name == "octocat/Hello-World"
    assert repo.html_url.startswith("https://github.com/octocat/Hello-World")
    assert repo.is_private is False
