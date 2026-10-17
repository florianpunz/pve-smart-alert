#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Repository checks that no other tool covers.

Two rules are enforced here.

1. **No AI attribution.** No file names an AI tool as an author, as the
   origin of its content or as a session link (CLAUDE.md, hard rule 4).
   Only the files in ``ATTRIBUTION_EXEMPT`` may quote such a line: the rules
   themselves and the tests of this check, which have to contain an example.
2. **SPDX license identifier.** Every source file carries an
   ``SPDX-License-Identifier`` line among its first lines (ADR 0015, NFR-20).

Which files count as source files is decided by ``SOURCE_SUFFIXES`` and
``SOURCE_NAMES`` below. Add a suffix there when a new file type is introduced,
so that the rule keeps holding for it.

Usage:
    scripts/check_hygiene.py [--root PATH] [--verbose]

Exit status: 0 when the repository is clean, 1 when a rule is broken.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPOSITORY_ROOT: Final = Path(__file__).resolve().parent.parent

# Directory names that never belong to the repository. Used only when git is
# not available and the tree has to be walked by hand.
IGNORED_DIRECTORIES: Final = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)

# Lines are searched one by one, so no pattern has to cross a line break.
ATTRIBUTION_PATTERNS: Final = (
    # A co-author trailer that names an AI tool.
    re.compile(
        r"co-authored-by:.*\b(ai|anthropic|chatgpt|claude|copilot|gemini|gpt|llm|openai)\b",
        re.IGNORECASE,
    ),
    # A "generated with/by ..." line, the usual footer of an AI tool.
    re.compile(
        r"\bgenerated (?:by|with)\b.*"
        r"\b(ai|anthropic|chatgpt|claude|copilot|gemini|gpt|llm|openai)\b",
        re.IGNORECASE,
    ),
    # Session links and vendor mail addresses.
    re.compile(r"\bclaude\.(?:ai|com)\b", re.IGNORECASE),
    re.compile(r"\banthropic\.com\b", re.IGNORECASE),
    # Such as "AI-assisted" or "AI-generated".
    re.compile(r"\bai-(?:assisted|generated|written)\b", re.IGNORECASE),
)

# Files that quote the forbidden patterns on purpose: the rule documents, this
# check, and its tests, which need a sample to detect.
# Nothing else belongs in this list, and a file is never added to it to silence
# a finding about its own content.
ATTRIBUTION_EXEMPT: Final = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
        "scripts/check_hygiene.py",
        "tests/unit/test_check_hygiene.py",
    }
)

# Every source file carries this identifier (ADR 0015). A file under another
# license needs an entry in LICENSE_EXCEPTIONS, next to the notice of the
# project it came from (ADR 0015, THIRD-PARTY-NOTICES.md).
EXPECTED_LICENSE: Final = "AGPL-3.0-or-later"

# Files that carry a different license identifier on purpose, for example
# third-party code. Each entry needs the notice of its origin in
# THIRD-PARTY-NOTICES.md (ADR 0015). Empty on purpose.
LICENSE_EXCEPTIONS: Final[dict[str, str]] = {}

SOURCE_SUFFIXES: Final = frozenset(
    {".8", ".pl", ".pm", ".py", ".service", ".sh", ".timer", ".toml", ".yaml", ".yml"}
)
# Scripts without a suffix: the ones whose installed path keeps the name, and
# the two maintainer scripts of the Debian package.
SOURCE_NAMES: Final = frozenset(
    {
        "Makefile",
        "fake-smartctl",
        "notify-bridge",
        "postrm",
        "pve-smart-alert",
        "report-failure",
        "rules",
    }
)

# The Handlebars templates (`.hbs`) are left out on purpose even though NFR-20
# asks for an identifier in every source file: their content is nothing but the
# two expressions they print, and where they come from and under which license
# they stand is recorded in the copyright file of the package (ADR 0015).
#
# The metadata of the Debian package is left out for the same reason: control,
# changelog, copyright and the install lists are read by the packaging tools,
# and the license of the whole package is stated in debian/copyright.

# A shebang, a coding line and an interpreter hint fit in front of it.
SPDX_SEARCH_LINES: Final = 5
SPDX_PATTERN: Final = re.compile(r"SPDX-License-Identifier:\s*(\S+)")


@dataclass(frozen=True)
class Finding:
    """One broken rule."""

    path: str
    line_number: int
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}: {self.message}"


def list_repository_files(root: Path) -> list[Path]:
    """Return every file of the repository below ``root``.

    Tracked files are what CI checks. Untracked files that are not ignored are
    included as well, so that the check also covers work that is not committed
    yet.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return sorted(_walk(root))

    names = result.stdout.decode("utf-8", errors="replace").split("\0")
    return sorted(root / name for name in names if name)


def _walk(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Compared relative to the root: a checkout below a directory called
        # "build" or "dist" must not be skipped as a whole.
        parts = path.relative_to(root).parts
        if IGNORED_DIRECTORIES.isdisjoint(parts):
            yield path


def read_lines(path: Path) -> list[str] | None:
    """Return the lines of a text file, or ``None`` for anything else."""
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None


def is_source_file(path: Path) -> bool:
    """Return whether the file is expected to carry an SPDX identifier."""
    return path.suffix in SOURCE_SUFFIXES or path.name in SOURCE_NAMES


def check_attribution(relative: str, lines: Sequence[str]) -> list[Finding]:
    """Return the AI attributions found in one file."""
    if relative in ATTRIBUTION_EXEMPT:
        return []

    findings = []
    for line_number, line in enumerate(lines, start=1):
        for pattern in ATTRIBUTION_PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(relative, line_number, f"AI attribution is not allowed: {line.strip()}")
                )
                break
    return findings


def check_license_identifier(relative: str, path: Path, lines: Sequence[str]) -> list[Finding]:
    """Return the missing or unexpected SPDX identifier of one source file."""
    if not is_source_file(path):
        return []

    expected = LICENSE_EXCEPTIONS.get(relative, EXPECTED_LICENSE)
    for line in lines[:SPDX_SEARCH_LINES]:
        match = SPDX_PATTERN.search(line)
        if match is None:
            continue
        if match.group(1) != expected:
            return [
                Finding(
                    relative,
                    1,
                    f"expected the license identifier {expected}, found {match.group(1)}",
                )
            ]
        return []

    return [
        Finding(
            relative,
            1,
            f"missing the SPDX license identifier line ({EXPECTED_LICENSE})",
        )
    ]


def check_root(root: Path) -> list[Finding]:
    """Return every rule violation below ``root``."""
    findings: list[Finding] = []
    for path in list_repository_files(root):
        lines = read_lines(path)
        if lines is None:
            continue
        relative = path.relative_to(root).as_posix()
        findings.extend(check_attribution(relative, lines))
        findings.extend(check_license_identifier(relative, path, lines))
    return findings


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPOSITORY_ROOT,
        help="repository to check (default: the repository this script is in)",
    )
    parser.add_argument("--verbose", action="store_true", help="report what was checked")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the check and return its exit status."""
    arguments = build_parser().parse_args(argv)
    root: Path = arguments.root.resolve()

    findings = check_root(root)
    for finding in findings:
        print(finding)

    if arguments.verbose:
        count = len(list_repository_files(root))
        print(f"checked {count} files below {root}", file=sys.stderr)

    if findings:
        print(f"{len(findings)} findings", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
