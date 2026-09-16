#!/usr/bin/env python3
"""
__main__.py --- console entrypoint that opens the terminal interface

Contains:
    _permission_mode(): reads --mode, failing at parse time on a typo
    build_parser(): builds the argument parser for the ship command
    resolve_workspace(): turns a typed path into the directory to work on
    provider_choices(): the provider names the entrypoint accepts
    build_app(): builds the application from parsed arguments, loading .env first
    main(): opens the terminal interface and returns its exit status
"""

import argparse
import sys
from pathlib import Path

from agent import __version__
from agent.cost_tracker import CostTracker
from agent.env_file import load_env_file
from agent.llm_client import Provider
from agent.permissions import PermissionMode, parse_mode
from tui.app import DEFAULT_GATEWAY_URL, ShipwrightApp

EXIT_OK = 0


def provider_choices() -> list[str]:
    """Lists the provider names the entrypoint accepts.

    Returns:
        choices: Provider values, matching the ones the CLI accepts.
    """
    return [provider.value for provider in Provider]


def _permission_mode(name: str) -> PermissionMode:
    """Reads --mode, so a typo fails at parse time with the valid names.

    Args:
        name: Mode name or alias as typed.

    Returns:
        mode: The matching permission mode.

    Raises:
        argparse.ArgumentTypeError: The name is not a mode.
    """
    mode = parse_mode(name)
    if mode is None:
        raise argparse.ArgumentTypeError(f"unknown mode {name!r}: use manual, edit, plan or bypass")
    return mode


def build_parser() -> argparse.ArgumentParser:
    """Builds the argument parser for the ship command.

    Returns:
        parser: Configured parser for the terminal interface.
    """
    parser = argparse.ArgumentParser(
        prog="ship",
        description="Open the shipwright terminal interface",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "path",
        nargs="?",
        help="directory to work on: '.', '..', a relative path, or an absolute one "
        "(default: the current directory)",
    )
    parser.add_argument("--repo", help="same as PATH; kept for existing scripts")
    parser.add_argument(
        "--provider",
        choices=provider_choices(),
        # The names are only worth listing where a provider is actually chosen.
        metavar="PROVIDER",
        default=Provider.ANTHROPIC.value,
        help="model provider to run the loop with",
    )
    parser.add_argument(
        "--mode",
        type=_permission_mode,
        default=PermissionMode.MANUAL,
        metavar="MODE",
        help="start in manual (default), edit, plan, or bypass",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="re-run provider and API-key setup, even if a key is already stored",
    )
    parser.add_argument(
        "--gateway",
        default=DEFAULT_GATEWAY_URL,
        help="gateway the connection indicator polls",
    )
    return parser


def resolve_workspace(raw: str) -> Path:
    """Turns a typed path into the absolute directory the agent will work on.

    Relative paths resolve against the directory ship was started in, and a
    leading ~ expands to the home directory, exactly as a shell would.

    Args:
        raw: Path as the operator typed it.

    Returns:
        workspace: Absolute, symlink-resolved directory.

    Raises:
        NotADirectoryError: The path does not exist or is not a directory.
    """
    workspace = Path(raw).expanduser().resolve()
    if not workspace.is_dir():
        raise NotADirectoryError(f"not a directory: {raw}")
    return workspace


def build_app(argv: list[str] | None = None) -> ShipwrightApp:
    """Builds the application from parsed command-line arguments.

    Args:
        argv: Argument vector; defaults to sys.argv when None.

    Returns:
        app: Application pointed at the requested checkout.
    """
    parser = build_parser()
    args: argparse.Namespace = parser.parse_args(argv)
    if args.path is not None and args.repo is not None and args.path != args.repo:
        parser.error("give the directory once, either as PATH or with --repo")
    try:
        workspace = resolve_workspace(args.path or args.repo or ".")
    except NotADirectoryError as exc:
        parser.error(str(exc))
    load_env_file(workspace)
    return ShipwrightApp(
        repo_path=workspace,
        provider=args.provider,
        gateway_url=args.gateway,
        cost_tracker=CostTracker(),
        force_setup=args.setup,
        permission_mode=args.mode,
    )


def main(argv: list[str] | None = None) -> int:
    """Opens the terminal interface and returns its exit status.

    Args:
        argv: Argument vector; defaults to sys.argv when None.

    Returns:
        exit_code: Process exit status.
    """
    build_app(argv).run()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
