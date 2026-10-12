# ADR 0025: Sandboxing options of the check service

- Status: Accepted
- Date: 2026-10-13

## Context

The check runs as root, because smartctl needs raw device access and the notification configuration is readable by root only ([ARCHITECTURE.md](../../ARCHITECTURE.md) section 14).
systemd can take away from such a service what it does not need. [ADR 0006](0006-scheduling.md) and Q-P1 left open which options are safe: options that block privilege changes are known to break mail submission on some setups, and the notification targets run inside the bridge process, so whatever they need, the service must allow.

What a run needs:

- Raw access to the drives under `/dev`, and reading `/sys` and `/proc`.
- Writing its own state directory and runtime directory.
- Starting smartctl, lsblk, the Perl bridge and `/usr/sbin/sendmail`; through the bridge, the notification library reads `/etc/pve` and reaches SMTP, Gotify and webhook targets over the network.

## Options considered

1. **No sandboxing.** Nothing can break, nothing is protected.
2. **A strict profile**: `ProtectSystem=strict`, `PrivateDevices=yes`, a system call filter. `PrivateDevices` hides the drives from smartctl. `ProtectSystem=strict` makes every path read-only that is not listed, including the mail queue of whatever mail system the host uses, which the tool cannot know.
3. **The options that a test on a real host showed harmless**, and none that hides devices or makes the mail queue read-only.

## Decision

Option 3. `pve-smart-alert.service` sets:

`PrivateTmp`, `ProtectSystem=full`, `ProtectHome=read-only`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectKernelLogs`, `ProtectControlGroups`, `ProtectClock`, `ProtectHostname`, `RestrictRealtime`, `RestrictSUIDSGID`, `LockPersonality`, `RestrictNamespaces`, `SystemCallArchitectures=native`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK`, and `NoNewPrivileges`.

Evidence, on the standalone host `pve1` (Proxmox VE 9.2.3, systemd 257, Postfix, 2026-10-13): with all of these options, through `systemd-run` with the same properties, a test notification through the notify bridge reached the target `mail-to-root`, a test notification through the mail transport was taken by Postfix and delivered to `proxmox-mail-forward`, and a check read the drive through smartctl. `NoNewPrivileges` was tested on its own as well, because it is the option known to break mail submission: as root, `sendmail` needs no setgid program to hand over the mail, and it worked. The installed service ran with the options afterwards.

Not set:

- `PrivateDevices`, `DevicePolicy`: smartctl needs the drives.
- `ProtectSystem=strict`, `ReadWritePaths`: the mail queue differs between mail systems.
- `SystemCallFilter`, `MemoryDenyWriteExecute`, `CapabilityBoundingSet`: not tested; a mistake would break a run silently on hardware the project cannot test.
- Any option on `pve-smart-alert-failure.service`: the last-resort path stays as plain as possible.

## Consequences

- A fault in the tool cannot write to `/usr`, `/boot`, `/etc` or the home directories, load kernel modules, or change kernel settings or the clock.
- Targets of the notification system that need another address family than IP, Unix sockets or netlink would fail. None of the targets of Proxmox VE 9.2 does.
- Controllers behind which smartctl creates a device node in `/dev` (MegaRAID) are not affected, because `/dev` stays writable. This is still to be confirmed with recordings in milestone M6.

## Revisit when

- A user reports mail or a notification target failing only under the timer.
- Milestone M6 brings controllers whose access differs from that of the drives tested here.
- A system call filter is wanted; it needs its own test on real hardware.
