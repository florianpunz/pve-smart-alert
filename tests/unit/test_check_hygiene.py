# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the repository checks in ``scripts/check_hygiene.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPOSITORY_ROOT / "scripts" / "check_hygiene.py"
SPDX_LINE = "# SPDX-License-Identifier: AGPL-3.0-or-later\n"


def run_check(root: Path) -> subprocess.CompletedProcess[str]:
    """Run the check against a directory and return the finished process."""
    return subprocess.run(
        [sys.executable, str(CHECK), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_clean_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text(f"{SPDX_LINE}value = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("No license identifier is needed here.\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""


def test_ai_attribution_is_reported(tmp_path: Path) -> None:
    content = f"{SPDX_LINE}# Co-Authored-By: Claude Code <noreply@anthropic.com>\n"
    (tmp_path / "module.py").write_text(content, encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "module.py:2: AI attribution is not allowed" in result.stdout


def test_a_generated_with_footer_is_reported(tmp_path: Path) -> None:
    content = f"{SPDX_LINE}# Generated with Claude Code\n"
    (tmp_path / "module.py").write_text(content, encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "AI attribution is not allowed" in result.stdout


def test_a_missing_license_identifier_is_reported(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("value = 1\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "missing the SPDX license identifier line" in result.stdout


def test_an_unexpected_license_identifier_is_reported(tmp_path: Path) -> None:
    (tmp_path / "module.py").write_text("# SPDX-License-Identifier: MIT\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 1
    assert "found MIT" in result.stdout


def test_the_rule_documents_may_quote_the_forbidden_patterns(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text('No "Generated with Claude Code" line.\n', encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("See CLAUDE.md, rule 4.\n", encoding="utf-8")

    result = run_check(tmp_path)

    assert result.returncode == 0
