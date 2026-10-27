"""Structured GitHub payloads used by RepoPilot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryInfo:
    owner: str
    name: str
    full_name: str
    html_url: str
    api_url: str
    description: str | None
    default_branch: str
    primary_language: str | None
    stars: int
    forks: int
    open_issues: int
    is_private: bool
    is_fork: bool
    is_archived: bool
    license_spdx: str | None
    topics: tuple[str, ...]
    created_at: str | None
    updated_at: str | None
    pushed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "name": self.name,
            "full_name": self.full_name,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "description": self.description,
            "default_branch": self.default_branch,
            "primary_language": self.primary_language,
            "stars": self.stars,
            "forks": self.forks,
            "open_issues": self.open_issues,
            "is_private": self.is_private,
            "is_fork": self.is_fork,
            "is_archived": self.is_archived,
            "license_spdx": self.license_spdx,
            "topics": list(self.topics),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pushed_at": self.pushed_at,
        }


@dataclass(frozen=True)
class FileEntry:
    path: str
    type: str
    size: int | None
    sha: str | None
    html_url: str | None
    api_url: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "sha": self.sha,
            "html_url": self.html_url,
            "api_url": self.api_url,
        }


@dataclass(frozen=True)
class FileListing:
    owner: str
    repo: str
    ref: str
    path_prefix: str
    truncated: bool
    truncation_reason: str | None
    files: tuple[FileEntry, ...]
    evidence_url: str

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "ref": self.ref,
            "path_prefix": self.path_prefix,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "file_count": len(self.files),
            "files": [item.to_dict() for item in self.files],
            "evidence_url": self.evidence_url,
        }


@dataclass(frozen=True)
class FileContent:
    owner: str
    repo: str
    path: str
    name: str
    html_url: str | None
    api_url: str | None
    download_url: str | None
    sha: str | None
    size: int
    encoding: str | None
    is_text: bool
    truncated: bool
    content: str | None
    untrusted_source: bool
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "owner": self.owner,
            "repo": self.repo,
            "path": self.path,
            "name": self.name,
            "html_url": self.html_url,
            "api_url": self.api_url,
            "download_url": self.download_url,
            "sha": self.sha,
            "size": self.size,
            "encoding": self.encoding,
            "is_text": self.is_text,
            "truncated": self.truncated,
            "content": self.content,
            "untrusted_source": self.untrusted_source,
            "notes": list(self.notes),
        }
