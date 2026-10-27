from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from repopilot.mcp_service import tools
from repopilot.mcp_service.server import create_mcp_server

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_get_repository_info_tool(httpx_mock: HTTPXMock, hello_world_payload: dict) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    result = tools.get_repository_info("octocat", "Hello-World")
    assert result["ok"] is True
    assert result["data"]["full_name"] == "octocat/Hello-World"
    assert result["data"]["html_url"].startswith("https://github.com/")


def test_get_repository_info_invalid_owner() -> None:
    result = tools.get_repository_info("../etc", "passwd")
    assert result["ok"] is False
    assert result["error_type"] == "InvalidRepositoryError"


def test_get_repository_info_missing(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/missing",
        status_code=404,
        json={"message": "Not Found"},
    )
    result = tools.get_repository_info("octocat", "missing")
    assert result["ok"] is False
    assert result["error_type"] == "RepositoryNotFoundError"


def test_list_and_get_file_tools(httpx_mock: HTTPXMock, hello_world_payload: dict) -> None:
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
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World/contents/README",
        json=_load("readme_hello_world.json"),
    )
    listing = tools.list_repository_files("octocat", "Hello-World")
    file_result = tools.get_file_contents("octocat", "Hello-World", "README")
    assert listing["ok"] is True
    assert "README" in [item["path"] for item in listing["data"]["files"]]
    assert file_result["ok"] is True
    assert file_result["data"]["content"] == "# Hello World\n"
    assert file_result["data"]["untrusted_source"] is True


@pytest.mark.anyio
async def test_mcp_server_lists_and_invokes_tools(
    httpx_mock: HTTPXMock,
    hello_world_payload: dict,
) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.github.com/repos/octocat/Hello-World",
        json=hello_world_payload,
    )
    server = create_mcp_server()
    listed = await server.list_tools()
    names = sorted(tool.name for tool in listed)
    assert names == ["get_file_contents", "get_repository_info", "list_repository_files"]
    result = await server.call_tool("get_repository_info", {"owner": "octocat", "repo": "Hello-World"})
    payload = _tool_payload(result)
    assert payload["ok"] is True
    assert payload["data"]["full_name"] == "octocat/Hello-World"


def _tool_payload(result: object) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple) and result:
        content = result[0]
        if isinstance(content, list) and content:
            first = content[0]
            text = getattr(first, "text", None)
            if text:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
        if isinstance(content, dict):
            return content
    structured = getattr(result, "structuredContent", None) or getattr(result, "data", None)
    if isinstance(structured, dict):
        return structured
    raise AssertionError(f"Unexpected MCP tool result shape: {result!r}")
