#!/usr/bin/env python3
"""
test_entrypoint.py --- covers the ship console entrypoint and the --tui flag

Contains:
    test_defaults_point_at_the_current_checkout(): no arguments works
    test_repo_argument_is_honoured(): --repo selects the checkout
    test_path_argument_accepts_dot_and_parent(): '.' and '..' resolve from the cwd
    test_path_argument_accepts_relative_and_absolute(): typed paths resolve
    test_path_argument_expands_home(): '~' means the home directory
    test_missing_or_non_directory_path_is_rejected(): bad paths fail at parse time
    test_path_and_repo_disagreeing_is_rejected(): the directory is given once
    test_provider_argument_is_honoured(): --provider selects the backend
    test_unknown_provider_is_rejected(): a bad provider fails at parse time
    test_cli_exposes_a_tui_flag(): shipwright --tui is a real flag
"""

from pathlib import Path

import pytest

from agent.cli import build_parser as build_cli_parser
from tui.__main__ import build_app, build_parser


def test_defaults_point_at_the_current_checkout() -> None:
    """Asserts running ship with no arguments targets the current directory."""
    app = build_app([])

    assert app.repo_path == Path.cwd().resolve()


def test_repo_argument_is_honoured(tmp_path: Path) -> None:
    """Asserts --repo points the interface at the given checkout."""
    app = build_app(["--repo", str(tmp_path)])

    assert app.repo_path == tmp_path.resolve()


def test_path_argument_accepts_dot_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts ship . opens the current directory and ship .. its parent."""
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)

    assert build_app(["."]).repo_path == child.resolve()
    assert build_app([".."]).repo_path == tmp_path.resolve()


def test_path_argument_accepts_relative_and_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asserts relative paths resolve against the cwd and absolute ones stand alone."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "sibling").mkdir()
    monkeypatch.chdir(tmp_path / "a")

    assert build_app(["b"]).repo_path == (tmp_path / "a" / "b").resolve()
    assert build_app(["../sibling"]).repo_path == (tmp_path / "sibling").resolve()
    assert build_app([str(tmp_path / "sibling")]).repo_path == (tmp_path / "sibling").resolve()


def test_path_argument_expands_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Asserts ~ is expanded to the home directory rather than read literally."""
    monkeypatch.setenv("HOME", str(tmp_path))

    assert build_app(["~"]).repo_path == tmp_path.resolve()


def test_missing_or_non_directory_path_is_rejected(tmp_path: Path) -> None:
    """Asserts a path that is missing, or is a file, is refused before the app starts."""
    a_file = tmp_path / "notes.txt"
    a_file.write_text("not a directory")

    with pytest.raises(SystemExit):
        build_app([str(tmp_path / "missing")])
    with pytest.raises(SystemExit):
        build_app([str(a_file)])


def test_path_and_repo_disagreeing_is_rejected(tmp_path: Path) -> None:
    """Asserts giving two different directories is an error, not a silent pick."""
    with pytest.raises(SystemExit):
        build_app([".", "--repo", str(tmp_path)])


def test_provider_argument_is_honoured() -> None:
    """Asserts --provider selects which backend answers the run."""
    app = build_app(["--provider", "openai"])

    assert app.provider == "openai"


def test_unknown_provider_is_rejected() -> None:
    """Asserts an unsupported provider is refused at parse time."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--provider", "mistral"])


def test_cli_exposes_a_tui_flag() -> None:
    """Asserts the main entrypoint still offers --tui alongside its other modes."""
    args = build_cli_parser().parse_args(["--tui"])

    assert args.tui is True
