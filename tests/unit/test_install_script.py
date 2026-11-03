# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for scripts/install.sh, the one-command installation (ADR 0013).

wget, apt, dpkg-query, dpkg-deb and id are replaced by programs of the test in
PATH: wget copies from a directory that plays the release, apt records what it
was asked to install and puts the package in place the way apt does, only when
the state differs, dpkg-query answers the exact format the script asks for or
fails for a package it does not know, dpkg-deb answers what the package file
says, and id answers as root or not.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install.sh"

PACKAGE = "pve-smart-alert"

# The one format the script may ask dpkg-query for. A fake that accepted any
# field name would let a changed separator or a dropped field through.
STATE_FORMAT = "--showformat=${db:Status-Status} ${Version}"
# In the generated fake the dollar signs must not be expanded by the
# shell that runs it, so they are escaped there.
STATE_FORMAT_IN_FAKE = STATE_FORMAT.replace("$", "\\$")


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
        self.dpkg_state = tmp_path / "dpkg-state"
        self.package_version = "0.5.2"
        self._program(
            "wget",
            f'url=""; out=""\nwhile [ $# -gt 0 ]; do case "$1" in -O) out="$2"; shift;; -q) ;;'
            f' *) url="$1";; esac; shift; done\necho "$url" >> "{self.fetched}"\n'
            f'cp "{self.assets}/$(basename "$url")" "$out"',
        )
        self.package_carries()
        self._program(
            "dpkg-query",
            # A real dpkg-query answers the field that --showformat names and
            # fails for a package it does not know. Only the format that the
            # script is meant to ask for is answered, so that a changed format
            # fails here instead of passing on a host.
            f'[ "$1" = "--show" ] || exit 2\n'
            f'[ "$2" = "{STATE_FORMAT_IN_FAKE}" ] || exit 2\n'
            f'[ "$3" = "{PACKAGE}" ] || exit 1\n'
            f'[ -f "{self.dpkg_state}" ] || exit 1\n'
            f'cat "{self.dpkg_state}"',
        )
        self._program("id", 'echo "$UID_OF_TEST"')

    def package_carries(self, *, name: str = PACKAGE, version: str | None = None) -> None:
        """Set what the package file says and what apt installs from it."""
        if version is not None:
            self.package_version = version
        self._program(
            "dpkg-deb",
            # The file argument matters: reading the fields out of SHA256SUMS
            # must not pass for reading them out of the package.
            'case "$2" in *SHA256SUMS*) exit 2 ;; esac\n'
            f'[ "$1" = "-f" ] || exit 2\n'
            'case "$3" in\n'
            f'Package) echo "{name}" ;;\n'
            f'Version) echo "{self.package_version}" ;;\n'
            "*) exit 2 ;;\n"
            "esac",
        )
        self._write_apt()

    def package_is_not_a_deb(self) -> None:
        """Make dpkg-deb refuse the downloaded file the way it does for a non-deb."""
        self._program("dpkg-deb", 'echo "dpkg-deb: error" >&2\nexit 2')

    def _write_apt(self) -> None:
        """Write the fake apt: install the package only when its state differs."""
        wanted = f"installed {self.package_version}"
        self._program(
            "apt",
            f'echo "$@" >> "{self.installed}"\n'
            f'cp "$3" "{self.installed}.deb"\n'
            f'[ "$(cat "{self.dpkg_state}" 2>/dev/null || true)" = "{wanted}" ] && exit 0\n'
            f'printf "%s\\n" "{wanted}" > "{self.dpkg_state}"',
        )

    def apt_fails(self) -> None:
        """Make apt fail the way it does when the package cannot be installed."""
        self._program("apt", 'echo "apt: error" >&2\nexit 100')

    def apt_fails_leaving(self, state: str) -> None:
        """Make apt fail after it put the package into a dpkg state."""
        self._program("apt", f'printf "%s\\n" "{state}" > "{self.dpkg_state}"\nexit 100')

    def apt_succeeds_leaving(self, state: str) -> None:
        """Make apt report success although the package is in a broken state."""
        self._program("apt", f'printf "%s\\n" "{state}" > "{self.dpkg_state}"\nexit 0')

    def apt_does_nothing(self) -> None:
        """Make apt report success without touching dpkg, as a broken call would."""
        self._program("apt", "exit 0")

    def installed_at(self, state: str) -> None:
        """Put the package into a dpkg state before the script runs."""
        self.dpkg_state.write_text(state, encoding="utf-8")

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
    assert "installed 0.5.2; see: pve-smart-alert status" in result.stdout


def test_a_version_can_be_pinned(release: Release) -> None:
    release.package_carries(version="0.5.0")
    release.publish("pve-smart-alert_0.5.0_all.deb", b"old package")

    result = release.run(PVE_SMART_ALERT_VERSION="0.5.0")

    assert result.returncode == 0, result.stderr
    assert release.fetched.read_text(encoding="utf-8").splitlines()[0] == (
        "https://github.com/florianpunz/pve-smart-alert/releases/download/v0.5.0/"
        "pve-smart-alert_0.5.0_all.deb"
    )
    # The message names the version that dpkg holds, so the fake apt and the
    # fake dpkg-deb must agree on it.
    assert "installed 0.5.0; see: pve-smart-alert status" in result.stdout


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


def test_a_checksum_of_a_similarly_named_file_does_not_count(
    release: Release,
) -> None:
    """A version carries dots, so the name is matched literally, not as a pattern."""
    (release.assets / "pve-smart-alert.deb").write_bytes(b"package")
    release.publish("pve-smart-alertXdeb", b"package")

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


def test_a_first_installation_names_what_dpkg_holds(release: Release) -> None:
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert "installed 0.5.2; see: pve-smart-alert status" in result.stdout


def test_nothing_is_announced_as_installed_when_apt_installed_nothing(
    release: Release,
) -> None:
    """apt says "already the newest version" and the script said "installed"."""
    release.installed_at("installed 0.5.2")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert "0.5.2 is installed already, nothing changed" in result.stdout
    assert "installed 0.5.2" not in result.stdout
    # apt was asked all the same; the script only reports what became of it.
    assert release.installed.exists()


def test_a_change_names_both_versions(release: Release) -> None:
    """An upgrade restarts the timer and starts no run (ARCHITECTURE.md, Q-P2)."""
    release.installed_at("installed 0.5.1")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert "changed from 0.5.1 to 0.5.2; see: pve-smart-alert status" in result.stdout


def test_a_removed_package_is_installed_again_not_reported_as_unchanged(
    release: Release,
) -> None:
    """dpkg names a version for a package that is removed but not purged."""
    release.installed_at("config-files 0.5.2")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert "installed 0.5.2 again; see: pve-smart-alert status" in result.stdout
    assert "installed already" not in result.stdout


def test_a_removed_package_of_another_version_is_installed_in_place(
    release: Release,
) -> None:
    release.installed_at("config-files 0.5.1")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 0, result.stderr
    assert "installed 0.5.2 in place of 0.5.1" in result.stdout


def test_a_failing_apt_stops_the_script_with_a_line(release: Release) -> None:
    release.apt_fails()
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "apt did not finish" in result.stderr
    # No state was left behind, so there is nothing to repair yet.
    assert "apt --fix-broken install" not in result.stderr


def test_a_package_that_dpkg_does_not_know_after_apt_is_an_error(
    release: Release,
) -> None:
    """apt reports success and dpkg has nothing: the script must not claim success."""
    release.publish("pve-smart-alert.deb", b"package")
    release.apt_does_nothing()

    result = release.run()

    assert result.returncode == 1
    assert "dpkg does not know the package" in result.stderr


def test_a_package_in_a_broken_state_after_apt_is_an_error(
    release: Release,
) -> None:
    """apt can exit 0 and leave the package half-configured."""
    release.publish("pve-smart-alert.deb", b"package")
    release.apt_succeeds_leaving("half-configured 0.5.2")

    result = release.run()

    assert result.returncode == 1
    assert "reports the package as half-configured after apt reported success" in (result.stderr)


def test_a_package_that_says_another_name_is_refused(release: Release) -> None:
    """A mirror can serve any package under the name the script asks for."""
    release.package_carries(name="something-else")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "carries the package something-else" in result.stderr
    assert not release.installed.exists()


def test_a_file_that_is_not_a_debian_package_is_refused(release: Release) -> None:
    release.package_is_not_a_deb()
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "is not a Debian package" in result.stderr
    assert not release.installed.exists()


def test_a_pinned_version_must_be_the_version_in_the_package(
    release: Release,
) -> None:
    release.package_carries(version="0.5.2")
    release.publish("pve-smart-alert_0.5.0_all.deb", b"package")

    result = release.run(PVE_SMART_ALERT_VERSION="0.5.0")

    assert result.returncode == 1
    assert "carries the version 0.5.2, not 0.5.0" in result.stderr
    assert not release.installed.exists()


def test_a_failure_over_a_removed_package_does_not_suggest_a_repair(
    release: Release,
) -> None:
    """config-files is not broken, it is removed; --fix-broken does not install it."""
    release.apt_fails_leaving("config-files 0.5.2")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "dpkg reports the package as config-files" in result.stderr
    assert "the package is not installed" in result.stderr
    assert "apt --fix-broken install" not in result.stderr


def test_a_failure_after_a_partial_install_names_the_state(
    release: Release,
) -> None:
    """apt can fail after it unpacked the package; that is not "not installed"."""
    release.apt_fails_leaving("half-configured 0.5.2")
    release.publish("pve-smart-alert.deb", b"package")

    result = release.run()

    assert result.returncode == 1
    assert "apt did not finish" in result.stderr
    assert "dpkg reports the package as half-configured" in result.stderr
    assert "apt --fix-broken install" in result.stderr
