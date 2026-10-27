"""Explainable, deterministic pull-request risk analysis."""

from __future__ import annotations

from typing import Any, Iterable

from repopilot.config import (
    BROAD_PR_DIRECTORIES,
    BROAD_PR_FILES,
    LARGE_PR_CHANGES,
    LARGE_PR_FILES,
)
from repopilot.github.models import PullRequestFile, PullRequestInfo

_SENSITIVE_MARKERS = (
    ".env",
    "auth",
    "oauth",
    "jwt",
    "security",
    "permission",
    "credential",
    "secret",
    "iam",
    "access-control",
)
_DEPENDENCY_MANIFESTS = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "pipfile",
    "pipfile.lock",
    "cargo.toml",
    "cargo.lock",
    "go.mod",
    "go.sum",
}


def analyze_pull_requests(
    pull_requests: Iterable[PullRequestInfo],
    *,
    large_files: int = LARGE_PR_FILES,
    large_changes: int = LARGE_PR_CHANGES,
    broad_files: int = BROAD_PR_FILES,
    broad_directories: int = BROAD_PR_DIRECTORIES,
) -> dict[str, Any]:
    """Return observable facts and heuristic review findings for each PR."""
    for name, value in {
        "large_files": large_files,
        "large_changes": large_changes,
        "broad_files": broad_files,
        "broad_directories": broad_directories,
    }.items():
        if value < 1:
            raise ValueError(f"{name} must be at least 1")

    assessments = [
        _analyze_one(
            pull_request,
            large_files=large_files,
            large_changes=large_changes,
            broad_files=broad_files,
            broad_directories=broad_directories,
        )
        for pull_request in pull_requests
    ]
    return {
        "pull_request_count": len(assessments),
        "assessments": assessments,
        "analysis_method": (
            "Deterministic thresholds and file-name heuristics over GitHub response data. "
            "Findings are review signals, not confirmed defects or vulnerabilities."
        ),
        "thresholds": {
            "large_files": large_files,
            "large_changes": large_changes,
            "broad_files": broad_files,
            "broad_directories": broad_directories,
        },
    }


def _analyze_one(
    pull_request: PullRequestInfo,
    *,
    large_files: int,
    large_changes: int,
    broad_files: int,
    broad_directories: int,
) -> dict[str, Any]:
    files = list(pull_request.files)
    file_count = pull_request.changed_files if pull_request.changed_files is not None else len(files)
    additions = pull_request.additions if pull_request.additions is not None else sum(item.additions for item in files)
    deletions = pull_request.deletions if pull_request.deletions is not None else sum(item.deletions for item in files)
    total_changes = additions + deletions if additions is not None and deletions is not None else None
    sensitive_files = [item for item in files if _is_sensitive(item.filename)]
    test_files = [item for item in files if _is_test_file(item.filename)]
    directories = sorted({_directory(item.filename) for item in files})
    findings: list[dict[str, Any]] = []
    score_breakdown: list[dict[str, Any]] = []
    limitations: list[str] = []

    if pull_request.changed_files is None or pull_request.additions is None or pull_request.deletions is None:
        limitations.append("Pull-request summary change counts were unavailable; counts were derived from returned files where possible.")
    if pull_request.files_error:
        limitations.append(f"Changed-file retrieval was unavailable: {pull_request.files_error}")
    if pull_request.files_truncated:
        limitations.append("Changed-file results were capped; broad-change and size signals may be understated.")
    if any(item.patch_unavailable or item.patch_truncated for item in files):
        limitations.append("One or more patches were missing or truncated; line-level reasoning is incomplete.")

    if total_changes is not None and total_changes >= large_changes or file_count >= large_files:
        score_breakdown.append({"rule": "large_change", "points": 2, "evidence": "configured size threshold exceeded"})
        findings.append(_finding(
            "medium",
            "large_change",
            f"This pull request changes {file_count} files and {total_changes if total_changes is not None else 'an unknown number of'} lines, exceeding the configured review-size threshold.",
            [pull_request.html_url],
            "Split the change or assign additional reviewers and focused tests.",
        ))
    if sensitive_files:
        score_breakdown.append({"rule": "sensitive_path", "points": 3, "evidence": [item.filename for item in sensitive_files]})
        findings.append(_finding(
            "medium",
            "sensitive_path",
            "Changed paths include authentication, authorization, security configuration, secrets-like names, or dependency manifests.",
            [_file_evidence(item) for item in sensitive_files],
            "Require an appropriate security or dependency review; this heuristic does not confirm a vulnerability.",
        ))
    if file_count >= broad_files or len(directories) >= broad_directories:
        score_breakdown.append({"rule": "broad_change", "points": 2, "evidence": {"files": file_count, "directories": len(directories)}})
        findings.append(_finding(
            "medium",
            "broad_change",
            f"The change spans {file_count} files across {len(directories)} directories, which can make review coverage harder.",
            [pull_request.html_url] + [_file_evidence(item) for item in files[:10]],
            "Review by component or split unrelated changes into smaller pull requests.",
        ))
    if test_files:
        findings.append(_finding(
            "info",
            "tests_modified",
            f"The changed-file response includes {len(test_files)} test file(s).",
            [_file_evidence(item) for item in test_files],
            "Confirm the modified tests cover the production behavior changed by this pull request.",
        ))
    elif files or not pull_request.files_error:
        score_breakdown.append({"rule": "no_visible_tests", "points": 1, "evidence": "no test path in returned files"})
        findings.append(_finding(
            "low",
            "no_visible_tests",
            "No test-file modification is visible in the returned changed-file list.",
            [pull_request.html_url],
            "Ask the author to add or explain tests; absence of a changed test file is not proof of missing coverage.",
        ))
    if pull_request.draft is True:
        score_breakdown.append({"rule": "draft_review_readiness", "points": 1, "evidence": "GitHub draft=true"})
        findings.append(_finding(
            "low",
            "draft_review_readiness",
            "The pull request is marked as a draft and may not be ready for final review.",
            [pull_request.html_url],
            "Confirm intended review timing and wait for the author to mark it ready when appropriate.",
        ))

    risk_score = sum(item["points"] for item in score_breakdown)
    risk_level = "high" if risk_score >= 5 else "medium" if risk_score >= 3 else "low" if risk_score else "info"
    return {
        "number": pull_request.number,
        "title": pull_request.title,
        "state": pull_request.state,
        "evidence_url": pull_request.html_url,
        "risk_score": risk_score,
        "risk_level": risk_level,
        "score_breakdown": score_breakdown,
        "facts": {
            "changed_files": file_count,
            "additions": additions,
            "deletions": deletions,
            "total_changes": total_changes,
            "directories": directories,
            "sensitive_files": [item.filename for item in sensitive_files],
            "test_files": [item.filename for item in test_files],
            "draft": pull_request.draft,
        },
        "limitations": limitations,
        "findings": findings,
    }


def _finding(
    risk_level: str,
    rule: str,
    explanation: str,
    evidence: list[object],
    recommended_action: str,
) -> dict[str, Any]:
    return {
        "risk_level": risk_level,
        "rule": rule,
        "explanation": explanation,
        "evidence": evidence,
        "recommended_action": recommended_action,
        "heuristic": True,
        "confirmed_security_vulnerability": False,
    }


def _is_sensitive(filename: str) -> bool:
    normalized = filename.lower().replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    return basename in _DEPENDENCY_MANIFESTS or any(marker in normalized for marker in _SENSITIVE_MARKERS)


def _is_test_file(filename: str) -> bool:
    normalized = filename.lower().replace("\\", "/")
    parts = normalized.split("/")
    basename = parts[-1]
    return (
        any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in parts[:-1])
        or basename.startswith("test_")
        or ".test." in basename
        or ".spec." in basename
    )


def _directory(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    return normalized.split("/", 1)[0] if "/" in normalized else "."


def _file_evidence(item: PullRequestFile) -> dict[str, object]:
    return {
        "filename": item.filename,
        "status": item.status,
        "additions": item.additions,
        "deletions": item.deletions,
        "evidence_url": item.html_url or item.api_url,
    }
