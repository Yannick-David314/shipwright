#!/usr/bin/env python3
"""
test_apt_repo.py --- covers the APT repository layout apt installs from

Contains:
    _repo(): builds a repository holding the given packages
    _stanzas(): splits a Packages index into its paragraphs
    test_package_lands_in_the_pool(): the .deb is served from pool/
    test_index_describes_the_package(): name, version, path, size and hash
    test_index_hash_matches_the_file(): apt's integrity check would pass
    test_release_covers_both_indexes(): Release hashes Packages and Packages.gz
    test_rebuilding_keeps_earlier_versions(): an upgrade path needs both
    test_unsigned_when_no_key_is_given(): signing is a release-time step
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from agent import __version__

REPO_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    shutil.which("dpkg-deb") is None, reason="dpkg-deb is only on Debian-like systems"
)


def _repo(tmp_path: Path, packages: list[Path]) -> Path:
    """Builds a repository holding the given packages.

    Args:
        tmp_path: Directory the repository is written under.
        packages: Packages to add.

    Returns:
        repo: Root of the repository.
    """
    repo = tmp_path / "repo"
    subprocess.run(
        ["sh", str(REPO_ROOT / "scripts/build_apt_repo.sh"), str(repo), *map(str, packages)],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


def _built_package(tmp_path: Path) -> Path:
    """Builds the project's package into a temporary directory.

    Args:
        tmp_path: Directory the package is written to.

    Returns:
        package: Path of the built .deb.
    """
    built = subprocess.run(
        ["sh", str(REPO_ROOT / "scripts/build_deb.sh"), str(tmp_path / "dist")],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(built.stdout.strip())


def _stanzas(index: Path) -> list[dict[str, str]]:
    """Splits a Packages index into its paragraphs.

    Args:
        index: The Packages file.

    Returns:
        stanzas: One field mapping per package, continuation lines dropped.
    """
    paragraphs = index.read_text().strip().split("\n\n")
    stanzas: list[dict[str, str]] = []
    for paragraph in paragraphs:
        fields: dict[str, str] = {}
        for line in paragraph.splitlines():
            if line.startswith(" ") or ": " not in line:
                continue
            name, value = line.split(": ", 1)
            fields[name] = value
        stanzas.append(fields)
    return stanzas


def test_package_lands_in_the_pool(tmp_path: Path) -> None:
    """Asserts the package is served from the pool at its versioned name."""
    repo = _repo(tmp_path, [_built_package(tmp_path)])

    pooled = repo / f"pool/main/s/shipwright/shipwright_{__version__}_all.deb"
    assert pooled.is_file()


def test_index_describes_the_package(tmp_path: Path) -> None:
    """Asserts the index names the package, its version, and where to fetch it."""
    repo = _repo(tmp_path, [_built_package(tmp_path)])

    stanza = _stanzas(repo / "dists/stable/main/binary-all/Packages")[0]

    assert stanza["Package"] == "shipwright"
    assert stanza["Version"] == __version__
    assert stanza["Filename"] == f"pool/main/s/shipwright/shipwright_{__version__}_all.deb"


def test_index_hash_matches_the_file(tmp_path: Path) -> None:
    """Asserts the recorded size and hash are the file's own, as apt checks."""
    repo = _repo(tmp_path, [_built_package(tmp_path)])
    stanza = _stanzas(repo / "dists/stable/main/binary-all/Packages")[0]
    pooled = repo / stanza["Filename"]

    assert int(stanza["Size"]) == pooled.stat().st_size
    assert stanza["SHA256"] == hashlib.sha256(pooled.read_bytes()).hexdigest()


def test_release_covers_both_indexes(tmp_path: Path) -> None:
    """Asserts Release hashes both the plain and the compressed index."""
    repo = _repo(tmp_path, [_built_package(tmp_path)])
    release = (repo / "dists/stable/Release").read_text()

    for name in ("main/binary-all/Packages", "main/binary-all/Packages.gz"):
        digest = hashlib.sha256((repo / "dists/stable" / name).read_bytes()).hexdigest()
        assert f" {digest} " in release
        assert release.rstrip().endswith("Packages.gz")


def test_rebuilding_keeps_earlier_versions(tmp_path: Path) -> None:
    """Asserts an added package joins the ones already there, so upgrades work."""
    package = _built_package(tmp_path)
    older = tmp_path / "shipwright_0.9.0_all.deb"
    shutil.copy(package, older)
    repo = _repo(tmp_path, [older])

    subprocess.run(
        ["sh", str(REPO_ROOT / "scripts/build_apt_repo.sh"), str(repo), str(package)],
        check=True,
        capture_output=True,
    )

    pooled = sorted(p.name for p in (repo / "pool/main/s/shipwright").iterdir())
    assert pooled == ["shipwright_0.9.0_all.deb", f"shipwright_{__version__}_all.deb"]


def test_unsigned_when_no_key_is_given(tmp_path: Path) -> None:
    """Asserts signing happens only at release time, when a key is configured."""
    repo = _repo(tmp_path, [_built_package(tmp_path)])

    assert not (repo / "dists/stable/InRelease").exists()
    assert not (repo / "key.gpg").exists()
