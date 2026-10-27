from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from mcp.shared.memory import create_connected_server_and_client_session

from repopilot.github.client import GitHubClient
from repopilot.github.errors import GitHubAPIError, GitHubRateLimitError, RepositoryNotFoundError
from repopilot.mcp_service.server import create_mcp_server
from repopilot.mcp_service import tools


def _workflow(identifier: int = 7) -> dict:
    return {
        "id": identifier,
        "name": "CI",
        "path": ".github/workflows/ci.yml",
        "state": "active",
        "url": f"https://api.github.com/repos/octocat/Hello-World/actions/workflows/{identifier}",
        "html_url": f"https://github.com/octocat/Hello-World/actions/workflows/{identifier}",
    }


def _run(identifier: int = 42, *, conclusion: str | None = "failure") -> dict:
    return {
        "id": identifier,
        "name": "CI",
        "workflow_id": 7,
        "status": "completed" if conclusion else "in_progress",
        "conclusion": conclusion,
        "head_branch": "main",
        "head_sha": "abc123",
        "event": "push",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:10:00Z",
        "run_started_at": "2026-01-01T00:01:00Z",
        "url": f"https://api.github.com/repos/octocat/Hello-World/actions/runs/{identifier}",
        "html_url": f"https://github.com/octocat/Hello-World/actions/runs/{identifier}",
        "jobs_url": f"https://api.github.com/repos/octocat/Hello-World/actions/runs/{identifier}/jobs",
        "logs_url": f"https://api.github.com/repos/octocat/Hello-World/actions/runs/{identifier}/logs",
    }


def _job(job_id: int = 101) -> dict:
    return {
        "id": job_id,
        "run_id": 42,
        "name": "test",
        "status": "completed",
        "conclusion": "failure",
        "url": f"https://api.github.com/repos/octocat/Hello-World/actions/jobs/{job_id}",
        "html_url": f"https://github.com/octocat/Hello-World/actions/runs/42/job/{job_id}",
        "steps": [
            {"number": 1, "name": "Install", "status": "completed", "conclusion": "success"},
            {"number": 2, "name": "Run tests", "status": "completed", "conclusion": "failure"},
        ],
    }


def test_workflow_discovery_and_empty_results(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/workflows?page=1&per_page=100",
        json={"total_count": 1, "workflows": [_workflow()]},
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_workflows("octocat", "Hello-World")
    assert listing.workflows[0].name == "CI"
    assert listing.workflows[0].state == "active"

    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/empty/actions/workflows?page=1&per_page=100",
        json={"total_count": 0, "workflows": []},
    )
    with GitHubClient(token=None) as client:
        empty = client.list_repository_workflows("octocat", "empty")
    assert empty.workflows == ()


def test_workflow_runs_paginate_and_validate_status(httpx_mock: HTTPXMock) -> None:
    first_url = "https://api.github.com/repos/octocat/Hello-World/actions/workflows/7/runs?status=failure&branch=main&event=push&page=1&per_page=100"
    second_url = "https://api.github.com/repos/octocat/Hello-World/actions/workflows/7/runs?status=failure&branch=main&event=push&page=2&per_page=100"
    httpx_mock.add_response(
        method="GET",
        url=first_url,
        json={"total_count": 2, "workflow_runs": [_run()]},
        headers={"Link": '<https://api.github.com/repos/octocat/Hello-World/actions/workflows/7/runs?page=2>; rel="next"'},
    )
    httpx_mock.add_response(method="GET", url=second_url, json={"total_count": 2, "workflow_runs": [_run(43, conclusion="success")]})
    with GitHubClient(token=None) as client:
        listing = client.list_workflow_runs(
            "octocat", "Hello-World", workflow_id=7, status="failure", branch="main", event="push"
        )
    assert [run.id for run in listing.runs] == [42, 43]
    assert listing.runs[0].conclusion == "failure"
    assert listing.runs[1].conclusion == "success"
    with GitHubClient(token=None) as client:
        with pytest.raises(ValueError, match="status"):
            client.list_workflow_runs("octocat", "Hello-World", status="not-a-status")


def test_jobs_and_log_extraction(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/runs/42/jobs?filter=latest&page=1&per_page=100",
        json={"total_count": 1, "jobs": [_job()]},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/jobs/101/logs",
        status_code=302,
        headers={"Location": "https://logs.example.test/job-101.txt"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://logs.example.test/job-101.txt",
        status_code=200,
        headers={"Content-Type": "text/plain"},
        content=b"Install complete\nNo module named missing_package\nTOKEN=do-not-leak\n",
    )
    with GitHubClient(token=None) as client:
        jobs = client.get_workflow_jobs("octocat", "Hello-World", 42)
        log = client.get_job_logs("octocat", "Hello-World", 101)
    assert jobs[0].steps[1].name == "Run tests"
    assert jobs[0].steps[1].conclusion == "failure"
    assert log.available is True
    assert any("No module named" in line for line in log.relevant_lines)
    assert all("do-not-leak" not in line for line in log.lines)


def test_missing_logs_and_api_errors_are_explicit(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/jobs/101/logs",
        status_code=403,
        json={"message": "Forbidden"},
    )
    with GitHubClient(token=None) as client:
        log = client.get_job_logs("octocat", "Hello-World", 101)
    assert log.available is False
    assert "403" in (log.error or "")

    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/missing/actions/workflows?page=1&per_page=100",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(RepositoryNotFoundError):
            client.list_repository_workflows("octocat", "missing")

    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/runs?status=failure&page=1&per_page=100",
        status_code=429,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(GitHubRateLimitError):
            client.list_workflow_runs("octocat", "Hello-World", status="failure")


@pytest.mark.anyio
async def test_actions_mcp_discovery_and_call(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/workflows?page=1&per_page=100",
        json={"total_count": 0, "workflows": []},
    )
    server = create_mcp_server()
    async with create_connected_server_and_client_session(server) as client:
        listed = await client.list_tools()
        result = await client.call_tool(
            "list_repository_workflows",
            {"owner": "octocat", "repo": "Hello-World"},
        )
    assert "list_repository_workflows" in {tool.name for tool in listed.tools}
    assert result.isError is False


def test_investigation_tool_diagnoses_missing_dependency(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(method="GET", url="https://api.github.com/repos/octocat/Hello-World/actions/runs/42", json=_run())
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/runs/42/jobs?filter=latest&page=1&per_page=100",
        json={"total_count": 1, "jobs": [_job()]},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/actions/jobs/101/logs",
        status_code=302,
        headers={"Location": "https://logs.example.test/job-101.txt"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://logs.example.test/job-101.txt",
        status_code=200,
        headers={"Content-Type": "text/plain"},
        content=b"Traceback\nModuleNotFoundError: No module named 'requests'\n",
    )
    result = tools.investigate_workflow_failure("octocat", "Hello-World", 42)
    assert result["ok"] is True
    diagnosis = result["data"]["diagnosis"]
    assert diagnosis["observed"]["failed_steps"][0]["name"] == "Run tests"
    assert diagnosis["inferred_likely_causes"][0]["pattern"] in {"missing_dependency", "syntax_or_import_error"}
    assert diagnosis["inferred_likely_causes"][0]["confirmed_root_cause"] is False
