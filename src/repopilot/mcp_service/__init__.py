"""MCP server package. Tool handlers stay thin over the GitHub client."""

from repopilot.mcp_service.server import create_mcp_server, run_mcp_server

__all__ = ["create_mcp_server", "run_mcp_server"]
