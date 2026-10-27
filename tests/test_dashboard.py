from __future__ import annotations

import pytest

from repopilot.dashboard import fetch_issue_report, fetch_overview, validate_dashboard_repository
from repopilot.github.errors import RepositoryNotFoundError
from repopilot.github.models import IssueInfo, IssueListing, RepositoryInfo


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def get_repository(self, owner: str, repo: str) -> RepositoryInfo:
        if self.fail:
            raise RepositoryNotFoundError("Repository not found", status_code=404)
        return RepositoryInfo(
            owner=owner,
            name=repo,
            full_name=f"{owner}/{repo}",
            html_url=f"https://github.com/{owner}/{repo}",
            api_url=f"https://api.github.com/repos/{owner}/{repo}",
            description="Example repository",
            default_branch="main",
            primary_language="Python",
            stars=3,
            forks=1,
            open_issues=1,
            is_private=False,
            is_fork=False,
            is_archived=False,
            license_spdx="MIT",
            topics=(),
            created_at=None,
            updated_at=None,
            pushed_at=None,
        )

    def list_repository_issues(self, owner: str, repo: str, *, state: str) -> IssueListing:
        issue = IssueInfo(
            number=1,
            title="Fix error",
            body="Failure details",
            state="open",
            labels=(),
            html_url="https://github.com/example/repo/issues/1",
            api_url="https://api.github.com/repos/example/repo/issues/1",
            author="octocat",
            comments=0,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
            closed_at=None,
        )
        return IssueListing(owner, repo, state, (issue,), 0, False, None, f"https://github.com/{owner}/{repo}/issues")


def test_dashboard_repository_validation() -> None:
    assert validate_dashboard_repository(" octocat ", " Hello-World ") == ("octocat", "Hello-World")
    with pytest.raises(ValueError):
        validate_dashboard_repository("../etc", "passwd")
    with pytest.raises(ValueError):
        validate_dashboard_repository("octocat", "bad/repo")


def test_dashboard_fetch_functions_reuse_service_results() -> None:
    client = FakeClient()
    overview = fetch_overview(client, "octocat", "Hello-World")
    assert overview["full_name"] == "octocat/Hello-World"
    report = fetch_issue_report(client, "octocat", "Hello-World")
    assert report["analysis"]["issue_count"] == 1
    assert report["analysis"]["unlabeled_issue_numbers"] == [1]


def test_dashboard_fetch_reports_api_errors_without_masking_them() -> None:
    with pytest.raises(RepositoryNotFoundError):
        fetch_overview(FakeClient(fail=True), "octocat", "missing")
