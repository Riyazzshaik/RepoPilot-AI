from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from repopilot.github.client import GitHubClient
from repopilot.github.errors import GitHubRateLimitError, InvalidPathError, PathNotFoundError

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_get_readme_decodes_text(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/readme",
        json=_load("readme_hello_world.json"),
    )
    with GitHubClient(token=None) as client:
        readme = client.get_readme("octocat", "Hello-World")
    assert readme.path == "README"
    assert readme.is_text is True
    assert readme.content == "# Hello World\n"
    assert readme.html_url == "https://github.com/octocat/Hello-World/blob/master/README"
    assert readme.untrusted_source is True


def test_missing_readme(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/readme",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(PathNotFoundError):
            client.get_readme("octocat", "Hello-World")


def test_list_repository_files_recursive_filters_blobs(
    httpx_mock: HTTPXMock,
    hello_world_payload: dict,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/git/trees/master?recursive=1",
        json=_load("git_tree_hello_world.json"),
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_files("octocat", "Hello-World")
    paths = [item.path for item in listing.files]
    assert paths == ["README", "docs/guide.md"]
    assert listing.truncated is False
    assert listing.evidence_url.endswith("/git/trees/master")
    assert listing.files[0].html_url.endswith("/blob/master/README")


def test_list_repository_files_prefix_and_cap(
    httpx_mock: HTTPXMock,
    hello_world_payload: dict,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/git/trees/master?recursive=1",
        json=_load("git_tree_hello_world.json"),
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_files(
            "octocat",
            "Hello-World",
            path_prefix="docs",
            max_files=1,
        )
    assert [item.path for item in listing.files] == ["docs/guide.md"]
    assert listing.truncated is True


def test_list_directory_pagination(httpx_mock: HTTPXMock, hello_world_payload: dict) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    page1 = [
        {
            "name": "README",
            "path": "README",
            "type": "file",
            "size": 14,
            "sha": "a",
            "html_url": "https://github.com/octocat/Hello-World/blob/master/README",
            "url": "https://api.github.com/repos/octocat/Hello-World/contents/README",
        }
    ]
    page2 = [
        {
            "name": "LICENSE",
            "path": "LICENSE",
            "type": "file",
            "size": 10,
            "sha": "b",
            "html_url": "https://github.com/octocat/Hello-World/blob/master/LICENSE",
            "url": "https://api.github.com/repos/octocat/Hello-World/contents/LICENSE",
        }
    ]
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents?ref=master&page=1&per_page=100",
        json=page1,
        headers={
            "Link": '<https://api.github.com/repos/octocat/Hello-World/contents?page=2>; rel="next"',
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents?ref=master&page=2&per_page=100",
        json=page2,
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_files("octocat", "Hello-World", recursive=False)
    assert [item.path for item in listing.files] == ["README", "LICENSE"]


def test_get_file_contents_text(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents/README",
        json=_load("readme_hello_world.json"),
    )
    with GitHubClient(token=None) as client:
        file_content = client.get_file_contents("octocat", "Hello-World", "README")
    assert file_content.content == "# Hello World\n"
    assert file_content.is_text is True


def test_get_file_contents_rejects_directory(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents/docs",
        json=[{"name": "guide.md", "path": "docs/guide.md", "type": "file"}],
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(Exception, match="directory"):
            client.get_file_contents("octocat", "Hello-World", "docs")


def test_get_file_contents_missing(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents/missing.txt",
        status_code=404,
        json={"message": "Not Found"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(PathNotFoundError):
            client.get_file_contents("octocat", "Hello-World", "missing.txt")


def test_get_file_contents_rate_limit(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents/README",
        status_code=429,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1710000000"},
    )
    with GitHubClient(token=None) as client:
        with pytest.raises(GitHubRateLimitError):
            client.get_file_contents("octocat", "Hello-World", "README")


def test_get_file_contents_rejects_path_traversal(httpx_mock: HTTPXMock) -> None:
    with GitHubClient(token=None) as client:
        with pytest.raises(InvalidPathError):
            client.get_file_contents("octocat", "Hello-World", "../secrets.txt")
    assert httpx_mock.get_requests() == []


def test_empty_directory_listing(httpx_mock: HTTPXMock, hello_world_payload: dict) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents?ref=master&page=1&per_page=100",
        json=[],
    )
    with GitHubClient(token=None) as client:
        listing = client.list_repository_files("octocat", "Hello-World", recursive=False)
    assert listing.files == ()
    assert listing.truncated is False
