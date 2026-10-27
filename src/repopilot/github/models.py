"""Structured GitHub payloads used by RepoPilot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryInfo:
    owner: str
    name: str
    full_name: str
    html_url: str
    api_url: str
    description: str | None
    default_branch: str
    primary_language: str | None
    stars: int
    forks: int
    open_issues: int
    is_private: bool
    is_fork: bool
    is_archived: bool
    license_spdx: str | None
    topics: tuple[str, ...]
    created_at: str | None
    updated_at: str | None
    pushed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "description": self.description,
            "default_branch": self.default_branch,
            "primary_language": self.primary_language,
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "is_private": self.is_private,
            "is_fork": self.is_fork,
            "is_archived": self.is_archived,
            "license_spdx": self.license_spdx,
            "topics": list(self.topics),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
        }


@dataclass(frozen=True)
class FileEntry:
    path: str
    type: str
    size: int | None
    sha: str | None
    html_url: str | None
    api_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "sha": self.sha,
            "html_url": self.html_url,
            "api_url": self.api_url,
        }


@dataclass(frozen=True)
class FileListing:
    owner: str
    repo: str
    ref: str
    path_prefix: str
    truncated: bool
    truncation_reason: str | None
    files: tuple[FileEntry, ...]
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "ref": self.ref,
            "path_prefix": self.path_prefix,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "file_count": len(self.files),
            "files": [item.to_dict() for item in self.files],
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class FileContent:
    owner: str
    repo: str
    path: str
    name: str
    html_url: str | None
    api_url: str | None
    download_url: str | None
    sha: str | None
    size: int
    encoding: str | None
    is_text: bool
    truncated: bool
    content: str | None
    untrusted_source: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "path": self.path,
            "name": self.name,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "download_url": self.download_url,
            "sha": self.sha,
            "size": self.size,
            "encoding": self.encoding,
            "is_text": self.is_text,
            "truncated": self.truncated,
            "content": self.content,
            "untrusted_source": self.untrusted_source,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class IssueInfo:
    number: int
    title: str
    body: str | None
    state: str
    labels: tuple[str, ...]
    html_url: str
    api_url: str
    author: str | None
    comments: int
    created_at: str
    updated_at: str | None
    closed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "labels": list(self.labels),
            "html_url": self.html_url,
            "api_url": self.api_url,
            "author": self.author,
            "comments": self.comments,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
        }


@dataclass(frozen=True)
class IssueListing:
    owner: str
    repo: str
    state: str
    issues: tuple[IssueInfo, ...]
    excluded_pull_requests: int
    truncated: bool
    truncation_reason: str | None
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "state": self.state,
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
            "excluded_pull_requests": self.excluded_pull_requests,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class PullRequestFile:
    filename: str
    status: str
    additions: int
    deletions: int
    changes: int
    patch: str | None
    patch_truncated: bool
    patch_unavailable: bool
    html_url: str | None
    api_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "filename": self.filename,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "changes": self.changes,
            "patch": self.patch,
            "patch_truncated": self.patch_truncated,
            "patch_unavailable": self.patch_unavailable,
            "html_url": self.html_url,
            "api_url": self.api_url,
        }


@dataclass(frozen=True)
class PullRequestInfo:
    number: int
    title: str
    body: str | None
    state: str
    author: str | None
    base_branch: str | None
    head_branch: str | None
    created_at: str
    updated_at: str | None
    html_url: str
    api_url: str
    draft: bool | None
    changed_files: int | None
    additions: int | None
    deletions: int | None
    files: tuple[PullRequestFile, ...]
    files_truncated: bool
    files_error: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "state": self.state,
            "author": self.author,
            "base_branch": self.base_branch,
            "head_branch": self.head_branch,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "draft": self.draft,
            "changed_files": self.changed_files,
            "additions": self.additions,
            "deletions": self.deletions,
            "files": [item.to_dict() for item in self.files],
            "files_truncated": self.files_truncated,
            "files_error": self.files_error,
        }


@dataclass(frozen=True)
class PullRequestListing:
    owner: str
    repo: str
    state: str
    pull_requests: tuple[PullRequestInfo, ...]
    truncated: bool
    truncation_reason: str | None
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "state": self.state,
            "pull_request_count": len(self.pull_requests),
            "pull_requests": [item.to_dict() for item in self.pull_requests],
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class WorkflowInfo:
    id: int
    name: str
    path: str
    state: str
    html_url: str | None
    api_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "state": self.state,
            "html_url": self.html_url,
            "api_url": self.api_url,
        }


@dataclass(frozen=True)
class WorkflowListing:
    owner: str
    repo: str
    workflows: tuple[WorkflowInfo, ...]
    truncated: bool
    truncation_reason: str | None
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "workflow_count": len(self.workflows),
            "workflows": [item.to_dict() for item in self.workflows],
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class WorkflowRunInfo:
    id: int
    name: str | None
    workflow_id: int | None
    status: str | None
    conclusion: str | None
    branch: str | None
    event: str | None
    head_sha: str | None
    created_at: str | None
    updated_at: str | None
    run_started_at: str | None
    html_url: str | None
    api_url: str | None
    jobs_url: str | None
    logs_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "workflow_id": self.workflow_id,
            "status": self.status,
            "conclusion": self.conclusion,
            "branch": self.branch,
            "event": self.event,
            "head_sha": self.head_sha,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_started_at": self.run_started_at,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "jobs_url": self.jobs_url,
            "logs_url": self.logs_url,
        }


@dataclass(frozen=True)
class WorkflowRunListing:
    owner: str
    repo: str
    workflow_id: int | None
    status_filter: str | None
    branch_filter: str | None
    event_filter: str | None
    runs: tuple[WorkflowRunInfo, ...]
    truncated: bool
    truncation_reason: str | None
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "workflow_id": self.workflow_id,
            "status_filter": self.status_filter,
            "branch_filter": self.branch_filter,
            "event_filter": self.event_filter,
            "run_count": len(self.runs),
            "runs": [item.to_dict() for item in self.runs],
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class WorkflowStep:
    number: int
    name: str
    status: str | None
    conclusion: str | None
    started_at: str | None
    completed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass(frozen=True)
class WorkflowJob:
    id: int
    run_id: int
    name: str
    status: str | None
    conclusion: str | None
    html_url: str | None
    api_url: str | None
    steps: tuple[WorkflowStep, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "steps": [item.to_dict() for item in self.steps],
        }


@dataclass(frozen=True)
class WorkflowLogExcerpt:
    job_id: int
    available: bool
    lines: tuple[str, ...]
    relevant_lines: tuple[str, ...]
    truncated: bool
    error: str | None
    source_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "available": self.available,
            "lines": list(self.lines),
            "relevant_lines": list(self.relevant_lines),
            "truncated": self.truncated,
            "error": self.error,
            "source_url": self.source_url,
        }
