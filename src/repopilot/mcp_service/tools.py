"""MCP tool implementations. These call the GitHub client; they do not talk HTTP themselves."""

from __future__ import annotations

import logging
from typing import Any

from repopilot.config import DEFAULT_LISTED_FILES
from repopilot.github.client import GitHubClient
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
