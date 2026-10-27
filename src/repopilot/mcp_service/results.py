"""Predictable JSON payloads returned by MCP tools."""

from __future__ import annotations

from typing import Any

from repopilot.github.errors import GitHubAPIError, InvalidPathError, InvalidRepositoryError


def ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "error": None, "error_type": None, "data": data}


def fail(exc: BaseException) -> dict[str, Any]:
    error_type = type(exc).__name__
    if isinstance(exc, (GitHubAPIError, InvalidRepositoryError, InvalidPathError, ValueError)):
        message = str(exc)
    else:
        message = "Unexpected error while handling this request"
    return {"ok": False, "error": message, "error_type": error_type, "data": None}
