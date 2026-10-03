# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the command-line interface."""

from __future__ import annotations

import subprocess
import sys

import pytest

from pve_smart_alert import __version__
from pve_smart_alert.cli import main


def test_version_option_prints_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"pve-smart-alert {__version__}"


def test_without_arguments_the_help_is_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0

    out = capsys.readouterr().out
    assert "usage:" in out
    assert "--version" in out


def test_module_entry_point_prints_the_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "pve_smart_alert", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == f"pve-smart-alert {__version__}"
