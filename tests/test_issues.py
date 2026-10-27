from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pytest_httpx import HTTPXMock

from repopilot.github.client import GitHubClient
from repopilot.github.errors import (
    GitHubAPIError,
    GitHubRateLimitError,
    InvalidRepositoryError,
    RepositoryNotFoundError,
)
from repopilot.github.models import IssueInfo
from repopilot.issue_analysis import analyze_issues


def _issue(number: int, *, title: str, state: str = "open", labels: list[str] | None = None, created: str = "2026-01-01T00:00:00Z", pull_request: bool = False) -> dict:
    payload = {
        "number": number,
        "title": title,
        "body": f"Details for {title}",
        "state": state,
        "labels": [{"name": label} for label in (labels or [])],
        "html_url": f"https://github.com/octocat/Hello-World/issues/{number}",
        "url": f"https://api.github.com/repos/octocat/Hello-World/issues/{number}",
        "user": {"login": "octocat"},
        "comments": 2,
        "created_at": created,
        "updated_at": created,
        "closed_at": created if state == "closed" else None,
    }
    if pull_request:
        payload["pull_request"] = {"url": "https://api.github.com/repos/octocat/Hello-World/pulls/9"}
    return payload


def test_list_issues_paginates_and_excludes_pull_requests(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/issues?state=all&sort=created&direction=desc&page=1&per_page=100",
        json=[_issue(1, title="Fix error"), _issue(9, title="PR", pull_request=True)],
        headers={"Link": '<https://api.github.com/repos/octocat/Hello-World/issues?page=2>; rel="next"'},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/issues?state=all&sort=created&direction=desc&page=2&per_page=100",
        json=[_issue(2, title="Add docs", state="closed", labels=["documentation"])],
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_issues("octocat", "Hello-World", state="all")
    assert [issue.number for issue in listing.issues] == [1, 2]
    assert listing.excluded_pull_requests == 1
    assert listing.truncated is False


def test_list_issues_empty(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/issues?state=open&sort=created&direction=desc&page=1&per_page=100",
        json=[],
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_issues("octocat", "Hello-World")
    assert listing.issues == ()
    assert listing.excluded_pull_requests == 0


def test_list_issues_validates_inputs(httpx_mock: HTTPXMock) -> None:
    with GitHubClient(token=None) as client:
        with pytest.raises(InvalidRepositoryError):
            client.list_repository_issues("../etc", "repo")
        with pytest.raises(ValueError, match="state"):
            client.list_repository_issues("octocat", "repo", state="unknown")
        with pytest.raises(GitHubAPIError, match="max_issues"):
            client.list_repository_issues("octocat", "repo", max_issues=0)
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("status", [404, 403, 429])
def test_list_issues_api_errors(httpx_mock: HTTPXMock, status: int) -> None:
    headers = {"X-RateLimit-Remaining": "0"} if status == 429 else {}
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/issues?state=open&sort=created&direction=desc&page=1&per_page=100",
        status_code=status,
        json={"message": "API rate limit exceeded" if status == 429 else "Not Found"},
        headers=headers,
    )
    with GitHubClient(token=None) as client:
        expected = GitHubRateLimitError if status == 429 else RepositoryNotFoundError if status == 404 else GitHubAPIError
        with pytest.raises(expected):
            client.list_repository_issues("octocat", "Hello-World")


def test_issue_analysis_is_explainable() -> None:
    issue_one = IssueInfo(
        number=1,
        title="Fix authentication error",
        body="Login fails with an exception",
        state="open",
        labels=(),
        html_url="https://github.com/octocat/Hello-World/issues/1",
        api_url="https://api.github.com/repos/octocat/Hello-World/issues/1",
        author="octocat",
        comments=0,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
        closed_at=None,
    )
    issue_two = IssueInfo(
        number=2,
        title="Authentication login request",
        body="Login still fails",
        state="closed",
        labels=("bug",),
        html_url="https://github.com/octocat/Hello-World/issues/2",
        api_url="https://api.github.com/repos/octocat/Hello-World/issues/2",
        author="octocat",
        comments=1,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        closed_at="2026-01-02T00:00:00Z",
    )
    result = analyze_issues(
        [issue_one, issue_two],
        now=datetime(2026, 4, 1, tzinfo=timezone.utc),
        long_open_days=90,
    )
    assert result["open_count"] == 1
    assert result["closed_count"] == 1
    assert result["unlabeled_issue_numbers"] == [1]
    assert result["long_open_issue_numbers"] == [1]
    assert result["category_counts"]["bug"] == 2
    assert result["recurring_themes"] == [{"theme": "authentication and access", "issue_count": 2}]
    assert {item["action"] for item in result["recommendations"]} == {
        "triage_unlabeled_issues",
        "review_long_open_issues",
        "group_recurring_theme",
    }
