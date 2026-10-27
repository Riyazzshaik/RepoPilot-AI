from __future__ import annotations

from pathlib import Path

import pytest

from repopilot.dashboard import _get_cached, fetch_issue_report, fetch_overview, validate_dashboard_repository
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

    def list_repository_issues(self, owner: str, repo: str, *, state: str, max_issues: int = 100) -> IssueListing:
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


class FakeSpinner:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


class FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = type("SessionState", (), {"dashboard_cache": {}})()

    def spinner(self, _message: str) -> FakeSpinner:
        return FakeSpinner()


class CountingLoader:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return "loaded"


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
    assert report["records_analyzed"] == 1
    assert report["configured_maximum"] == 100
    assert report["repository_open_issues"] == 1
    assert report["refreshed_at"]


def test_dashboard_fetch_reports_api_errors_without_masking_them() -> None:
    with pytest.raises(RepositoryNotFoundError):
        fetch_overview(FakeClient(fail=True), "octocat", "missing")


def test_dashboard_session_cache_avoids_repeated_loads() -> None:
    fake_st = FakeStreamlit()
    loader = CountingLoader()
    assert _get_cached(fake_st, "overview:example/repo", loader) == "loaded"
    assert _get_cached(fake_st, "overview:example/repo", loader) == "loaded"
    assert loader.calls == 1


def test_streamlit_rendering_handles_invalid_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("GITHUB_API_BASE_URL", "http://127.0.0.1:1")
    app = AppTest.from_file(Path(__file__).parents[1] / "src" / "repopilot" / "dashboard.py")
    app.run(timeout=10)
    app.sidebar.text_input[0].set_value("../invalid")
    app.sidebar.text_input[1].set_value("repo")
    app.run(timeout=10)
    assert any("Invalid repository owner" in item.value for item in app.error)
