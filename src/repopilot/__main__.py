"""CLI entry: python -m repopilot <command>"""

from __future__ import annotations

import argparse
import json
import sys

from repopilot.github.client import GitHubClient
from repopilot.github.errors import GitHubAPIError, InvalidPathError, InvalidRepositoryError
from repopilot.github.validation import parse_repo_ref
from repopilot.logging_setup import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repopilot", description="RepoPilot AI CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    get_repo = sub.add_parser("get-repo", help="Fetch public repository metadata")
    get_repo.add_argument("ref", help="Repository as owner/repo")

    get_readme = sub.add_parser("get-readme", help="Fetch the repository README")
    get_readme.add_argument("ref", help="Repository as owner/repo")
    get_readme.add_argument("--git-ref", dest="git_ref", default=None, help="Branch, tag, or commit")

    list_files = sub.add_parser("list-files", help="List repository files")
    list_files.add_argument("ref", help="Repository as owner/repo")
    list_files.add_argument("--git-ref", dest="git_ref", default=None, help="Branch, tag, or commit")
    list_files.add_argument("--prefix", default="", help="Optional path prefix")
    list_files.add_argument("--max-files", type=int, default=50)
    list_files.add_argument("--no-recursive", action="store_true")

    get_file = sub.add_parser("get-file", help="Fetch one repository file")
    get_file.add_argument("ref", help="Repository as owner/repo")
    get_file.add_argument("path", help="Repository-relative file path")
    get_file.add_argument("--git-ref", dest="git_ref", default=None, help="Branch, tag, or commit")

    sub.add_parser("mcp", help="Run the MCP server on stdio")

    args = parser.parse_args(argv)
    if args.command == "mcp":
        from repopilot.mcp_service.server import run_mcp_server

        run_mcp_server()
        return 0

    configure_logging()
    try:
        owner, repo = parse_repo_ref(args.ref)
        with GitHubClient() as client:
            if args.command == "get-repo":
                payload = client.get_repository(owner, repo).to_dict()
            elif args.command == "get-readme":
                payload = client.get_readme(owner, repo, ref=args.git_ref).to_dict()
            elif args.command == "list-files":
                payload = client.list_repository_files(
                    owner,
                    repo,
                    ref=args.git_ref,
                    path_prefix=args.prefix,
                    max_files=args.max_files,
                    recursive=not args.no_recursive,
                ).to_dict()
            elif args.command == "get-file":
                payload = client.get_file_contents(owner, repo, args.path, ref=args.git_ref).to_dict()
            else:
                return 2
    except (InvalidRepositoryError, InvalidPathError, GitHubAPIError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
