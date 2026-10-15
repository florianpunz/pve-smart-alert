# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for scripts/install.sh, the one-command installation (ADR 0013).

wget, apt and id are replaced by programs of the test in PATH: wget copies
from a directory that plays the release, apt records what it was asked to
install, id answers as root or not.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"


class Release:
    """A release directory, the fake programs, and a way to run the script."""

    def __init__(self, tmp_path: Path) -> None:
        self.assets = tmp_path / "release"
        self.assets.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.installed = tmp_path / "apt.log"
        self.fetched = tmp_path / "wget.log"
        self.uid = "0"
        self._program(
            "wget",
            f'url=""; out=""\nwhile [ $# -gt 0 ]; do case "$1" in -O) out="$2"; shift;; -q) ;;'
            f' *) url="$1";; esac; shift; done\necho "$url" >> "{self.fetched}"\n'
            f'cp "{self.assets}/$(basename "$url")" "$out"',
        )
        self._program("apt", f'echo "$@" >> "{self.installed}"\ncp "$3" "{self.installed}.deb"')
        self._program("id", 'echo "$UID_OF_TEST"')

    def _program(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def publish(self, name: str, content: bytes, *, checksum: bytes | None = None) -> None:
        (self.assets / name).write_bytes(content)
        digest = hashlib.sha256(checksum if checksum is not None else content).hexdigest()
        with (self.assets / "SHA256SUMS").open("a", encoding="utf-8") as sums:
            sums.write(f"{digest}  {name}\n")

    def run(self, **environment: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "UID_OF_TEST": self.uid,
            **environment,
        }
        for name in ("PVE_SMART_ALERT_VERSION", "PVE_SMART_ALERT_BASE_URL"):
            if name not in environment:
                env.pop(name, None)
        return subprocess.run(
            ["sh", str(SCRIPT)], env=env, capture_output=True, text=True, check=False
        )


@pytest.fixture
def release(tmp_path: Path) -> Release:
    return Release(tmp_path)


def test_the_newest_package_is_verified_and_installed(release: Release) -> None:
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert release.fetched.read_text(encoding="utf-8").splitlines() == [
        "https://github.com/florianpunz/pve-smart-alert/releases/latest/download/pve-smart-alert.deb",
        "https://github.com/florianpunz/pve-smart-alert/releases/latest/download/SHA256SUMS",
    ]
    arguments = release.installed.read_text(encoding="utf-8").split()
    assert arguments[:2] == ["install", "--yes"]
    assert arguments[2].endswith("/pve-smart-alert.deb")
    assert Path(f"{release.installed}.deb").read_bytes() == b"package"


def test_a_version_can_be_pinned(release: Release) -> None:
    release.publish("pve-smart-alert_0.5.0_all.deb", b"old package")

    result = release.run(PVE_SMART_ALERT_VERSION="0.5.0")

    assert result.returncode == 0, result.stderr
    assert release.fetched.read_text(encoding="utf-8").splitlines()[0] == (
        "https://github.com/florianpunz/pve-smart-alert/releases/download/v0.5.0/"
        "pve-smart-alert_0.5.0_all.deb"
    )


def test_a_wrong_checksum_installs_nothing(release: Release) -> None:
    release.publish("pve-smart-alert.deb", b"package", checksum=b"something else")

    result = release.run()

    assert result.returncode == 1
    assert "does not match" in result.stderr
    assert not release.installed.exists()


def test_a_package_without_a_checksum_installs_nothing(release: Release) -> None:
    release.publish("pve-smart-alert_0.5.0_all.deb", b"package")
    (release.assets / "pve-smart-alert.deb").write_bytes(b"package")

    result = release.run()

    assert result.returncode == 1
    assert "no checksum for pve-smart-alert.deb" in result.stderr
    assert not release.installed.exists()


def test_it_needs_root(release: Release) -> None:
    release.uid = "1000"
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "as root" in result.stderr
    assert not release.fetched.exists()


def test_a_version_with_other_characters_is_refused(release: Release) -> None:
    result = release.run(PVE_SMART_ALERT_VERSION="1.0; rm -rf /")

    assert result.returncode == 1
    assert "not a version" in result.stderr


def test_a_mirror_can_replace_the_download_location(release: Release) -> None:
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run(PVE_SMART_ALERT_BASE_URL="https://mirror.example/pve-smart-alert")

    assert result.returncode == 0, result.stderr
    assert release.fetched.read_text(encoding="utf-8").startswith(
        "https://mirror.example/pve-smart-alert/pve-smart-alert.deb"
    )
