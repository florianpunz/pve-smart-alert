# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test of the launcher that starts the installed tool (ADR 0013).

The launcher is what `pve-smart-alert` is on a host: it sets the path of the
installed package, turns byte code off and hands the command line to the
interpreter. Both tests here need neither an installation nor root — one of
them asks a stand-in interpreter what it was called with, the other runs a
module from a temporary directory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY / "libexec" / "pve-smart-alert"

SH = shutil.which("sh")

requires_sh = pytest.mark.skipif(SH is None, reason="a shell is needed to run the launcher")

# A stand-in for the interpreter: reports how it was called and what it got.
FAKE_INTERPRETER = """\
#!/bin/sh
for argument in "$@"; do
	echo "argument: $argument"
done
echo "pythonpath: $PYTHONPATH"
echo "bytecode: $PYTHONDONTWRITEBYTECODE"
"""

# A package that reports what the launcher handed to it.
FAKE_MAIN = """\
import sys

print("ran:", " ".join(sys.argv[1:]))
"""


def run_launcher(
    directory: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the launcher in a directory and return the finished process."""
    return subprocess.run(
        [str(LAUNCHER), *arguments],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def fake_package(directory: Path) -> Path:
    """Write a package for the launcher to start."""
    package = directory / "pve_smart_alert"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "__main__.py").write_text(FAKE_MAIN, encoding="utf-8")
    return package


@requires_sh
def test_the_interpreter_is_called_with_the_installed_path(tmp_path: Path) -> None:
    interpreters = tmp_path / "bin"
    interpreters.mkdir()
    interpreter = interpreters / "python3"
    interpreter.write_text(FAKE_INTERPRETER, encoding="utf-8")
    interpreter.chmod(0o755)
    environment = dict(os.environ)
    environment["PATH"] = f"{interpreters}{os.pathsep}{environment['PATH']}"

    result = run_launcher(
        tmp_path, "test-notification", "--severity=warning", environment=environment
    )

    assert result.returncode == 0
    assert result.stdout == (
        "argument: -B\n"
        "argument: -m\n"
        "argument: pve_smart_alert\n"
        "argument: test-notification\n"
        "argument: --severity=warning\n"
        "pythonpath: /usr/share/pve-smart-alert\n"
        "bytecode: 1\n"
    )


@requires_sh
def test_the_command_line_reaches_the_module(tmp_path: Path) -> None:
    fake_package(tmp_path)

    result = run_launcher(tmp_path, "doctor", "--severity", "warning")

    assert result.returncode == 0
    assert result.stdout == "ran: doctor --severity warning\n"


@requires_sh
def test_no_byte_code_is_left_behind(tmp_path: Path) -> None:
    # The reason for -B and PYTHONDONTWRITEBYTECODE: /usr belongs to dpkg, and
    # a .pyc file written at run time would belong to no package (ADR 0013).
    fake_package(tmp_path)

    assert run_launcher(tmp_path, "--version").returncode == 0

    assert list(tmp_path.rglob("*.pyc")) == []
    assert list(tmp_path.rglob("__pycache__")) == []
