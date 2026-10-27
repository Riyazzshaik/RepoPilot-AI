"""Validate GitHub owner and repository identifiers."""

from __future__ import annotations

import re

from repopilot.github.errors import InvalidPathError, InvalidRepositoryError

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_RESERVED = {".", ".."}


def validate_owner(owner: str) -> str:
    value = (owner or "").strip()
    if not value or value in _RESERVED or "/" in value or "\\" in value:
        raise InvalidRepositoryError("Invalid repository owner")
    if not _OWNER_RE.fullmatch(value):
        raise InvalidRepositoryError("Invalid repository owner")
    return value


def validate_repo_name(repo: str) -> str:
    value = (repo or "").strip()
    if not value or value in _RESERVED or "/" in value or "\\" in value:
        raise InvalidRepositoryError("Invalid repository name")
    if len(value) > 100 or not _REPO_RE.fullmatch(value):
        raise InvalidRepositoryError("Invalid repository name")
    return value


_REF_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_PATH_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._@%+-]+$")
_MAX_PATH_LENGTH = 4096


def parse_repo_ref(ref: str) -> tuple[str, str]:
    """Parse 'owner/repo' into validated components."""
    text = (ref or "").strip()
    if text.count("/") != 1:
        raise InvalidRepositoryError("Repository must be specified as owner/repo")
    owner, repo = text.split("/", 1)
    return validate_owner(owner), validate_repo_name(repo)


def validate_git_ref(ref: str | None) -> str | None:
    """Validate an optional branch, tag, or commit-ish. None means default branch."""
    if ref is None:
        return None
    value = ref.strip()
    if not value:
        return None
    if "\\" in value or ".." in value or value.startswith("/") or value.endswith("/"):
        raise InvalidPathError("Invalid git ref")
    if not _REF_RE.fullmatch(value):
        raise InvalidPathError("Invalid git ref")
    return value


def validate_repo_path(path: str, *, allow_empty: bool = False) -> str:
    """Validate a repository-relative path. Rejects traversal and absolute paths."""
    value = (path or "").strip().replace("\\", "/")
    if not value:
        if allow_empty:
            return ""
        raise InvalidPathError("File path is required")
    if value.startswith("/") or value.startswith("~") or ":" in value:
        raise InvalidPathError("Invalid repository path")
    if len(value) > _MAX_PATH_LENGTH:
        raise InvalidPathError("Repository path is too long")
    parts = value.split("/")
    for part in parts:
        if part in {"", ".", ".."}:
            raise InvalidPathError("Invalid repository path")
        if not _PATH_SEGMENT_RE.fullmatch(part):
            raise InvalidPathError("Invalid repository path")
    return "/".join(parts)
