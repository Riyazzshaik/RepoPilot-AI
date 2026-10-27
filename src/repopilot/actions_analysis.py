"""Deterministic GitHub Actions failure diagnosis."""

from __future__ import annotations

import re
from typing import Any, Iterable

from repopilot.github.models import WorkflowJob, WorkflowLogExcerpt, WorkflowRunInfo


def diagnose_workflow_failure(
    run: WorkflowRunInfo,
    jobs: Iterable[WorkflowJob],
    logs: Iterable[WorkflowLogExcerpt],
) -> dict[str, Any]:
    """Separate API observations from likely, explicitly heuristic causes."""
    job_list = list(jobs)
    log_list = list(logs)
    failed_jobs = [job for job in job_list if job.conclusion in {"failure", "timed_out", "action_required"}]
    failed_steps = [
        {"job_id": job.id, "job_name": job.name, "number": step.number, "name": step.name, "conclusion": step.conclusion}
        for job in failed_jobs
        for step in job.steps
        if step.conclusion in {"failure", "timed_out", "action_required"}
    ]
    observed = {
        "run": run.to_dict(),
        "job_count": len(job_list),
        "failed_jobs": [job.to_dict() for job in failed_jobs],
        "failed_steps": failed_steps,
        "logs": [log.to_dict() for log in log_list],
    }
    evidence_lines = [
        (log.job_id, line)
        for log in log_list
        for line in log.relevant_lines
    ]
    inferred: list[dict[str, Any]] = []
    patterns = (
        (
            "missing_dependency",
            re.compile(r"no module named|modulenotfound|cannot find module|npm err.*(missing|not found)|command not found", re.I),
            "A dependency or executable may be unavailable in the runner environment.",
            "Check dependency installation steps, lockfiles, package names, and runner PATH setup.",
        ),
        (
            "test_failure",
            re.compile(r"pytest|junit|assertionerror|test(s)? failed|failing test", re.I),
            "The available log evidence points to a test or assertion failure.",
            "Run the failing test command locally or inspect its complete test report and first assertion failure.",
        ),
        (
            "syntax_or_import_error",
            re.compile(r"syntaxerror|importerror|modulenotfounderror|cannot import", re.I),
            "The available log evidence points to a syntax or import failure.",
            "Inspect the referenced module and Python/package import paths before changing workflow configuration.",
        ),
        (
            "version_incompatibility",
            re.compile(r"requires (python|node|npm)|unsupported (python|node)|incompatible|version", re.I),
            "The available log evidence may indicate a runtime or dependency-version mismatch.",
            "Compare the workflow runtime matrix with package requirements and pin a compatible version.",
        ),
    )
    for rule, pattern, explanation, next_step in patterns:
        matches = [(job_id, line) for job_id, line in evidence_lines if pattern.search(line)]
        if matches:
            inferred.append(
                {
                    "pattern": rule,
                    "confidence": "heuristic",
                    "explanation": explanation,
                    "evidence": [{"job_id": job_id, "line": line} for job_id, line in matches[:10]],
                    "next_step": next_step,
                    "confirmed_root_cause": False,
                }
            )
    limitations = [
        log.error for log in log_list if log.error
    ]
    if not evidence_lines:
        limitations.append("No relevant log lines were available; likely causes cannot be inferred from logs.")
    if not failed_jobs and run.conclusion == "failure":
        limitations.append("The run is marked failed, but no failed job was present in the returned job data.")
    next_steps = [
        "Inspect the failed job and step evidence before changing workflow files.",
        "Re-run the reported command with the same runtime and dependency versions.",
    ]
    next_steps.extend(item["next_step"] for item in inferred)
    return {
        "observed": observed,
        "inferred_likely_causes": inferred,
        "limitations": limitations,
        "next_steps": list(dict.fromkeys(next_steps)),
        "analysis_method": "Deterministic pattern matching over returned job conclusions and bounded redacted log excerpts; root causes are not confirmed.",
    }
