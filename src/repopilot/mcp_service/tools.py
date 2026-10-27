"""MCP tool implementations. These call the GitHub client; they do not talk HTTP themselves."""

from __future__ import annotations

import logging
from typing import Any

from repopilot.config import (
    DEFAULT_ISSUES,
    DEFAULT_LISTED_FILES,
    DEFAULT_PR_FILES,
    DEFAULT_PULL_REQUESTS,
    DEFAULT_LOG_LINES,
    DEFAULT_WORKFLOW_RUNS,
    DEFAULT_WORKFLOWS,
    LOG_CONTEXT_LINES,
    LONG_OPEN_ISSUE_DAYS,
)
from repopilot.github.client import GitHubClient
from repopilot.issue_analysis import analyze_issues
from repopilot.pr_analysis import analyze_pull_requests
from repopilot.actions_analysis import diagnose_workflow_failure
from repopilot.mcp_service.results import fail, ok

logger = logging.getLogger(__name__)

_client_override: GitHubClient | None = None


def set_github_client_override(client: GitHubClient | None) -> None:
    """Test hook. Production code leaves this unset."""
    global _client_override
    _client_override = client


def _client() -> GitHubClient:
    if _client_override is not None:
        return _client_override
    return GitHubClient()


def get_repository_info(owner: str, repo: str) -> dict[str, Any]:
    """Retrieve public GitHub repository metadata, including HTML and API evidence URLs."""
    logger.info("tool get_repository_info owner=%s repo=%s", owner, repo)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        info = client.get_repository(owner, repo)
        return ok(info.to_dict())
    except Exception as exc:
        logger.warning("get_repository_info failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def list_repository_files(
    owner: str,
    repo: str,
    ref: str | None = None,
    path_prefix: str = "",
    max_files: int = DEFAULT_LISTED_FILES,
    recursive: bool = True,
) -> dict[str, Any]:
    """List files in a repository. Recursive listings use the Git trees API and are capped."""
    logger.info("tool list_repository_files owner=%s repo=%s ref=%s", owner, repo, ref)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_files(
            owner,
            repo,
            ref=ref,
            path_prefix=path_prefix,
            max_files=max_files,
            recursive=recursive,
        )
        return ok(listing.to_dict())
    except Exception as exc:
        logger.warning("list_repository_files failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def get_file_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
) -> dict[str, Any]:
    """Retrieve one text file from a repository. Binary and oversized files omit body content."""
    logger.info("tool get_file_contents owner=%s repo=%s path=%s", owner, repo, path)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        file_content = client.get_file_contents(owner, repo, path, ref=ref)
        return ok(file_content.to_dict())
    except Exception as exc:
        logger.warning("get_file_contents failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def list_repository_issues(
    owner: str,
    repo: str,
    state: str = "open",
    max_issues: int = DEFAULT_ISSUES,
) -> dict[str, Any]:
    """List repository issues while excluding pull requests."""
    logger.info("tool list_repository_issues owner=%s repo=%s state=%s", owner, repo, state)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_issues(owner, repo, state=state, max_issues=max_issues)
        return ok(listing.to_dict())
    except Exception as exc:
        logger.warning("list_repository_issues failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def analyze_repository_issues(
    owner: str,
    repo: str,
    state: str = "all",
    max_issues: int = DEFAULT_ISSUES,
    long_open_days: int = LONG_OPEN_ISSUE_DAYS,
) -> dict[str, Any]:
    """Retrieve issues and return deterministic findings with evidence links."""
    logger.info("tool analyze_repository_issues owner=%s repo=%s state=%s", owner, repo, state)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_issues(owner, repo, state=state, max_issues=max_issues)
        data = listing.to_dict()
        data["analysis"] = analyze_issues(listing.issues, long_open_days=long_open_days)
        return ok(data)
    except Exception as exc:
        logger.warning("analyze_repository_issues failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def list_repository_pull_requests(
    owner: str,
    repo: str,
    state: str = "open",
    max_pull_requests: int = DEFAULT_PULL_REQUESTS,
    max_files_per_pull_request: int = DEFAULT_PR_FILES,
) -> dict[str, Any]:
    """List pull requests and bounded changed-file metadata."""
    logger.info("tool list_repository_pull_requests owner=%s repo=%s state=%s", owner, repo, state)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_pull_requests(
            owner,
            repo,
            state=state,
            max_pull_requests=max_pull_requests,
            max_files_per_pull_request=max_files_per_pull_request,
        )
        return ok(listing.to_dict())
    except Exception as exc:
        logger.warning("list_repository_pull_requests failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def analyze_pull_request_risks(
    owner: str,
    repo: str,
    state: str = "open",
    max_pull_requests: int = DEFAULT_PULL_REQUESTS,
    max_files_per_pull_request: int = DEFAULT_PR_FILES,
) -> dict[str, Any]:
    """Retrieve pull requests and return evidence-backed heuristic risk findings."""
    logger.info("tool analyze_pull_request_risks owner=%s repo=%s state=%s", owner, repo, state)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_pull_requests(
            owner,
            repo,
            state=state,
            max_pull_requests=max_pull_requests,
            max_files_per_pull_request=max_files_per_pull_request,
        )
        data = listing.to_dict()
        data["analysis"] = analyze_pull_requests(listing.pull_requests)
        return ok(data)
    except Exception as exc:
        logger.warning("analyze_pull_request_risks failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def list_repository_workflows(
    owner: str,
    repo: str,
    max_workflows: int = DEFAULT_WORKFLOWS,
) -> dict[str, Any]:
    """List workflow definitions without changing repository state."""
    logger.info("tool list_repository_workflows owner=%s repo=%s", owner, repo)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_repository_workflows(owner, repo, max_workflows=max_workflows)
        return ok(listing.to_dict())
    except Exception as exc:
        logger.warning("list_repository_workflows failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def list_workflow_runs(
    owner: str,
    repo: str,
    workflow_id: int | str | None = None,
    status: str | None = None,
    branch: str | None = None,
    event: str | None = None,
    max_runs: int = DEFAULT_WORKFLOW_RUNS,
) -> dict[str, Any]:
    """List workflow runs with validated GitHub Actions filters."""
    logger.info("tool list_workflow_runs owner=%s repo=%s workflow_id=%s", owner, repo, workflow_id)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        listing = client.list_workflow_runs(
            owner,
            repo,
            workflow_id=workflow_id,
            status=status,
            branch=branch,
            event=event,
            max_runs=max_runs,
        )
        return ok(listing.to_dict())
    except Exception as exc:
        logger.warning("list_workflow_runs failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()


def investigate_workflow_failure(
    owner: str,
    repo: str,
    run_id: int,
    max_jobs: int = DEFAULT_WORKFLOW_RUNS,
    max_log_lines: int = DEFAULT_LOG_LINES,
    context_lines: int = LOG_CONTEXT_LINES,
) -> dict[str, Any]:
    """Inspect one run's jobs and bounded logs, then diagnose observed patterns."""
    logger.info("tool investigate_workflow_failure owner=%s repo=%s run_id=%s", owner, repo, run_id)
    owned = False
    client = _client()
    try:
        if _client_override is None:
            owned = True
        run = client.get_workflow_run(owner, repo, run_id)
        jobs = client.get_workflow_jobs(owner, repo, run_id, max_jobs=max_jobs)
        failed_jobs = [job for job in jobs if job.conclusion in {"failure", "timed_out", "action_required"}]
        logs = [
            client.get_job_logs(owner, repo, job.id, max_lines=max_log_lines, context_lines=context_lines)
            for job in failed_jobs
        ]
        return ok(
            {
                "run": run.to_dict(),
                "jobs": [job.to_dict() for job in jobs],
                "logs": [log.to_dict() for log in logs],
                "diagnosis": diagnose_workflow_failure(run, jobs, logs),
            }
        )
    except Exception as exc:
        logger.warning("investigate_workflow_failure failed: %s", exc)
        return fail(exc)
    finally:
        if owned:
            client.close()
