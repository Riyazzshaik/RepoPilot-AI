from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from repopilot.github.client import GitHubClient
from repopilot.github.errors import GitHubAPIError, GitHubRateLimitError, RepositoryNotFoundError
from repopilot.github.models import PullRequestFile, PullRequestInfo
from repopilot.pr_analysis import analyze_pull_requests


def _pull(number: int, *, title: str = "Improve login", draft: bool = False) -> dict:
    return {
        "number": number,
        "title": title,
        "body": "Review this change",
        "state": "open",
        "user": {"login": "octocat"},
        "base": {"ref": "main"},
        "head": {"ref": "feature/login"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        "html_url": f"https://github.com/octocat/Hello-World/pull/{number}",
        "url": f"https://api.github.com/repos/octocat/Hello-World/pulls/{number}",
        "draft": draft,
        "changed_files": 2,
        "additions": 12,
        "deletions": 3,
    }


def _file(filename: str, *, patch: str | None = "@@ -1 +1 @@") -> dict:
    result = {
        "filename": filename,
        "status": "modified",
        "additions": 8,
        "deletions": 2,
        "changes": 10,
        "blob_url": f"https://github.com/octocat/Hello-World/blob/main/{filename}",
        "url": f"https://api.github.com/repos/octocat/Hello-World/contents/{filename}",
    }
    if patch is not None:
        result["patch"] = patch
    return result


def test_pull_requests_paginate_and_retrieve_changed_files(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls?state=all&sort=created&direction=desc&page=1&per_page=100",
        json=[_pull(1)],
        headers={"Link": '<https://api.github.com/repos/octocat/Hello-World/pulls?page=2>; rel="next"'},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls/1/files?page=1&per_page=100",
        json=[_file("src/auth.py"), _file("README.md", patch=None)],
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls?state=all&sort=created&direction=desc&page=2&per_page=100",
        json=[_pull(2, title="Update docs")],
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls/2/files?page=1&per_page=100",
        json=[],
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_pull_requests("octocat", "Hello-World", state="all")
    assert [item.number for item in listing.pull_requests] == [1, 2]
    first = listing.pull_requests[0]
    assert first.base_branch == "main"
    assert first.files[0].filename == "src/auth.py"
    assert first.files[1].patch is None
    assert first.files[1].patch_unavailable is True
    assert listing.truncated is False


def test_pull_request_file_endpoint_failure_is_explicit(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls?state=closed&sort=created&direction=desc&page=1&per_page=100",
        json=[_pull(3)],
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls/3/files?page=1&per_page=100",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_pull_requests("octocat", "Hello-World", state="closed")
    assert listing.pull_requests[0].files == ()
    assert "not found" in (listing.pull_requests[0].files_error or "").lower()


def test_pull_request_validation_and_api_errors(httpx_mock: HTTPXMock) -> None:
    with GitHubClient(token=None) as client:
        with pytest.raises(ValueError, match="state"):
            client.list_repository_pull_requests("octocat", "repo", state="invalid")
        with pytest.raises(GitHubAPIError, match="max_pull_requests"):
            client.list_repository_pull_requests("octocat", "repo", max_pull_requests=0)
    assert httpx_mock.get_requests() == []

    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/pulls?state=open&sort=created&direction=desc&page=1&per_page=100",
        status_code=429,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(GitHubRateLimitError):
            client.list_repository_pull_requests("octocat", "Hello-World")


def test_pull_request_not_found(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/missing/pulls?state=open&sort=created&direction=desc&page=1&per_page=100",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(RepositoryNotFoundError):
            client.list_repository_pull_requests("octocat", "missing")


def test_pull_request_risk_analysis_is_heuristic_and_evidence_backed() -> None:
    files = (
        PullRequestFile("src/auth.py", "modified", 20, 5, 25, "patch", False, False, "https://github.com/file", None),
        PullRequestFile("pyproject.toml", "modified", 2, 1, 3, None, False, True, "https://github.com/deps", None),
        PullRequestFile("tests/test_auth.py", "added", 10, 0, 10, "patch", False, False, "https://github.com/test", None),
    )
    pull_request = PullRequestInfo(
        number=1,
        title="Improve authentication",
        body="Review login changes",
        state="open",
        author="octocat",
        base_branch="main",
        head_branch="feature/auth",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        html_url="https://github.com/octocat/Hello-World/pull/1",
        api_url="https://api.github.com/repos/octocat/Hello-World/pulls/1",
        draft=True,
        changed_files=30,
        additions=500,
        deletions=600,
        files=files,
        files_truncated=False,
        files_error=None,
    )
    result = analyze_pull_requests([pull_request], large_files=20, large_changes=1000, broad_files=20, broad_directories=2)
    assessment = result["assessments"][0]
    rules = {finding["rule"] for finding in assessment["findings"]}
    assert {"large_change", "sensitive_path", "broad_change", "tests_modified", "draft_review_readiness"} <= rules
    assert assessment["limitations"] == ["One or more patches were missing or truncated; line-level reasoning is incomplete."]
    sensitive = next(item for item in assessment["findings"] if item["rule"] == "sensitive_path")
    assert sensitive["heuristic"] is True
    assert sensitive["confirmed_security_vulnerability"] is False
    assert sensitive["evidence"][0]["filename"] == "src/auth.py"
