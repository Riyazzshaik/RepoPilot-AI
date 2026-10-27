"""GitHub REST API client. No MCP or analysis logic lives here."""

from __future__ import annotations

import base64
import ipaddress
import logging
from dataclasses import replace
import re
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from repopilot.config import (
    DEFAULT_LISTED_FILES,
    DEFAULT_ISSUES,
    DEFAULT_PR_FILES,
    DEFAULT_PULL_REQUESTS,
    DEFAULT_LOG_LINES,
    DEFAULT_WORKFLOW_RUNS,
    DEFAULT_WORKFLOWS,
    DIRECTORY_PAGE_SIZE,
    LOG_CONTEXT_LINES,
    MAX_LOG_CHARS,
    MAX_LOG_LINES,
    MAX_WORKFLOW_RUNS,
    MAX_WORKFLOWS,
    MAX_PATCH_CHARS,
    MAX_PR_FILES,
    MAX_PULL_REQUESTS,
    MAX_ISSUES,
    MAX_DIRECTORY_PAGES,
    MAX_FILE_BYTES,
    MAX_LISTED_FILES,
    MAX_TEXT_CHARS,
    Settings,
    load_settings,
)
from repopilot.github.errors import (
    GitHubAPIError,
    GitHubRateLimitError,
    PathNotFoundError,
    RepositoryNotFoundError,
)
from repopilot.github.models import (
    FileContent,
    FileEntry,
    FileListing,
    IssueInfo,
    IssueListing,
    PullRequestFile,
    PullRequestInfo,
    PullRequestListing,
    RepositoryInfo,
    WorkflowInfo,
    WorkflowJob,
    WorkflowListing,
    WorkflowLogExcerpt,
    WorkflowRunInfo,
    WorkflowRunListing,
    WorkflowStep,
)
from repopilot.github.validation import (
    validate_git_ref,
    validate_owner,
    validate_repo_name,
    validate_repo_path,
)

logger = logging.getLogger(__name__)


class GitHubClient:
    """Thin, reusable wrapper around GitHub's public REST API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = load_settings()
        self._token = token if token is not None else settings.github_token
        self._base_url = (base_url or settings.github_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.github_request_timeout_seconds
        self._user_agent = user_agent or settings.user_agent
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self._user_agent,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_repository(self, owner: str, repo: str) -> RepositoryInfo:
        """Retrieve public metadata for a GitHub repository."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        path = f"/repos/{owner}/{repo}"
        payload = self._request_json("GET", path)
        return _parse_repository(payload)

    def list_repository_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        max_issues: int = DEFAULT_ISSUES,
    ) -> IssueListing:
        """Retrieve repository issues while excluding pull requests."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        state = state.strip().lower()
        if state not in {"open", "closed", "all"}:
            raise ValueError("state must be one of: open, closed, all")
        if max_issues < 1:
            raise GitHubAPIError("max_issues must be at least 1")
        max_issues = min(max_issues, MAX_ISSUES)
        issues, excluded, has_next = self._request_issues(
            owner,
            repo,
            state=state,
            max_issues=max_issues,
        )
        truncated = has_next and len(issues) >= max_issues
        return IssueListing(
            owner=owner,
            repo=repo,
            state=state,
            issues=tuple(issues),
            excluded_pull_requests=excluded,
            truncated=truncated,
            truncation_reason=(f"Issue listing stopped after {max_issues} issues" if truncated else None),
            evidence_url=f"https://github.com/{owner}/{repo}/issues",
        )

    def list_repository_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        max_pull_requests: int = DEFAULT_PULL_REQUESTS,
        max_files_per_pull_request: int = DEFAULT_PR_FILES,
    ) -> PullRequestListing:
        """Retrieve pull-request metadata and bounded changed-file information."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        state = state.strip().lower()
        if state not in {"open", "closed", "all"}:
            raise ValueError("state must be one of: open, closed, all")
        if max_pull_requests < 1:
            raise GitHubAPIError("max_pull_requests must be at least 1")
        if max_files_per_pull_request < 1:
            raise GitHubAPIError("max_files_per_pull_request must be at least 1")
        pull_requests = min(max_pull_requests, MAX_PULL_REQUESTS)
        files_per_pull_request = min(max_files_per_pull_request, MAX_PR_FILES)
        items, has_next = self._request_pull_requests(
            owner,
            repo,
            state=state,
            max_pull_requests=pull_requests,
            max_files_per_pull_request=files_per_pull_request,
        )
        truncated = has_next and len(items) >= pull_requests
        return PullRequestListing(
            owner=owner,
            repo=repo,
            state=state,
            pull_requests=tuple(items),
            truncated=truncated,
            truncation_reason=(
                f"Pull-request listing stopped after {pull_requests} pull requests" if truncated else None
            ),
            evidence_url=f"https://github.com/{owner}/{repo}/pulls",
        )

    def list_repository_workflows(
        self,
        owner: str,
        repo: str,
        *,
        max_workflows: int = DEFAULT_WORKFLOWS,
    ) -> WorkflowListing:
        """List workflow definitions using the read-only Actions endpoint."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        if max_workflows < 1:
            raise GitHubAPIError("max_workflows must be at least 1")
        limit = min(max_workflows, MAX_WORKFLOWS)
        workflows: list[WorkflowInfo] = []
        page = 1
        has_next = False
        while page <= MAX_DIRECTORY_PAGES and len(workflows) < limit:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/actions/workflows",
                params={"page": page, "per_page": DIRECTORY_PAGE_SIZE},
            )
            payload = _parse_json(response)
            if not isinstance(payload, dict):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for workflows")
            raw_workflows = payload.get("workflows", [])
            if not isinstance(raw_workflows, list):
                raise GitHubAPIError("GitHub API returned invalid workflow data")
            for item in raw_workflows:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid workflow object")
                workflows.append(_parse_workflow(item))
                if len(workflows) >= limit:
                    break
            link = response.headers.get("Link", "")
            has_next = 'rel="next"' in link
            if not raw_workflows or not has_next:
                break
            page += 1
        return WorkflowListing(
            owner=owner,
            repo=repo,
            workflows=tuple(workflows),
            truncated=has_next and len(workflows) >= limit,
            truncation_reason=(f"Workflow listing stopped after {limit} workflows" if has_next and len(workflows) >= limit else None),
            evidence_url=f"https://github.com/{owner}/{repo}/actions/workflows",
        )

    def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        *,
        workflow_id: int | str | None = None,
        status: str | None = None,
        branch: str | None = None,
        event: str | None = None,
        max_runs: int = DEFAULT_WORKFLOW_RUNS,
    ) -> WorkflowRunListing:
        """List workflow runs with the documented Actions filters."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        if max_runs < 1:
            raise GitHubAPIError("max_runs must be at least 1")
        workflow_value = _validate_workflow_identifier(workflow_id) if workflow_id is not None else None
        status = _validate_run_status(status)
        branch = validate_git_ref(branch)
        event = _validate_action_event(event)
        limit = min(max_runs, MAX_WORKFLOW_RUNS)
        path = f"/repos/{owner}/{repo}/actions/runs"
        if workflow_value is not None:
            path = f"/repos/{owner}/{repo}/actions/workflows/{quote(workflow_value, safe='')}/runs"
        params: dict[str, str | int] = {}
        if status:
            params["status"] = status
        if branch:
            params["branch"] = branch
        if event:
            params["event"] = event
        runs: list[WorkflowRunInfo] = []
        page = 1
        has_next = False
        while page <= MAX_DIRECTORY_PAGES and len(runs) < limit:
            page_params = {**params, "page": page, "per_page": DIRECTORY_PAGE_SIZE}
            response = self._request("GET", path, params=page_params)
            payload = _parse_json(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for workflow runs")
            raw_runs = payload["workflow_runs"]
            for item in raw_runs:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid workflow run object")
                runs.append(_parse_workflow_run(item))
                if len(runs) >= limit:
                    break
            link = response.headers.get("Link", "")
            has_next = 'rel="next"' in link
            if not raw_runs or not has_next:
                break
            page += 1
        return WorkflowRunListing(
            owner=owner,
            repo=repo,
            workflow_id=int(workflow_value) if workflow_value and workflow_value.isdigit() else None,
            status_filter=status,
            branch_filter=branch,
            event_filter=event,
            runs=tuple(runs),
            truncated=has_next and len(runs) >= limit,
            truncation_reason=(f"Workflow run listing stopped after {limit} runs" if has_next and len(runs) >= limit else None),
            evidence_url=f"https://github.com/{owner}/{repo}/actions/runs",
        )

    def get_workflow_run(self, owner: str, repo: str, run_id: int) -> WorkflowRunInfo:
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        run_id = _validate_positive_id(run_id, "run_id")
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}")
        return _parse_workflow_run(payload)

    def get_workflow_jobs(
        self,
        owner: str,
        repo: str,
        run_id: int,
        *,
        max_jobs: int = DEFAULT_WORKFLOW_RUNS,
        job_filter: str = "latest",
    ) -> tuple[WorkflowJob, ...]:
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        run_id = _validate_positive_id(run_id, "run_id")
        if job_filter not in {"latest", "all"}:
            raise ValueError("job_filter must be one of: latest, all")
        if max_jobs < 1:
            raise GitHubAPIError("max_jobs must be at least 1")
        jobs: list[WorkflowJob] = []
        page = 1
        limit = min(max_jobs, MAX_WORKFLOW_RUNS)
        while page <= MAX_DIRECTORY_PAGES and len(jobs) < limit:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                params={"filter": job_filter, "page": page, "per_page": DIRECTORY_PAGE_SIZE},
            )
            payload = _parse_json(response)
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for workflow jobs")
            raw_jobs = payload["jobs"]
            for item in raw_jobs:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid workflow job object")
                jobs.append(_parse_workflow_job(item))
                if len(jobs) >= limit:
                    break
            link = response.headers.get("Link", "")
            if not raw_jobs or 'rel="next"' not in link:
                break
            page += 1
        return tuple(jobs)

    def get_job_logs(
        self,
        owner: str,
        repo: str,
        job_id: int,
        *,
        max_lines: int = DEFAULT_LOG_LINES,
        context_lines: int = LOG_CONTEXT_LINES,
    ) -> WorkflowLogExcerpt:
        """Fetch one job's supported log redirect without forwarding the API token."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        job_id = _validate_positive_id(job_id, "job_id")
        if max_lines < 1 or max_lines > MAX_LOG_LINES:
            raise ValueError(f"max_lines must be between 1 and {MAX_LOG_LINES}")
        if context_lines < 0 or context_lines > 20:
            raise ValueError("context_lines must be between 0 and 20")
        try:
            response = self._request("GET", f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs")
            if response.status_code != 302:
                return WorkflowLogExcerpt(job_id, False, (), (), False, "GitHub did not return a log redirect", None)
            location = response.headers.get("Location")
            safe_location = _safe_log_location(location)
            if safe_location is None:
                return WorkflowLogExcerpt(job_id, False, (), (), False, "GitHub returned an unsafe or missing log redirect", None)
            try:
                with httpx.Client(timeout=self._timeout, follow_redirects=False, headers={"User-Agent": self._user_agent}) as download_client:
                    download = download_client.get(safe_location)
            except httpx.HTTPError as exc:
                return WorkflowLogExcerpt(job_id, False, (), (), False, f"Log download failed: {exc}", safe_location)
            if download.status_code != 200:
                return WorkflowLogExcerpt(job_id, False, (), (), False, f"Log download returned HTTP {download.status_code}", safe_location)
            raw = download.content
            if raw.startswith(b"PK") or "zip" in download.headers.get("Content-Type", "").lower():
                return WorkflowLogExcerpt(job_id, False, (), (), False, "Binary or archived logs are not expanded by this investigator", safe_location)
            text = raw[:MAX_LOG_CHARS].decode("utf-8", errors="replace")
            truncated = len(raw) > MAX_LOG_CHARS
            lines = [_redact_log_line(line) for line in text.splitlines()]
            selected, relevant = _select_log_lines(lines, max_lines=max_lines, context_lines=context_lines)
            return WorkflowLogExcerpt(job_id, True, tuple(selected), tuple(relevant), truncated, None, safe_location)
        except GitHubAPIError as exc:
            return WorkflowLogExcerpt(job_id, False, (), (), False, str(exc), None)

    def get_readme(self, owner: str, repo: str, *, ref: str | None = None) -> FileContent:
        """Retrieve the repository README using GitHub's README endpoint."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        ref = validate_git_ref(ref)
        params = {"ref": ref} if ref else None
        payload = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/readme",
            params=params,
            not_found_error=PathNotFoundError,
            not_found_message="README not found in this repository",
        )
        return _parse_file_content(payload, owner=owner, repo=repo)

    def list_repository_files(
        self,
        owner: str,
        repo: str,
        *,
        ref: str | None = None,
        path_prefix: str = "",
        max_files: int = DEFAULT_LISTED_FILES,
        recursive: bool = True,
    ) -> FileListing:
        """List repository files. Recursive listing uses the Git trees API."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        prefix = validate_repo_path(path_prefix, allow_empty=True)
        ref = validate_git_ref(ref)
        if max_files < 1:
            raise GitHubAPIError("max_files must be at least 1")
        max_files = min(max_files, MAX_LISTED_FILES)
        if ref is None:
            ref = self.get_repository(owner, repo).default_branch
        if recursive:
            return self._list_files_via_tree(owner, repo, ref=ref, prefix=prefix, max_files=max_files)
        return self._list_files_via_contents(owner, repo, ref=ref, prefix=prefix, max_files=max_files)

    def get_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> FileContent:
        """Retrieve a single file. Directories are rejected. Content is not executed."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        path = validate_repo_path(path, allow_empty=False)
        ref = validate_git_ref(ref)
        encoded_path = quote(path, safe="/")
        params = {"ref": ref} if ref else None
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{encoded_path}",
            params=params,
            not_found_error=PathNotFoundError,
            not_found_message=f"Path not found: {path}",
        )
        payload = _parse_json(response)
        if isinstance(payload, list):
            raise GitHubAPIError(f"Path is a directory, not a file: {path}", status_code=response.status_code)
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub API returned an unexpected JSON shape")
        if payload.get("type") == "dir":
            raise GitHubAPIError(f"Path is a directory, not a file: {path}")
        return _parse_file_content(payload, owner=owner, repo=repo)

    def _list_files_via_tree(
        self,
        owner: str,
        repo: str,
        *,
        ref: str,
        prefix: str,
        max_files: int,
    ) -> FileListing:
        encoded_ref = quote(ref, safe="")
        payload = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{encoded_ref}",
            params={"recursive": "1"},
            not_found_error=PathNotFoundError,
            not_found_message=f"Git tree not found for ref {ref}",
        )
        tree = payload.get("tree") if isinstance(payload.get("tree"), list) else []
        entries: list[FileEntry] = []
        api_truncated = bool(payload.get("truncated"))
        for node in tree:
            if not isinstance(node, dict) or node.get("type") != "blob":
                continue
            node_path = str(node.get("path") or "")
            if prefix and node_path != prefix and not node_path.startswith(prefix.rstrip("/") + "/"):
                continue
            entries.append(
                FileEntry(
                    path=node_path,
                    type="file",
                    size=int(node["size"]) if node.get("size") is not None else None,
                    sha=str(node["sha"]) if node.get("sha") else None,
                    html_url=f"https://github.com/{owner}/{repo}/blob/{ref}/{node_path}",
                    api_url=str(node["url"]) if node.get("url") else None,
                )
            )
            if len(entries) >= max_files:
                break
        truncated = api_truncated or len(entries) >= max_files
        reason = None
        if api_truncated:
            reason = "GitHub truncated the git tree; additional files exist but were not returned"
        elif len(entries) >= max_files:
            reason = f"Listing stopped after {max_files} files"
        evidence = str(payload.get("url") or f"{self._base_url}/repos/{owner}/{repo}/git/trees/{encoded_ref}")
        return FileListing(
            owner=owner,
            repo=repo,
            ref=ref,
            path_prefix=prefix,
            truncated=truncated,
            truncation_reason=reason,
            files=tuple(entries),
            evidence_url=evidence,
        )

    def _request_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str,
        max_issues: int,
    ) -> tuple[list[IssueInfo], int, bool]:
        issues: list[IssueInfo] = []
        excluded_pull_requests = 0
        page = 1
        has_next = False
        while page <= MAX_DIRECTORY_PAGES and len(issues) < max_issues:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues",
                params={
                    "state": state,
                    "sort": "created",
                    "direction": "desc",
                    "page": page,
                    "per_page": DIRECTORY_PAGE_SIZE,
                },
                not_found_message="Repository not found or is not visible with the current credentials",
            )
            payload = _parse_json(response)
            if not isinstance(payload, list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for issues")
            for item in payload:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid issue object")
                if item.get("pull_request") is not None:
                    excluded_pull_requests += 1
                    continue
                issues.append(_parse_issue(item))
                if len(issues) >= max_issues:
                    break
            link = response.headers.get("Link", "")
            has_next = 'rel="next"' in link
            if not payload or not has_next:
                break
            page += 1
        return issues, excluded_pull_requests, has_next

    def _request_pull_requests(
        self,
        owner: str,
        repo: str,
        *,
        state: str,
        max_pull_requests: int,
        max_files_per_pull_request: int,
    ) -> tuple[list[PullRequestInfo], bool]:
        pull_requests: list[PullRequestInfo] = []
        page = 1
        has_next = False
        while page <= MAX_DIRECTORY_PAGES and len(pull_requests) < max_pull_requests:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls",
                params={
                    "state": state,
                    "sort": "created",
                    "direction": "desc",
                    "page": page,
                    "per_page": DIRECTORY_PAGE_SIZE,
                },
            )
            payload = _parse_json(response)
            if not isinstance(payload, list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for pull requests")
            for item in payload:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid pull-request object")
                pull_request = _parse_pull_request(item)
                pull_request = self._attach_pull_request_files(
                    owner,
                    repo,
                    pull_request,
                    max_files=max_files_per_pull_request,
                )
                pull_requests.append(pull_request)
                if len(pull_requests) >= max_pull_requests:
                    break
            link = response.headers.get("Link", "")
            has_next = 'rel="next"' in link
            if not payload or not has_next:
                break
            page += 1
        return pull_requests, has_next

    def _attach_pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_request: PullRequestInfo,
        *,
        max_files: int,
    ) -> PullRequestInfo:
        try:
            files, files_truncated = self._request_pull_request_files(
                owner,
                repo,
                pull_request.number,
                max_files=max_files,
            )
        except GitHubAPIError as exc:
            return replace(pull_request, files_error=str(exc))
        return replace(pull_request, files=tuple(files), files_truncated=files_truncated)

    def _request_pull_request_files(
        self,
        owner: str,
        repo: str,
        number: int,
        *,
        max_files: int,
    ) -> tuple[list[PullRequestFile], bool]:
        files: list[PullRequestFile] = []
        page = 1
        has_next = False
        while page <= MAX_DIRECTORY_PAGES and len(files) < max_files:
            response = self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"page": page, "per_page": DIRECTORY_PAGE_SIZE},
            )
            payload = _parse_json(response)
            if not isinstance(payload, list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for pull-request files")
            for item in payload:
                if not isinstance(item, dict):
                    raise GitHubAPIError("GitHub API returned an invalid pull-request file object")
                files.append(_parse_pull_request_file(item))
                if len(files) >= max_files:
                    break
            link = response.headers.get("Link", "")
            has_next = 'rel="next"' in link
            if not payload or not has_next:
                break
            page += 1
        return files, has_next and len(files) >= max_files

    def _list_files_via_contents(
        self,
        owner: str,
        repo: str,
        *,
        ref: str,
        prefix: str,
        max_files: int,
    ) -> FileListing:
        encoded_prefix = quote(prefix, safe="/") if prefix else ""
        path = f"/repos/{owner}/{repo}/contents"
        if encoded_prefix:
            path = f"{path}/{encoded_prefix}"
        items = self._request_paginated_list(
            "GET",
            path,
            params={"ref": ref},
            not_found_error=PathNotFoundError,
            not_found_message=f"Path not found: {prefix or '/'}",
        )
        entries: list[FileEntry] = []
        for node in items:
            if not isinstance(node, dict):
                continue
            node_path = str(node.get("path") or node.get("name") or "")
            node_type = "dir" if node.get("type") == "dir" else "file"
            entries.append(
                FileEntry(
                    path=node_path,
                    type=node_type,
                    size=int(node["size"]) if node.get("size") is not None else None,
                    sha=str(node["sha"]) if node.get("sha") else None,
                    html_url=str(node["html_url"]) if node.get("html_url") else None,
                    api_url=str(node["url"]) if node.get("url") else None,
                )
            )
            if len(entries) >= max_files:
                break
        truncated = len(entries) >= max_files or len(items) > len(entries)
        return FileListing(
            owner=owner,
            repo=repo,
            ref=ref,
            path_prefix=prefix,
            truncated=truncated,
            truncation_reason=f"Listing stopped after {max_files} files" if truncated else None,
            files=tuple(entries),
            evidence_url=f"https://github.com/{owner}/{repo}/tree/{ref}/{prefix}".rstrip("/"),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Repository not found or is not visible with the current credentials",
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            not_found_error=not_found_error,
            not_found_message=not_found_message,
        )
        data = _parse_json(response)
        if not isinstance(data, dict):
            raise GitHubAPIError("GitHub API returned an unexpected JSON shape")
        return data

    def _request_paginated_list(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Not found",
        max_pages: int = MAX_DIRECTORY_PAGES,
        per_page: int = DIRECTORY_PAGE_SIZE,
    ) -> list[Any]:
        collected: list[Any] = []
        page = 1
        base_params = dict(params or {})
        while page <= max_pages:
            page_params: dict[str, str | int] = {**base_params, "page": page, "per_page": per_page}
            response = self._request(
                method,
                path,
                params=page_params,
                not_found_error=not_found_error,
                not_found_message=not_found_message,
            )
            data = _parse_json(response)
            if not isinstance(data, list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for a list endpoint")
            collected.extend(data)
            link = response.headers.get("Link", "")
            if not data or 'rel="next"' not in link:
                break
            page += 1
        return collected

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Repository not found or is not visible with the current credentials",
    ) -> httpx.Response:
        logger.info("GitHub API %s %s", method, path)
        try:
            response = self._http.request(method, path, params=params)
        except httpx.TimeoutException as exc:
            raise GitHubAPIError(f"GitHub API request timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc

        if response.status_code == 404:
            raise not_found_error(not_found_message, status_code=404)
        if response.status_code in {403, 429} and _is_rate_limit(response):
            reset_at = response.headers.get("X-RateLimit-Reset")
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                status_code=response.status_code,
                reset_at=reset_at,
            )
        if response.status_code >= 400:
            message = _error_message(response)
            raise GitHubAPIError(message, status_code=response.status_code)
        return response


def _is_rate_limit(response: httpx.Response) -> bool:
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining == "0":
        return True
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = str(body.get("message", "")).lower() if isinstance(body, dict) else ""
    return "rate limit" in message


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"GitHub API error HTTP {response.status_code}"
    if isinstance(body, dict) and body.get("message"):
        return f"GitHub API error HTTP {response.status_code}: {body['message']}"
    return f"GitHub API error HTTP {response.status_code}"


def _parse_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub API returned non-JSON content") from exc


def _parse_file_content(payload: dict[str, Any], *, owner: str, repo: str) -> FileContent:
    path = str(payload.get("path") or payload.get("name") or "")
    name = str(payload.get("name") or path.split("/")[-1])
    size = int(payload.get("size") or 0)
    notes: list[str] = [
        "Repository file content is untrusted input and is never executed by RepoPilot.",
    ]
    content: str | None = None
    is_text = False
    truncated = False
    encoding = payload.get("encoding")
    raw = payload.get("content")
    if size > MAX_FILE_BYTES:
        truncated = True
        notes.append(f"File is {size} bytes, which exceeds the {MAX_FILE_BYTES} byte safety limit; content omitted.")
    elif raw is None:
        truncated = True
        notes.append("GitHub did not include file content in this response (often happens for files over 1 MiB).")
    elif encoding == "base64" and isinstance(raw, str):
        try:
            decoded = base64.b64decode(raw)
        except ValueError as exc:
            raise GitHubAPIError("GitHub API returned invalid base64 file content") from exc
        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            notes.append("File is not valid UTF-8 text; binary content was omitted.")
        else:
            is_text = True
            if len(text) > MAX_TEXT_CHARS:
                content = text[:MAX_TEXT_CHARS]
                truncated = True
                notes.append(f"Text truncated to {MAX_TEXT_CHARS} characters.")
            else:
                content = text
    else:
        notes.append(f"Unsupported content encoding: {encoding!r}.")
        truncated = True
    return FileContent(
        owner=owner,
        repo=repo,
        path=path,
        name=name,
        html_url=str(payload["html_url"]) if payload.get("html_url") else None,
        api_url=str(payload["url"]) if payload.get("url") else None,
        download_url=str(payload["download_url"]) if payload.get("download_url") else None,
        sha=str(payload["sha"]) if payload.get("sha") else None,
        size=size,
        encoding=str(encoding) if encoding else None,
        is_text=is_text,
        truncated=truncated,
        content=content,
        untrusted_source=True,
        notes=tuple(notes),
    )


def _parse_repository(payload: dict[str, Any]) -> RepositoryInfo:
    owner_block = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    license_block = payload.get("license") if isinstance(payload.get("license"), dict) else {}
    topics = payload.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    owner_login = str(owner_block.get("login") or payload.get("full_name", "").split("/")[0])
    name = str(payload.get("name") or "")
    full_name = str(payload.get("full_name") or f"{owner_login}/{name}")
    if not name or not owner_login:
        raise GitHubAPIError("GitHub API returned incomplete repository metadata")
    return RepositoryInfo(
        owner=owner_login,
        name=name,
        full_name=full_name,
        html_url=str(payload.get("html_url") or f"https://github.com/{full_name}"),
        api_url=str(payload.get("url") or f"https://api.github.com/repos/{full_name}"),
        description=payload.get("description"),
        default_branch=str(payload.get("default_branch") or "main"),
        primary_language=payload.get("language"),
        stars=int(payload.get("stargazers_count") or 0),
        forks=int(payload.get("forks_count") or 0),
        open_issues=int(payload.get("open_issues_count") or 0),
        is_private=bool(payload.get("private")),
        is_fork=bool(payload.get("fork")),
        is_archived=bool(payload.get("archived")),
        license_spdx=(license_block.get("spdx_id") if license_block else None),
        topics=tuple(str(item) for item in topics),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
        pushed_at=payload.get("pushed_at"),
    )


def _parse_issue(payload: dict[str, Any]) -> IssueInfo:
    """Parse only the bounded issue fields used by RepoPilot."""
    number = payload.get("number")
    title = payload.get("title")
    state = payload.get("state")
    created_at = payload.get("created_at")
    if not isinstance(number, int) or not isinstance(title, str) or not isinstance(state, str):
        raise GitHubAPIError("GitHub API returned incomplete issue metadata")
    if not isinstance(created_at, str) or not created_at:
        raise GitHubAPIError("GitHub API returned an issue without created_at")
    raw_labels = payload.get("labels", [])
    if not isinstance(raw_labels, list):
        raise GitHubAPIError("GitHub API returned invalid issue labels")
    labels: list[str] = []
    for label in raw_labels:
        if not isinstance(label, dict) or not isinstance(label.get("name"), str):
            raise GitHubAPIError("GitHub API returned an invalid issue label")
        labels.append(label["name"])
    user = payload.get("user")
    author = user.get("login") if isinstance(user, dict) and isinstance(user.get("login"), str) else None
    html_url = payload.get("html_url")
    api_url = payload.get("url")
    if not isinstance(html_url, str) or not isinstance(api_url, str):
        raise GitHubAPIError("GitHub API returned incomplete issue URLs")
    body = payload.get("body")
    if body is not None and not isinstance(body, str):
        raise GitHubAPIError("GitHub API returned an invalid issue body")
    return IssueInfo(
        number=number,
        title=title,
        body=body,
        state=state,
        labels=tuple(labels),
        html_url=html_url,
        api_url=api_url,
        author=author,
        comments=int(payload.get("comments") or 0),
        created_at=created_at,
        updated_at=payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
        closed_at=payload.get("closed_at") if isinstance(payload.get("closed_at"), str) else None,
    )


def _parse_pull_request(payload: dict[str, Any]) -> PullRequestInfo:
    number = payload.get("number")
    title = payload.get("title")
    state = payload.get("state")
    created_at = payload.get("created_at")
    html_url = payload.get("html_url")
    api_url = payload.get("url")
    if (
        not isinstance(number, int)
        or not isinstance(title, str)
        or not isinstance(state, str)
        or not isinstance(created_at, str)
        or not isinstance(html_url, str)
        or not isinstance(api_url, str)
    ):
        raise GitHubAPIError("GitHub API returned incomplete pull-request metadata")
    user = payload.get("user")
    base = payload.get("base")
    head = payload.get("head")
    author = user.get("login") if isinstance(user, dict) and isinstance(user.get("login"), str) else None
    base_branch = base.get("ref") if isinstance(base, dict) and isinstance(base.get("ref"), str) else None
    head_branch = head.get("ref") if isinstance(head, dict) and isinstance(head.get("ref"), str) else None
    body = payload.get("body")
    if body is not None and not isinstance(body, str):
        raise GitHubAPIError("GitHub API returned an invalid pull-request body")
    return PullRequestInfo(
        number=number,
        title=title,
        body=body,
        state=state,
        author=author,
        base_branch=base_branch,
        head_branch=head_branch,
        created_at=created_at,
        updated_at=payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
        html_url=html_url,
        api_url=api_url,
        draft=payload.get("draft") if isinstance(payload.get("draft"), bool) else None,
        changed_files=_optional_int(payload.get("changed_files"), "changed_files"),
        additions=_optional_int(payload.get("additions"), "additions"),
        deletions=_optional_int(payload.get("deletions"), "deletions"),
        files=(),
        files_truncated=False,
        files_error=None,
    )


def _parse_pull_request_file(payload: dict[str, Any]) -> PullRequestFile:
    filename = payload.get("filename")
    status = payload.get("status")
    if not isinstance(filename, str) or not isinstance(status, str):
        raise GitHubAPIError("GitHub API returned incomplete pull-request file metadata")
    raw_patch = payload.get("patch")
    if raw_patch is not None and not isinstance(raw_patch, str):
        raise GitHubAPIError("GitHub API returned an invalid pull-request patch")
    patch_truncated = isinstance(raw_patch, str) and len(raw_patch) > MAX_PATCH_CHARS
    patch = raw_patch[:MAX_PATCH_CHARS] if patch_truncated else raw_patch
    return PullRequestFile(
        filename=filename,
        status=status,
        additions=_required_int(payload.get("additions"), "additions"),
        deletions=_required_int(payload.get("deletions"), "deletions"),
        changes=_required_int(payload.get("changes"), "changes"),
        patch=patch,
        patch_truncated=patch_truncated,
        patch_unavailable=raw_patch is None,
        html_url=payload.get("blob_url") if isinstance(payload.get("blob_url"), str) else None,
        api_url=payload.get("url") if isinstance(payload.get("url"), str) else None,
    )


def _optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _required_int(value, name)


def _required_int(value: Any, name: str) -> int:
    if not isinstance(value, int):
        raise GitHubAPIError(f"GitHub API returned invalid pull-request {name}")
    return value


def _validate_positive_id(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_workflow_identifier(value: int | str) -> str:
    if isinstance(value, bool):
        raise ValueError("workflow_id must be a positive integer or workflow file name")
    if isinstance(value, int):
        return str(_validate_positive_id(value, "workflow_id"))
    text = value.strip()
    if not text or ".." in text or "\\" in text or not re.fullmatch(r"[A-Za-z0-9_./@+-]+", text):
        raise ValueError("workflow_id must be a positive integer or workflow file name")
    return text


_RUN_STATUSES = {
    "completed",
    "action_required",
    "cancelled",
    "failure",
    "neutral",
    "skipped",
    "stale",
    "success",
    "timed_out",
    "in_progress",
    "queued",
    "requested",
    "waiting",
    "pending",
}


def _validate_run_status(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip().lower()
    if text not in _RUN_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(_RUN_STATUSES))}")
    return text


def _validate_action_event(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    text = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", text):
        raise ValueError("event contains invalid characters")
    return text


def _safe_log_location(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
        return None
    return value


def _parse_workflow(payload: dict[str, Any]) -> WorkflowInfo:
    identifier = payload.get("id")
    name = payload.get("name")
    path = payload.get("path")
    state = payload.get("state")
    if not isinstance(identifier, int) or not isinstance(name, str) or not isinstance(path, str) or not isinstance(state, str):
        raise GitHubAPIError("GitHub API returned incomplete workflow metadata")
    return WorkflowInfo(
        id=identifier,
        name=name,
        path=path,
        state=state,
        html_url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
        api_url=payload.get("url") if isinstance(payload.get("url"), str) else None,
    )


def _parse_workflow_run(payload: dict[str, Any]) -> WorkflowRunInfo:
    identifier = payload.get("id")
    if not isinstance(identifier, int):
        raise GitHubAPIError("GitHub API returned incomplete workflow run metadata")
    return WorkflowRunInfo(
        id=identifier,
        name=payload.get("name") if isinstance(payload.get("name"), str) else None,
        workflow_id=payload.get("workflow_id") if isinstance(payload.get("workflow_id"), int) else None,
        status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        conclusion=payload.get("conclusion") if isinstance(payload.get("conclusion"), str) else None,
        branch=payload.get("head_branch") if isinstance(payload.get("head_branch"), str) else None,
        event=payload.get("event") if isinstance(payload.get("event"), str) else None,
        head_sha=payload.get("head_sha") if isinstance(payload.get("head_sha"), str) else None,
        created_at=payload.get("created_at") if isinstance(payload.get("created_at"), str) else None,
        updated_at=payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
        run_started_at=payload.get("run_started_at") if isinstance(payload.get("run_started_at"), str) else None,
        html_url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
        api_url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        jobs_url=payload.get("jobs_url") if isinstance(payload.get("jobs_url"), str) else None,
        logs_url=payload.get("logs_url") if isinstance(payload.get("logs_url"), str) else None,
    )


def _parse_workflow_job(payload: dict[str, Any]) -> WorkflowJob:
    identifier = payload.get("id")
    run_id = payload.get("run_id")
    name = payload.get("name")
    if not isinstance(identifier, int) or not isinstance(run_id, int) or not isinstance(name, str):
        raise GitHubAPIError("GitHub API returned incomplete workflow job metadata")
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list):
        raise GitHubAPIError("GitHub API returned invalid workflow job steps")
    steps: list[WorkflowStep] = []
    for item in raw_steps:
        if not isinstance(item, dict) or not isinstance(item.get("number"), int) or not isinstance(item.get("name"), str):
            raise GitHubAPIError("GitHub API returned an invalid workflow step")
        steps.append(
            WorkflowStep(
                number=item["number"],
                name=item["name"],
                status=item.get("status") if isinstance(item.get("status"), str) else None,
                conclusion=item.get("conclusion") if isinstance(item.get("conclusion"), str) else None,
                started_at=item.get("started_at") if isinstance(item.get("started_at"), str) else None,
                completed_at=item.get("completed_at") if isinstance(item.get("completed_at"), str) else None,
            )
        )
    return WorkflowJob(
        id=identifier,
        run_id=run_id,
        name=name,
        status=payload.get("status") if isinstance(payload.get("status"), str) else None,
        conclusion=payload.get("conclusion") if isinstance(payload.get("conclusion"), str) else None,
        html_url=payload.get("html_url") if isinstance(payload.get("html_url"), str) else None,
        api_url=payload.get("url") if isinstance(payload.get("url"), str) else None,
        steps=tuple(steps),
    )


_LOG_ERROR_RE = re.compile(
    r"(error|failed|failure|exception|traceback|no module named|modulenotfound|cannot find|command not found|npm err|requires python|incompatible)",
    re.IGNORECASE,
)
_SECRET_RE = re.compile(r"(?i)(token|password|passwd|secret|authorization|api[_-]?key)(\s*[:=]\s*)\S+")


def _redact_log_line(line: str) -> str:
    return _SECRET_RE.sub(r"\1\2<redacted>", line)


def _select_log_lines(lines: list[str], *, max_lines: int, context_lines: int) -> tuple[list[str], list[str]]:
    relevant_indexes = [index for index, line in enumerate(lines) if _LOG_ERROR_RE.search(line)]
    if not relevant_indexes:
        return lines[:max_lines], []
    selected_indexes: set[int] = set()
    for index in relevant_indexes:
        selected_indexes.update(range(max(0, index - context_lines), min(len(lines), index + context_lines + 1)))
    ordered_indexes = sorted(selected_indexes)[:max_lines]
    selected = [lines[index] for index in ordered_indexes]
    relevant = [lines[index] for index in relevant_indexes if index in selected_indexes][:max_lines]
    return selected, relevant


def client_from_settings(settings: Settings | None = None) -> GitHubClient:
    cfg = settings or load_settings()
    return GitHubClient(
        token=cfg.github_token,
        base_url=cfg.github_api_base_url,
        timeout=cfg.github_request_timeout_seconds,
        user_agent=cfg.user_agent,
    )
