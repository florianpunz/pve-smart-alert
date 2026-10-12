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

# Every key of the configuration with its default, shipped with the
# documentation (ADR 0011).
REFERENCE_PATH: Final = Path("/usr/share/doc/pve-smart-alert/config.reference.toml")

# The state directory of the tool, and in it the last configuration that
# passed validation (ADR 0007, ADR 0011).
STATE_DIR: Final = Path("/var/lib/pve-smart-alert")
LAST_GOOD_CONFIG_PATH: Final = STATE_DIR / "last-good-config.json"
# What the tool remembers between runs (ADR 0007).
STATE_PATH: Final = STATE_DIR / "state.json"

# The corosync configuration of a cluster, on pmxcfs. A notification names
# the cluster from it; the tool only reads it (ADR 0012).
COROSYNC_CONF_PATH: Final = Path("/etc/pve/corosync.conf")

# The runtime directory, and in it the lock that keeps two runs from
# overlapping (ADR 0007, FR-605).
RUN_DIR: Final = Path("/run/pve-smart-alert")
LOCK_PATH: Final = RUN_DIR / "lock"

# smartctl of the package smartmontools, the default of `smartctl.path`
# (ADR 0004). The key exists so that tests and acceptance runs can use the
# fake smartctl instead (ADR 0016).
SMARTCTL_PATH: Final = Path("/usr/sbin/smartctl")

# What discovery reads besides smartctl, best effort (ADR 0005): the block
# devices from lsblk of util-linux, the links udev keeps below /dev/disk, and
# the transport of NVMe controllers in sysfs.
LSBLK_PATH: Final = Path("/usr/bin/lsblk")
DISK_LINKS_DIR: Final = Path("/dev/disk")
SYSFS_DIR: Final = Path("/sys")

# The command line client of the Proxmox VE API, part of `pve-manager`. The
# routing check reads the matchers and targets through it (ADR 0020).
PVESH_PATH: Final = Path("/usr/bin/pvesh")

# systemd, which runs the timer of the tool (ADR 0006), and the version
# command of Proxmox VE, part of `pve-manager` (ADR 0002). The self-diagnosis
# only asks them.
SYSTEMCTL_PATH: Final = Path("/usr/bin/systemctl")
PVEVERSION_PATH: Final = Path("/usr/bin/pveversion")

# The configuration of smartd, owned by `smartmontools`. The self-diagnosis
# reads it to say whether smartd mails root; the tool never changes it
# (ADR 0012).
SMARTD_CONF_PATH: Final = Path("/etc/smartd.conf")

# Where the mail system looks for the forwarding of mail to root. The package
# `proxmox-mail-forward` pipes it to its program from here; the tool only
# reads the file (ADR 0012, ADR 0022).
ROOT_FORWARD_PATH: Final = Path("/root/.forward")
