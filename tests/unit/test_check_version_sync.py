# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the repository check in ``scripts/check_version_sync.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPOSITORY_ROOT / "scripts" / "check_version_sync.py"

VERSION_MODULE = Path("src/pve_smart_alert/__init__.py")
CHANGELOG = Path("debian/changelog")

SPDX_LINE = "# SPDX-License-Identifier: AGPL-3.0-or-later\n"
CHANGELOG_TAIL = (
    "\n"
    "  * Initial release.\n"
    "\n"
    " -- Florian Punz <39314759+florianpunz@users.noreply.github.com>  "
    "Sun, 04 Oct 2026 12:05:35 +0000\n"
)


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the check against a directory and return the finished process."""
    return subprocess.run(
        [sys.executable, str(CHECK), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def write_version(root: Path, version: str) -> None:
    """Write the module that holds the version of the program."""
    module = root / VERSION_MODULE
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(f'{SPDX_LINE}__version__ = "{version}"\n', encoding="utf-8")


def write_changelog(root: Path, version: str) -> None:
    """Write a changelog whose newest entry names a version."""
    changelog = root / CHANGELOG
    changelog.parent.mkdir(parents=True, exist_ok=True)
    changelog.write_text(
        f"pve-smart-alert ({version}) unstable; urgency=medium\n{CHANGELOG_TAIL}",
        encoding="utf-8",
    )


def test_the_same_version_in_both_files_passes(tmp_path: Path) -> None:
    write_version(tmp_path, "1.2.3")
    write_changelog(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""


def test_a_different_version_is_reported(tmp_path: Path) -> None:
    write_version(tmp_path, "1.2.3")
    write_changelog(tmp_path, "1.2.4")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "1.2.3" in result.stdout
    assert "1.2.4" in result.stdout


def test_only_the_newest_entry_counts(tmp_path: Path) -> None:
    write_version(tmp_path, "1.2.3")
    write_changelog(tmp_path, "1.2.3")
    # An older entry below the newest one is none of this check's business.
    with (tmp_path / CHANGELOG).open("a", encoding="utf-8") as changelog:
        changelog.write(f"pve-smart-alert (1.2.2) unstable; urgency=medium\n{CHANGELOG_TAIL}")

    assert run_check(tmp_path).returncode == 0


def test_a_module_without_a_version_is_reported(tmp_path: Path) -> None:
    write_version(tmp_path, "1.2.3")
    (tmp_path / VERSION_MODULE).write_text(f"{SPDX_LINE}NAME = 'x'\n", encoding="utf-8")
    write_changelog(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "does not name __version__" in result.stdout


def test_a_missing_changelog_is_reported(tmp_path: Path) -> None:
    write_version(tmp_path, "1.2.3")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "could not be read" in result.stdout


# Pre-releases for test hosts (ADR 0027)


def test_a_pre_release_has_the_debian_form_in_the_changelog(tmp_path: Path) -> None:
    write_version(tmp_path, "0.5.0.dev3")
    write_changelog(tmp_path, "0.5.0~dev3")

    assert run_check(tmp_path).returncode == 0


@pytest.mark.parametrize("package", ["0.5.0.dev3", "0.5.0~dev2", "0.5.0"])
def test_a_pre_release_with_another_package_version_is_reported(
    tmp_path: Path, package: str
) -> None:
    write_version(tmp_path, "0.5.0.dev3")
    write_changelog(tmp_path, package)

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "the package of 0.5.0.dev3 is 0.5.0~dev3" in result.stdout


@pytest.mark.parametrize("version", ["0.5.0~dev3", "0.5.0rc1", "0.5", "0.5.0.dev"])
def test_a_program_version_of_another_form_is_reported(tmp_path: Path, version: str) -> None:
    write_version(tmp_path, version)
    write_changelog(tmp_path, version)

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "neither a release X.Y.Z nor a pre-release X.Y.Z.devN" in result.stdout
