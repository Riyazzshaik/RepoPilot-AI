"""Typed GitHub API and validation errors."""

from __future__ import annotations


class GitHubAPIError(Exception):
    """Raised when the GitHub API returns an unexpected error."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RepositoryNotFoundError(GitHubAPIError):
    """Raised when a repository does not exist or is not visible."""


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub rate-limits the client."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reset_at: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.reset_at = reset_at


class InvalidRepositoryError(ValueError):
    """Raised when owner or repository name fails validation."""


class InvalidPathError(ValueError):
    """Raised when a repository file path or git ref fails validation."""


class PathNotFoundError(GitHubAPIError):
    """Raised when a file, directory, or README does not exist.""""""
