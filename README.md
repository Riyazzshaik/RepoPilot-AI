# RepoPilot AI — Your GitHub Repository Assistant

RepoPilot is a local, zero-cost GitHub intelligence toolkit. The current milestone provides a read-only GitHub REST client and a genuine MCP server with repository metadata, file listing, file-content, deterministic issue intelligence, pull-request risk analysis, and GitHub Actions failure investigation. Write actions and the Streamlit dashboard are not implemented yet.

## Problem statement

Engineers spend time gathering repository context, issues, pull requests, and CI failures by hand. RepoPilot AI will expose that work through a real Model Context Protocol server, deterministic analysis, and a local dashboard — without paid LLM or hosting services.

## Current scope (Milestone 5)

- Project package layout under `src/repopilot`.
- GitHub REST client with timeouts, validation, pagination and typed errors.
- Official Python MCP SDK server over stdio with ten read-only tools:
  `get_repository_info`, `list_repository_files`, `get_file_contents`,
  `list_repository_issues`, `analyze_repository_issues`,
  `list_repository_pull_requests`, `analyze_pull_request_risks`,
  `list_repository_workflows`, `list_workflow_runs`, and
  `investigate_workflow_failure`.
- Issue retrieval through the official `/repos/{owner}/{repo}/issues` endpoint with capped pagination,
  ordinary-issue filtering, and typed API errors.
- Deterministic issue analysis exposed through `list_repository_issues` and
  `analyze_repository_issues`. It reports state counts, label-based categories,
  unlabeled issues, long-open issues, recurring keyword themes, recommendations,
  and evidence URLs.
- Pull-request retrieval includes bounded metadata and changed-file information,
  preserving missing or truncated patches as explicit limitations.
- Pull-request risk analysis uses explainable thresholds for large changes,
  sensitive paths, broad changes, test-file visibility, and draft readiness.
- GitHub Actions investigation uses the documented workflow, run, job, and job-log
  endpoints. It reports run status, failed jobs and steps, bounded redacted log
  excerpts, deterministic likely-cause signals, and next debugging steps.
- Offline unit tests with mocked HTTP responses plus an opt-in live call.

## Prerequisites

- Python 3.11+ (developed against 3.13.3).
- Optional: a GitHub personal access token for a higher rate limit. Public metadata works unauthenticated (60 requests/hour).

## Installation

```powershell
cd C:\Users\Riyaz\OneDrive\Desktop\Git_Mcp
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pip install -e .
```

## Configuration

Copy `.env.example` to `.env` only if you want to set `GITHUB_TOKEN`. Do not commit `.env`.

## Local commands

```powershell
python -m pytest tests
python -m repopilot get-repo octocat/Hello-World
```

The issue MCP tools accept `state` as `open`, `closed`, or `all`, and cap retrieval with
`max_issues` to avoid unbounded API requests. `analyze_repository_issues` also accepts
`long_open_days` (default `90`). Example MCP tool arguments:

```json
{"owner": "octocat", "repo": "Hello-World", "state": "all", "max_issues": 100}
```

Pull-request tools use the same `state` values. `max_pull_requests` and
`max_files_per_pull_request` cap API work. Example arguments:

```json
{"owner": "octocat", "repo": "Hello-World", "state": "open", "max_pull_requests": 20, "max_files_per_pull_request": 200}
```

Actions tools use the documented read endpoints. Run filters accept GitHub's
`status` values such as `failure`, `success`, `queued`, `in_progress`, and
`cancelled`. Example run lookup:

```json
{"owner": "octocat", "repo": "Hello-World", "workflow_id": 7, "status": "failure", "max_runs": 50}
```

Failure investigation accepts a run ID and returns failed jobs, failed steps,
bounded redacted log excerpts, and diagnosis evidence:

```json
{"owner": "octocat", "repo": "Hello-World", "run_id": 12345, "max_log_lines": 80}
```

The official GitHub REST API documents these read operations as available to
users with repository read access. For private repositories, use credentials
with repository access; classic personal access tokens require the documented
`repo` scope, while fine-grained tokens should grant repository metadata and
Actions read permissions. Public repositories can be queried without a token,
subject to GitHub's unauthenticated rate limits.

Start the MCP server over stdio:

```powershell
python -m repopilot mcp
```

Configure an MCP client to launch that command from the project directory. For example, an MCP client configuration uses the executable `python`, arguments `-m repopilot mcp`, and working directory `C:\Users\Riyaz\OneDrive\Desktop\Git_Mcp`. The server communicates using MCP JSON-RPC over stdin/stdout; logs go to stderr. The SDK-level in-memory client test in `tests/test_mcp_tools.py` verifies initialization, tool discovery, and a tool call without a network connection to MCP.

Live GitHub integration test:

```powershell
$env:RUN_INTEGRATION="1"
python -m pytest tests -m integration
```

## Security

- Tokens are read from the environment only.
- Write operations are not implemented in this milestone.
- Owner and repository names are validated before any HTTP call.
- Repository content is treated as untrusted text, capped in size, and never executed.
- Pull requests returned by GitHub's issues endpoint are excluded using the API's
  `pull_request` marker.
- Issue themes use simple keyword rules and are triage aids, not duplicate-detection
  proof, severity predictions, or an AI model's judgment. The analyzer does not close
  issues, edit labels, or post comments.
- Pull-request findings are heuristic review signals based on returned metadata and
  filenames. A sensitive path is not a confirmed security vulnerability. Missing,
  truncated, or permission-limited file/patch data is reported as a limitation rather
  than inferred.
- Workflow log download URLs are short-lived redirects. RepoPilot follows only one
  HTTPS redirect and does not send the GitHub bearer token to the signed download
  host. Logs are bounded, redacted for common secret assignments, and never returned
  wholesale. Expired, binary, oversized, or permission-limited logs produce explicit
  limitations.
- Workflow diagnosis separates observed API data from heuristic likely causes. It
  does not claim a root cause is confirmed and does not rerun, cancel, approve, or
  modify workflow runs.
- The `mcp` dependency is the free official Python MCP SDK; no paid API or hosting service is required.

## License

MIT. Chosen because this is an original personal portfolio project with no third-party copyleft constraints at this stage.
