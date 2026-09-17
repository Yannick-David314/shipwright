#!/usr/bin/env python3
"""
test_deb_package.py --- covers the Debian package the release publishes

Contains:
    _built(): builds the package into a temporary directory
    _field(): reads one control field out of a built package
    test_package_carries_the_launcher(): /usr/bin/ship ships executable
    test_version_matches_the_project(): the package version is the project's
    test_package_depends_on_docker(): apt pulls in a container runtime
    test_launcher_has_no_placeholders_left(): image and state path are filled in
    test_launcher_is_a_valid_shell_script(): the shipped launcher parses
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from agent import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    shutil.which("dpkg-deb") is None, reason="dpkg-deb is only on Debian-like systems"
)


def _built(tmp_path: Path) -> Path:
    """Builds the package into a temporary directory.

    Args:
        tmp_path: Directory the package is written to.

    Returns:
        package: Path of the built .deb.
    """
    built = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts/build_deb.sh"), str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(built.stdout.strip())


def _field(package: Path, name: str) -> str:
    """Reads one control field out of a built package.

    Args:
        package: The built .deb.
        name: Field to read, such as "Version".

    Returns:
        value: The field's value.
    """
    shown = subprocess.run(
        ["dpkg-deb", "--field", str(package), name], check=True, capture_output=True, text=True
    )
    return shown.stdout.strip()


def test_package_carries_the_launcher(tmp_path: Path) -> None:
    """Asserts the package installs /usr/bin/ship, executable by everyone."""
    listing = subprocess.run(
        ["dpkg-deb", "--contents", str(_built(tmp_path))],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    line = next(row for row in listing.splitlines() if row.endswith("./usr/bin/ship"))
    assert line.startswith("-rwxr-xr-x")


def test_version_matches_the_project(tmp_path: Path) -> None:
    """Asserts the package version is the one in agent/__init__.py."""
    package = _built(tmp_path)

    assert _field(package, "Version") == __version__
    assert package.name == f"shipwright_{__version__}_all.deb"


def test_package_depends_on_docker(tmp_path: Path) -> None:
    """Asserts apt installs a container runtime along with shipwright."""
    depends = _field(_built(tmp_path), "Depends")

    assert "docker.io" in depends


def test_launcher_has_no_placeholders_left(tmp_path: Path) -> None:
    """Asserts the shipped launcher names a real image and state directory."""
    package = _built(tmp_path)
    subprocess.run(["dpkg-deb", "--extract", str(package), str(tmp_path / "root")], check=True)
    launcher = (tmp_path / "root/usr/bin/ship").read_text()

    assert "@IMAGE_NAME@" not in launcher
    assert "@STATE_DIR@" not in launcher
    assert f"ghcr.io/abj360/shipwright:{__version__}" in launcher
    assert "$HOME/.local/share/shipwright/state" in launcher


def test_launcher_is_a_valid_shell_script(tmp_path: Path) -> None:
    """Asserts the launcher the package installs parses as POSIX shell."""
    package = _built(tmp_path)
    subprocess.run(["dpkg-deb", "--extract", str(package), str(tmp_path / "root")], check=True)

    subprocess.run(["sh", "-n", str(tmp_path / "root/usr/bin/ship")], check=True)
