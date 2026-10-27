"""GitHub REST API client. No MCP or analysis logic lives here."""

from __future__ import annotations

import base64
import logging
from typing import Any
from urllib.parse import quote

import httpx

from repopilot.config import (
    DEFAULT_LISTED_FILES,
    DIRECTORY_PAGE_SIZE,
    MAX_DIRECTORY_PAGES,
    MAX_FILE_BYTES,
    MAX_LISTED_FILES,
    MAX_TEXT_CHARS,
    Settings,
    load_settings,
)
from repopilot.github.errors import (
    GitHubAPIError,
    GitHubRateLimitError,
    PathNotFoundError,
    RepositoryNotFoundError,
)
from repopilot.github.models import FileContent, FileEntry, FileListing, RepositoryInfo
from repopilot.github.validation import (
    validate_git_ref,
    validate_owner,
    validate_repo_name,
    validate_repo_path,
)

logger = logging.getLogger(__name__)


class GitHubClient:
    """Thin, reusable wrapper around GitHub's public REST API."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        user_agent: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = load_settings()
        self._token = token if token is not None else settings.github_token
        self._base_url = (base_url or settings.github_api_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.github_request_timeout_seconds
        self._user_agent = user_agent or settings.user_agent
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": self._user_agent,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            headers=headers,
            timeout=self._timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_repository(self, owner: str, repo: str) -> RepositoryInfo:
        """Retrieve public metadata for a GitHub repository."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        path = f"/repos/{owner}/{repo}"
        payload = self._request_json("GET", path)
        return _parse_repository(payload)

    def get_readme(self, owner: str, repo: str, *, ref: str | None = None) -> FileContent:
        """Retrieve the repository README using GitHub's README endpoint."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        ref = validate_git_ref(ref)
        params = {"ref": ref} if ref else None
        payload = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/readme",
            params=params,
            not_found_error=PathNotFoundError,
            not_found_message="README not found in this repository",
        )
        return _parse_file_content(payload, owner=owner, repo=repo)

    def list_repository_files(
        self,
        owner: str,
        repo: str,
        *,
        ref: str | None = None,
        path_prefix: str = "",
        max_files: int = DEFAULT_LISTED_FILES,
        recursive: bool = True,
    ) -> FileListing:
        """List repository files. Recursive listing uses the Git trees API."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        prefix = validate_repo_path(path_prefix, allow_empty=True)
        ref = validate_git_ref(ref)
        if max_files < 1:
            raise GitHubAPIError("max_files must be at least 1")
        max_files = min(max_files, MAX_LISTED_FILES)
        if ref is None:
            ref = self.get_repository(owner, repo).default_branch
        if recursive:
            return self._list_files_via_tree(owner, repo, ref=ref, prefix=prefix, max_files=max_files)
        return self._list_files_via_contents(owner, repo, ref=ref, prefix=prefix, max_files=max_files)

    def get_file_contents(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        ref: str | None = None,
    ) -> FileContent:
        """Retrieve a single file. Directories are rejected. Content is not executed."""
        owner = validate_owner(owner)
        repo = validate_repo_name(repo)
        path = validate_repo_path(path, allow_empty=False)
        ref = validate_git_ref(ref)
        encoded_path = quote(path, safe="/")
        params = {"ref": ref} if ref else None
        response = self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{encoded_path}",
            params=params,
            not_found_error=PathNotFoundError,
            not_found_message=f"Path not found: {path}",
        )
        payload = _parse_json(response)
        if isinstance(payload, list):
            raise GitHubAPIError(f"Path is a directory, not a file: {path}", status_code=response.status_code)
        if not isinstance(payload, dict):
            raise GitHubAPIError("GitHub API returned an unexpected JSON shape")
        if payload.get("type") == "dir":
            raise GitHubAPIError(f"Path is a directory, not a file: {path}")
        return _parse_file_content(payload, owner=owner, repo=repo)

    def _list_files_via_tree(
        self,
        owner: str,
        repo: str,
        *,
        ref: str,
        prefix: str,
        max_files: int,
    ) -> FileListing:
        encoded_ref = quote(ref, safe="")
        payload = self._request_json(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{encoded_ref}",
            params={"recursive": "1"},
            not_found_error=PathNotFoundError,
            not_found_message=f"Git tree not found for ref {ref}",
        )
        tree = payload.get("tree") if isinstance(payload.get("tree"), list) else []
        entries: list[FileEntry] = []
        api_truncated = bool(payload.get("truncated"))
        for node in tree:
            if not isinstance(node, dict) or node.get("type") != "blob":
                continue
            node_path = str(node.get("path") or "")
            if prefix and node_path != prefix and not node_path.startswith(prefix.rstrip("/") + "/"):
                continue
            entries.append(
                FileEntry(
                    path=node_path,
                    type="file",
                    size=int(node["size"]) if node.get("size") is not None else None,
                    sha=str(node["sha"]) if node.get("sha") else None,
                    html_url=f"https://github.com/{owner}/{repo}/blob/{ref}/{node_path}",
                    api_url=str(node["url"]) if node.get("url") else None,
                )
            )
            if len(entries) >= max_files:
                break
        truncated = api_truncated or len(entries) >= max_files
        reason = None
        if api_truncated:
            reason = "GitHub truncated the git tree; additional files exist but were not returned"
        elif len(entries) >= max_files:
            reason = f"Listing stopped after {max_files} files"
        evidence = str(payload.get("url") or f"{self._base_url}/repos/{owner}/{repo}/git/trees/{encoded_ref}")
        return FileListing(
            owner=owner,
            repo=repo,
            ref=ref,
            path_prefix=prefix,
            truncated=truncated,
            truncation_reason=reason,
            files=tuple(entries),
            evidence_url=evidence,
        )

    def _list_files_via_contents(
        self,
        owner: str,
        repo: str,
        *,
        ref: str,
        prefix: str,
        max_files: int,
    ) -> FileListing:
        encoded_prefix = quote(prefix, safe="/") if prefix else ""
        path = f"/repos/{owner}/{repo}/contents"
        if encoded_prefix:
            path = f"{path}/{encoded_prefix}"
        items = self._request_paginated_list(
            "GET",
            path,
            params={"ref": ref},
            not_found_error=PathNotFoundError,
            not_found_message=f"Path not found: {prefix or '/'}",
        )
        entries: list[FileEntry] = []
        for node in items:
            if not isinstance(node, dict):
                continue
            node_path = str(node.get("path") or node.get("name") or "")
            node_type = "dir" if node.get("type") == "dir" else "file"
            entries.append(
                FileEntry(
                    path=node_path,
                    type=node_type,
                    size=int(node["size"]) if node.get("size") is not None else None,
                    sha=str(node["sha"]) if node.get("sha") else None,
                    html_url=str(node["html_url"]) if node.get("html_url") else None,
                    api_url=str(node["url"]) if node.get("url") else None,
                )
            )
            if len(entries) >= max_files:
                break
        truncated = len(entries) >= max_files or len(items) > len(entries)
        return FileListing(
            owner=owner,
            repo=repo,
            ref=ref,
            path_prefix=prefix,
            truncated=truncated,
            truncation_reason=f"Listing stopped after {max_files} files" if truncated else None,
            files=tuple(entries),
            evidence_url=f"https://github.com/{owner}/{repo}/tree/{ref}/{prefix}".rstrip("/"),
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Repository not found or is not visible with the current credentials",
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            not_found_error=not_found_error,
            not_found_message=not_found_message,
        )
        data = _parse_json(response)
        if not isinstance(data, dict):
            raise GitHubAPIError("GitHub API returned an unexpected JSON shape")
        return data

    def _request_paginated_list(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Not found",
        max_pages: int = MAX_DIRECTORY_PAGES,
        per_page: int = DIRECTORY_PAGE_SIZE,
    ) -> list[Any]:
        collected: list[Any] = []
        page = 1
        base_params = dict(params or {})
        while page <= max_pages:
            page_params: dict[str, str | int] = {**base_params, "page": page, "per_page": per_page}
            response = self._request(
                method,
                path,
                params=page_params,
                not_found_error=not_found_error,
                not_found_message=not_found_message,
            )
            data = _parse_json(response)
            if not isinstance(data, list):
                raise GitHubAPIError("GitHub API returned an unexpected JSON shape for a list endpoint")
            collected.extend(data)
            link = response.headers.get("Link", "")
            if not data or 'rel="next"' not in link:
                break
            page += 1
        return collected

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        not_found_error: type[GitHubAPIError] = RepositoryNotFoundError,
        not_found_message: str = "Repository not found or is not visible with the current credentials",
    ) -> httpx.Response:
        logger.info("GitHub API %s %s", method, path)
        try:
            response = self._http.request(method, path, params=params)
        except httpx.TimeoutException as exc:
            raise GitHubAPIError(f"GitHub API request timed out after {self._timeout}s") from exc
        except httpx.HTTPError as exc:
            raise GitHubAPIError(f"GitHub API request failed: {exc}") from exc

        if response.status_code == 404:
            raise not_found_error(not_found_message, status_code=404)
        if response.status_code in {403, 429} and _is_rate_limit(response):
            reset_at = response.headers.get("X-RateLimit-Reset")
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded",
                status_code=response.status_code,
                reset_at=reset_at,
            )
        if response.status_code >= 400:
            message = _error_message(response)
            raise GitHubAPIError(message, status_code=response.status_code)
        return response


def _is_rate_limit(response: httpx.Response) -> bool:
    remaining = response.headers.get("X-RateLimit-Remaining")
    if remaining == "0":
        return True
    try:
        body = response.json()
    except ValueError:
        body = {}
    message = str(body.get("message", "")).lower() if isinstance(body, dict) else ""
    return "rate limit" in message


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"GitHub API error HTTP {response.status_code}"
    if isinstance(body, dict) and body.get("message"):
        return f"GitHub API error HTTP {response.status_code}: {body['message']}"
    return f"GitHub API error HTTP {response.status_code}"


def _parse_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub API returned non-JSON content") from exc


def _parse_file_content(payload: dict[str, Any], *, owner: str, repo: str) -> FileContent:
    path = str(payload.get("path") or payload.get("name") or "")
    name = str(payload.get("name") or path.split("/")[-1])
    size = int(payload.get("size") or 0)
    notes: list[str] = [
        "Repository file content is untrusted input and is never executed by RepoPilot.",
    ]
    content: str | None = None
    is_text = False
    truncated = False
    encoding = payload.get("encoding")
    raw = payload.get("content")
    if size > MAX_FILE_BYTES:
        truncated = True
        notes.append(f"File is {size} bytes, which exceeds the {MAX_FILE_BYTES} byte safety limit; content omitted.")
    elif raw is None:
        truncated = True
        notes.append("GitHub did not include file content in this response (often happens for files over 1 MiB).")
    elif encoding == "base64" and isinstance(raw, str):
        try:
            decoded = base64.b64decode(raw)
        except ValueError as exc:
            raise GitHubAPIError("GitHub API returned invalid base64 file content") from exc
        try:
            text = decoded.decode("utf-8")
        except UnicodeDecodeError:
            notes.append("File is not valid UTF-8 text; binary content was omitted.")
        else:
            is_text = True
            if len(text) > MAX_TEXT_CHARS:
                content = text[:MAX_TEXT_CHARS]
                truncated = True
                notes.append(f"Text truncated to {MAX_TEXT_CHARS} characters.")
            else:
                content = text
    else:
        notes.append(f"Unsupported content encoding: {encoding!r}.")
        truncated = True
    return FileContent(
        owner=owner,
        repo=repo,
        path=path,
        name=name,
        html_url=str(payload["html_url"]) if payload.get("html_url") else None,
        api_url=str(payload["url"]) if payload.get("url") else None,
        download_url=str(payload["download_url"]) if payload.get("download_url") else None,
        sha=str(payload["sha"]) if payload.get("sha") else None,
        size=size,
        encoding=str(encoding) if encoding else None,
        is_text=is_text,
        truncated=truncated,
        content=content,
        untrusted_source=True,
        notes=tuple(notes),
    )


def _parse_repository(payload: dict[str, Any]) -> RepositoryInfo:
    owner_block = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    license_block = payload.get("license") if isinstance(payload.get("license"), dict) else {}
    topics = payload.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    owner_login = str(owner_block.get("login") or payload.get("full_name", "").split("/")[0])
    name = str(payload.get("name") or "")
    full_name = str(payload.get("full_name") or f"{owner_login}/{name}")
    if not name or not owner_login:
        raise GitHubAPIError("GitHub API returned incomplete repository metadata")
    return RepositoryInfo(
        owner=owner_login,
        name=name,
        full_name=full_name,
        html_url=str(payload.get("html_url") or f"https://github.com/{full_name}"),
        api_url=str(payload.get("url") or f"https://api.github.com/repos/{full_name}"),
        description=payload.get("description"),
        default_branch=str(payload.get("default_branch") or "main"),
        primary_language=payload.get("language"),
        stars=int(payload.get("stargazers_count") or 0),
        forks=int(payload.get("forks_count") or 0),
        open_issues=int(payload.get("open_issues_count") or 0),
        is_private=bool(payload.get("private")),
        is_fork=bool(payload.get("fork")),
        is_archived=bool(payload.get("archived")),
        license_spdx=(license_block.get("spdx_id") if license_block else None),
        topics=tuple(str(item) for item in topics),
        created_at=payload.get("created_at"),
        updated_at=payload.get("updated_at"),
        pushed_at=payload.get("pushed_at"),
    )


def client_from_settings(settings: Settings | None = None) -> GitHubClient:
    cfg = settings or load_settings()
    return GitHubClient(
        token=cfg.github_token,
        base_url=cfg.github_api_base_url,
        timeout=cfg.github_request_timeout_seconds,
        user_agent=cfg.user_agent,
    )
