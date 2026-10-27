# RepoPilot AI — Your Autonomous GitHub Repository Engineer

Milestone 1 of a local, zero-cost GitHub intelligence toolkit. This repository currently implements a **minimal GitHub REST client** that retrieves **public repository metadata**. MCP tools, issue analysis, pull-request risk scoring, and the Streamlit dashboard are not implemented yet.

## Problem statement

Engineers spend time gathering repository context, issues, pull requests, and CI failures by hand. RepoPilot AI will expose that work through a real Model Context Protocol server, deterministic analysis, and a local dashboard — without paid LLM or hosting services.

## Current scope (Milestone 1)

- Inspected an empty workspace and verified Python 3.13.
- Project package layout under `src/repopilot`.
- GitHub REST client with timeouts, validation, and typed errors.
- Offline unit tests plus an opt-in live call against `octocat/Hello-World`.

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

Live GitHub integration test:

```powershell
$env:RUN_INTEGRATION="1"
python -m pytest tests -m integration
```

## Security

- Tokens are read from the environment only.
- Write operations are not implemented in this milestone.
- Owner and repository names are validated before any HTTP call.

## License

MIT. Chosen because this is an original personal portfolio project with no third-party copyleft constraints at this stage.
