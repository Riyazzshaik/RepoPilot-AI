"""Environment-backed configuration. Tokens are never hardcoded."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_API_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "RepoPilot-AI/0.1"
MAX_FILE_BYTES = 512 * 1024
MAX_TEXT_CHARS = 100_000
DEFAULT_LISTED_FILES = 500
MAX_LISTED_FILES = 2000
MAX_DIRECTORY_PAGES = 10
DIRECTORY_PAGE_SIZE = 100
DEFAULT_ISSUES = 100
MAX_ISSUES = 500
LONG_OPEN_ISSUE_DAYS = 90
DEFAULT_PULL_REQUESTS = 20
MAX_PULL_REQUESTS = 100
DEFAULT_PR_FILES = 200
MAX_PR_FILES = 1000
MAX_PATCH_CHARS = 20_000
LARGE_PR_FILES = 50
LARGE_PR_CHANGES = 1_000
BROAD_PR_DIRECTORIES = 10
BROAD_PR_FILES = 20
DEFAULT_WORKFLOWS = 50
MAX_WORKFLOWS = 200
DEFAULT_WORKFLOW_RUNS = 50
MAX_WORKFLOW_RUNS = 200
DEFAULT_LOG_LINES = 80
MAX_LOG_LINES = 500
MAX_LOG_CHARS = 50_000
LOG_CONTEXT_LINES = 2


@dataclass(frozen=True)
class Settings:
    github_token: str | None
    github_api_base_url: str
    github_request_timeout_seconds: float
    user_agent: str


def load_settings() -> Settings:
    token = os.getenv("GITHUB_TOKEN", "").strip() or None
    timeout_raw = os.getenv("GITHUB_REQUEST_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise ValueError("GITHUB_REQUEST_TIMEOUT_SECONDS must be a number") from exc
    if timeout <= 0:
        raise ValueError("GITHUB_REQUEST_TIMEOUT_SECONDS must be greater than zero")

    base_url = os.getenv("GITHUB_API_BASE_URL", DEFAULT_API_BASE_URL).strip().rstrip("/")
    if not base_url:
        base_url = DEFAULT_API_BASE_URL

    user_agent = os.getenv("REPOPILOT_USER_AGENT", DEFAULT_USER_AGENT).strip() or DEFAULT_USER_AGENT
    return Settings(
        github_token=token,
        github_api_base_url=base_url,
        github_request_timeout_seconds=timeout,
        user_agent=user_agent,
    )
