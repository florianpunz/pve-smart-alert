# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures of every test: the guard against programs of the host (tests/guard.py)."""

from guard import no_host_programs, pytest_configure

__all__ = ["no_host_programs", "pytest_configure"]
