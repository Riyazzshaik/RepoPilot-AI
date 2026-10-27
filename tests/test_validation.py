from __future__ import annotations

import pytest

from repopilot.github.errors import InvalidPathError, InvalidRepositoryError
from repopilot.github.validation import (
    parse_repo_ref,
    validate_git_ref,
    validate_owner,
    validate_repo_name,
    validate_repo_path,
)


def test_valid_owner_and_repo() -> None:
    assert validate_owner("octocat") == "octocat"
    assert validate_repo_name("Hello-World") == "Hello-World"
    assert parse_repo_ref("octocat/Hello-World") == ("octocat", "Hello-World")


@pytest.mark.parametrize(
    "owner",
    ["", "../etc", "octo/cat", "octo\\cat", ".", "..", "-bad", "bad-", "a" * 40],
)
def test_invalid_owner(owner: str) -> None:
    with pytest.raises(InvalidRepositoryError):
        validate_owner(owner)


@pytest.mark.parametrize(
    "repo",
    ["", ".", "..", "hello/world", "hello\\world", "a" * 101],
)
def test_invalid_repo_name(repo: str) -> None:
    with pytest.raises(InvalidRepositoryError):
        validate_repo_name(repo)


def test_parse_repo_ref_requires_single_slash() -> None:
    with pytest.raises(InvalidRepositoryError):
        parse_repo_ref("onlyowner")
    with pytest.raises(InvalidRepositoryError):
        parse_repo_ref("a/b/c")


def test_valid_paths_and_refs() -> None:
    assert validate_repo_path("README.md") == "README.md"
    assert validate_repo_path("src/repopilot/client.py") == "src/repopilot/client.py"
    assert validate_repo_path("", allow_empty=True) == ""
    assert validate_git_ref(None) is None
    assert validate_git_ref("feature/mcp-tools") == "feature/mcp-tools"


@pytest.mark.parametrize(
    "path",
    ["../secrets", "/etc/passwd", "..", ".", "C:\\Windows", "foo/../bar", ""],
)
def test_invalid_paths(path: str) -> None:
    with pytest.raises(InvalidPathError):
        validate_repo_path(path)
