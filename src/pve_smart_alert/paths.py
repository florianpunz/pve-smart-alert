# SPDX-License-Identifier: AGPL-3.0-or-later
"""The paths the tool uses on an installed host.

The table of installed files is in ARCHITECTURE.md section 12. These
constants exist so that the transports, the self-diagnosis and the tests name
the same paths, and so that every path is injectable where it is used
(ADR 0014).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# The Perl bridge, the only code that touches Proxmox VE internals (ADR 0008).
BRIDGE_PATH: Final = Path("/usr/libexec/pve-smart-alert/notify-bridge")

# The mail command of the host, used as the fallback transport (ADR 0008).
SENDMAIL_PATH: Final = Path("/usr/sbin/sendmail")

# Where the two pass-through templates are installed. Their names are the
# template name with the suffix of the notification system (ADR 0008).
TEMPLATE_DIR: Final = Path("/usr/share/pve-manager/templates/default")
SUBJECT_TEMPLATE: Final = TEMPLATE_DIR / "pve-smart-alert-subject.txt.hbs"
BODY_TEMPLATE: Final = TEMPLATE_DIR / "pve-smart-alert-body.txt.hbs"

# The directory administrators can override the templates in. The tool only
# ever reads it (ADR 0012, ADR 0008).
TEMPLATE_OVERRIDE_DIR: Final = Path("/etc/pve/notification-templates/default")

CONFIG_PATH: Final = Path("/etc/pve-smart-alert/config.toml")
