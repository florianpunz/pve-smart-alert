# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point for ``python -m pve_smart_alert``."""

from __future__ import annotations

from pve_smart_alert.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
