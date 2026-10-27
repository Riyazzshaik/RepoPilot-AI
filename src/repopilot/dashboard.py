"""Local Streamlit dashboard over RepoPilot's read-only services."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from repopilot.actions_analysis import diagnose_workflow_failure
from repopilot.config import DEFAULT_ISSUES, DEFAULT_PULL_REQUESTS, DEFAULT_WORKFLOW_RUNS, DEFAULT_WORKFLOWS
from repopilot.github.client import GitHubClient, client_from_settings
from repopilot.github.validation import validate_owner, validate_repo_name
from repopilot.issue_analysis import analyze_issues
from repopilot.pr_analysis import analyze_pull_requests

T = TypeVar("T")


def validate_dashboard_repository(owner: str, repo: str) -> tuple[str, str]:
    """Validate the two dashboard repository fields before any network call."""
    return validate_owner(owner), validate_repo_name(repo)


def fetch_overview(client: GitHubClient, owner: str, repo: str) -> dict[str, Any]:
    return {**client.get_repository(owner, repo).to_dict(), "refreshed_at": _now()}


def fetch_issue_report(client: GitHubClient, owner: str, repo: str) -> dict[str, Any]:
    repository = client.get_repository(owner, repo)
    listing = client.list_repository_issues(owner, repo, state="all", max_issues=DEFAULT_ISSUES)
    return {
        "listing": listing.to_dict(),
        "analysis": analyze_issues(listing.issues),
        "records_analyzed": len(listing.issues),
        "configured_maximum": DEFAULT_ISSUES,
        "sample_truncated": listing.truncated,
        "repository_open_issues": repository.open_issues,
        "refreshed_at": _now(),
    }


def fetch_pull_request_report(client: GitHubClient, owner: str, repo: str) -> dict[str, Any]:
    listing = client.list_repository_pull_requests(
        owner,
        repo,
        state="all",
        max_pull_requests=DEFAULT_PULL_REQUESTS,
    )
    return {
        "listing": listing.to_dict(),
        "analysis": analyze_pull_requests(listing.pull_requests),
        "records_analyzed": len(listing.pull_requests),
        "configured_maximum": DEFAULT_PULL_REQUESTS,
        "sample_truncated": listing.truncated,
        "refreshed_at": _now(),
    }


def fetch_actions_report(client: GitHubClient, owner: str, repo: str) -> dict[str, Any]:
    workflows = client.list_repository_workflows(owner, repo, max_workflows=DEFAULT_WORKFLOWS)
    runs = client.list_workflow_runs(owner, repo, max_runs=DEFAULT_WORKFLOW_RUNS)
    return {
        "workflows": workflows.to_dict(),
        "runs": runs.to_dict(),
        "workflow_records_analyzed": len(workflows.workflows),
        "run_records_analyzed": len(runs.runs),
        "workflow_configured_maximum": DEFAULT_WORKFLOWS,
        "run_configured_maximum": DEFAULT_WORKFLOW_RUNS,
        "refreshed_at": _now(),
    }


def fetch_failure_report(
    client: GitHubClient,
    owner: str,
    repo: str,
    run_id: int,
    *,
    max_log_lines: int = 80,
) -> dict[str, Any]:
    run = client.get_workflow_run(owner, repo, run_id)
    jobs = client.get_workflow_jobs(owner, repo, run_id)
    failed_jobs = [job for job in jobs if job.conclusion in {"failure", "timed_out", "action_required"}]
    logs = [client.get_job_logs(owner, repo, job.id, max_lines=max_log_lines) for job in failed_jobs]
    return {
        "run": run.to_dict(),
        "jobs": [job.to_dict() for job in jobs],
        "logs": [log.to_dict() for log in logs],
        "diagnosis": diagnose_workflow_failure(run, jobs, logs),
        "refreshed_at": _now(),
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    """Render the dashboard; Streamlit remains an optional import for library users."""
    import streamlit as st

    st.set_page_config(
        page_title="RepoPilot AI",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        .block-container { max-width: 1380px; padding-top: 2rem; }
        [data-testid="stMetricValue"] { letter-spacing: -0.04em; }
        .repo-kicker { color: #79c2ff; font-size: .78rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
        .repo-title { font-size: 2.5rem; font-weight: 800; letter-spacing: -.06em; margin: 0 0 .35rem; }
        .repo-subtitle { color: #91a4b7; margin-bottom: 1.5rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.caption("All views are read-only. Data is fetched on demand and cached until Refresh data is pressed.")

    if "dashboard_cache" not in st.session_state:
        st.session_state.dashboard_cache = {}
    st.sidebar.markdown("### ◈ RepoPilot AI")
    st.sidebar.caption("Read-only repository intelligence")
    owner = st.sidebar.text_input("Owner", value="octocat")
    repo = st.sidebar.text_input("Repository", value="Hello-World")
    if st.sidebar.button("Refresh data", use_container_width=True):
        st.session_state.dashboard_cache = {}
        st.rerun()
    section = st.sidebar.radio("Explore", ["Overview", "Issues", "Pull Requests", "GitHub Actions"])

    try:
        owner, repo = validate_dashboard_repository(owner, repo)
    except ValueError as exc:
        st.error(str(exc))
        st.info("Enter a GitHub owner and repository name, for example `octocat` and `Hello-World`.")
        return

    st.markdown('<div class="repo-kicker">Repository intelligence workspace</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="repo-title">{owner}/{repo}</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="repo-subtitle">Evidence-first views for code, issues, pull requests, and CI health.</div>',
        unsafe_allow_html=True,
    )

    if section == "Overview":
        _render_overview(st, owner, repo)
    elif section == "Issues":
        _render_issues(st, owner, repo)
    elif section == "Pull Requests":
        _render_pull_requests(st, owner, repo)
    else:
        _render_actions(st, owner, repo)


def _get_cached(st: Any, key: str, loader: Callable[[], T]) -> T:
    if key not in st.session_state.dashboard_cache:
        with st.spinner("Querying GitHub..."):
            try:
                st.session_state.dashboard_cache[key] = loader()
            except Exception as exc:
                st.error(str(exc))
                raise
    return st.session_state.dashboard_cache[key]


def _with_client(owner: str, repo: str, loader: Callable[[GitHubClient, str, str], T]) -> T:
    with client_from_settings() as client:
        return loader(client, owner, repo)


def _render_overview(st: Any, owner: str, repo: str) -> None:
    try:
        data = _get_cached(st, f"overview:{owner}/{repo}", lambda: _with_client(owner, repo, fetch_overview))
    except Exception:
        return
    st.subheader("Repository overview")
    st.caption(f"Last refreshed: {data['refreshed_at']}")
    metrics = st.columns(4)
    metrics[0].metric("Stars", f"{data['stars']:,}")
    metrics[1].metric("Forks", f"{data['forks']:,}")
    metrics[2].metric("Open issues (GitHub)", f"{data['open_issues']:,}")
    metrics[3].metric("Primary language", data["primary_language"] or "Not reported")
    st.info(data["description"] or "This repository has no description.")
    left, right = st.columns(2)
    with left:
        st.markdown("**Repository details**")
        st.dataframe(
            [{"Field": "Default branch", "Value": data["default_branch"]}, {"Field": "License", "Value": data["license_spdx"] or "Not reported"}, {"Field": "Topics", "Value": ", ".join(data["topics"]) or "None"}],
            hide_index=True,
            use_container_width=True,
        )
    with right:
        st.markdown("**Evidence links**")
        st.link_button("Open repository on GitHub", data["html_url"])
        st.link_button("Open GitHub API response", data["api_url"])


def _render_issues(st: Any, owner: str, repo: str) -> None:
    try:
        report = _get_cached(st, f"issues:{owner}/{repo}", lambda: _with_client(owner, repo, fetch_issue_report))
    except Exception:
        return
    listing, analysis = report["listing"], report["analysis"]
    st.subheader("Issue intelligence")
    st.caption(f"Last refreshed: {report['refreshed_at']}")
    sample_note = f"Analyzed {report['records_analyzed']} records (configured maximum {report['configured_maximum']})."
    if report["sample_truncated"]:
        st.warning(sample_note + " This is a limited sample, not a repository-wide issue report.")
    else:
        st.caption(sample_note + " Counts below describe the returned ordinary-issue sample.")
    if report["repository_open_issues"] != analysis["open_count"] or report["sample_truncated"]:
        st.info(
            f"GitHub repository metric: {report['repository_open_issues']:,} open issues. "
            f"Issue analysis sample: {analysis['open_count']:,} open records. These values are not expected to match when the sample is limited."
        )
    metrics = st.columns(4)
    metrics[0].metric("Analyzed", analysis["issue_count"])
    metrics[1].metric("Open in sample", analysis["open_count"])
    metrics[2].metric("Closed in sample", analysis["closed_count"])
    metrics[3].metric("Stale", len(analysis["stale_issue_numbers"]))
    if listing["issue_count"] == 0:
        st.success("No ordinary issues were returned for this repository.")
        return
    st.markdown("**Categories**")
    st.bar_chart(analysis["category_counts"])
    if analysis["priority_counts"]:
        st.caption("Explicit priority labels")
        st.json(analysis["priority_counts"])
    for recommendation in analysis["recommendations"]:
        with st.expander(f"Recommendation: {recommendation['action']}"):
            st.write(recommendation["reason"])
            if "issue_numbers" in recommendation:
                st.write("Issues:", ", ".join(f"#{number}" for number in recommendation["issue_numbers"]))
    st.dataframe(analysis["assessments"], hide_index=True, use_container_width=True)
    if analysis["duplicate_candidates"]:
        with st.expander(f"Duplicate candidates ({len(analysis['duplicate_candidates'])})"):
            st.dataframe(analysis["duplicate_candidates"], hide_index=True, use_container_width=True)
    with st.expander("Retrieval details"):
        st.write(f"Excluded pull requests: {listing['excluded_pull_requests']}")
        st.write(f"Evidence: {listing['evidence_url']}")


def _render_pull_requests(st: Any, owner: str, repo: str) -> None:
    try:
        report = _get_cached(st, f"pulls:{owner}/{repo}", lambda: _with_client(owner, repo, fetch_pull_request_report))
    except Exception:
        return
    listing, analysis = report["listing"], report["analysis"]
    st.subheader("Pull-request risk review")
    st.caption(f"Last refreshed: {report['refreshed_at']}")
    sample_note = f"Analyzed {report['records_analyzed']} records (configured maximum {report['configured_maximum']})."
    st.warning(sample_note + " Findings describe this returned sample.") if report["sample_truncated"] else st.caption(sample_note)
    st.metric("Pull requests analyzed", listing["pull_request_count"])
    if not listing["pull_request_count"]:
        st.success("No pull requests were returned for this repository.")
        return
    for assessment in analysis["assessments"]:
        facts = assessment["facts"]
        with st.expander(f"#{assessment['number']} · {assessment['title']}"):
            st.write(f"Risk: {assessment['risk_level'].upper()} · Score: {assessment['risk_score']} · {facts['changed_files']} files · +{facts['additions']} / -{facts['deletions']}")
            st.link_button("Open pull request evidence", assessment["evidence_url"])
            if facts["sensitive_files"]:
                st.warning("Sensitive-file indicators: " + ", ".join(facts["sensitive_files"]))
            st.caption("Test-file signal: " + (", ".join(facts["test_files"]) if facts["test_files"] else "No visible test-file changes"))
            if assessment["score_breakdown"]:
                st.dataframe(assessment["score_breakdown"], hide_index=True, use_container_width=True)
            if assessment["limitations"]:
                st.warning("Limitations: " + " ".join(assessment["limitations"]))
            if not assessment["findings"]:
                st.success("No configured heuristic findings.")
            for finding in assessment["findings"]:
                message = f"{finding['risk_level'].upper()} · {finding['explanation']}"
                if finding["risk_level"] == "medium":
                    st.warning(message)
                elif finding["risk_level"] == "low":
                    st.info(message)
                else:
                    st.write(message)
                st.caption(f"Action: {finding['recommended_action']}")
                with st.expander("Evidence"):
                    st.json(finding["evidence"])


def _render_actions(st: Any, owner: str, repo: str) -> None:
    try:
        report = _get_cached(st, f"actions:{owner}/{repo}", lambda: _with_client(owner, repo, fetch_actions_report))
    except Exception:
        return
    workflows, runs = report["workflows"], report["runs"]
    st.subheader("GitHub Actions")
    st.caption(f"Last refreshed: {report['refreshed_at']}")
    metrics = st.columns(3)
    metrics[0].metric("Workflows analyzed", f"{report['workflow_records_analyzed']}/{report['workflow_configured_maximum']}")
    metrics[1].metric("Runs analyzed", f"{report['run_records_analyzed']}/{report['run_configured_maximum']}")
    metrics[2].metric("Failed runs", sum(item["conclusion"] == "failure" for item in runs["runs"]))
    if not workflows["workflow_count"]:
        st.info("No workflows were reported for this repository.")
    else:
        st.dataframe(workflows["workflows"], hide_index=True, use_container_width=True)
    if runs["run_count"]:
        st.dataframe(
            [{"id": item["id"], "name": item["name"], "status": item["status"], "conclusion": item["conclusion"], "branch": item["branch"], "event": item["event"]} for item in runs["runs"]],
            hide_index=True,
            use_container_width=True,
        )
        failed_runs = [item for item in runs["runs"] if item["conclusion"] == "failure"]
        if failed_runs:
            selected_id = st.selectbox("Investigate failed run", [item["id"] for item in failed_runs])
            if st.button("Investigate selected run"):
                try:
                    with st.spinner("Inspecting failed jobs and bounded logs..."):
                        detail = _with_client(owner, repo, lambda client, o, r: fetch_failure_report(client, o, r, selected_id))
                    _render_failure_detail(st, detail)
                except Exception as exc:
                    st.error(str(exc))
    else:
        st.success("No workflow runs were returned.")


def _render_failure_detail(st: Any, detail: dict[str, Any]) -> None:
    diagnosis = detail["diagnosis"]
    st.markdown("### Failure investigation")
    st.caption(f"Last refreshed: {detail['refreshed_at']}")
    if diagnosis["inferred_likely_causes"]:
        for cause in diagnosis["inferred_likely_causes"]:
            st.warning(f"Heuristic: {cause['explanation']}")
            st.caption(f"Next step: {cause['next_step']}")
    else:
        st.info("No deterministic failure pattern matched the available evidence.")
    for limitation in diagnosis["limitations"]:
        st.warning(limitation)
    with st.expander("Observed jobs and steps"):
        st.json(diagnosis["observed"]["failed_steps"])
    with st.expander("Relevant log evidence"):
        for log in detail["logs"]:
            st.markdown(f"**Job {log['job_id']}**")
            if log["relevant_lines"]:
                st.code("\n".join(log["relevant_lines"]), language="text")
            elif log["error"]:
                st.caption(log["error"])


if __name__ == "__main__":
    main()
