# Security policy

## Supported versions

Version 1 is not released yet. Until then only the current state of the `main` branch is supported.
Once version 1 exists, the supported versions are listed here; Proxmox VE 9.x is the supported platform ([ADR 0002](docs/adr/0002-supported-platforms-and-version-baseline.md)).

## Reporting a vulnerability

Report it privately through the **Security** tab of the repository and "Report a vulnerability", which opens a private advisory:
<https://github.com/florianpunz/pve-smart-alert/security/advisories/new>

Please do not open a public issue for a security problem, and do not attach real drive data (serial numbers, WWNs, host names) to a report.

A useful report contains:

- what the problem is and what an attacker can do with it,
- the affected version, commit or package,
- the steps to reproduce it,
- the environment, for example "Proxmox VE 9.2, package 0.5.0", and whether the tool runs as root or as an unprivileged user,
- a suggested fix, if you have one.

## What is in scope

PVE SMART Alert runs as `root` on a hypervisor and reads data that comes from device firmware, which is not trustworthy. The following are security problems in the sense of this policy:

- Running, or causing the tool to run, a command that the administrator did not intend, in particular through a device name, a smartctl type or a configuration value.
- Reading or writing files outside the paths the tool declares in [ARCHITECTURE.md](ARCHITECTURE.md), or following a symbolic link out of them.
- Privilege escalation, or a file or directory created with permissions that are wider than documented.
- A crash or a hang that a device can trigger, for example through a hostile or malformed answer to a smartctl call.
- Escape of identifying data: serial numbers, WWNs or host names reaching a place they should not reach, such as a fixture written by `dump-fixture`.
- Anything that lets an unprivileged local user control what the tool executes or sends.

## What is not in scope

- The thresholds, the notification policy and the wording of messages. A missed or noisy alert is a bug; report it in the issue tracker.
- The absence of a feature, including the checks and controller families listed as out of scope in [ADR 0017](docs/adr/0017-scope-of-version-1.md).
- Vulnerabilities in Proxmox VE, in smartmontools or in the notification targets. Report those to their own projects.
- The Proxmox VE notification system itself, which the tool calls and does not replace.

## How a report is handled

This is a one-person project, so reports are handled as time allows.
You will get an answer that says whether the report is accepted, and if it is, an advisory and a fixed release.
If you want to be named in the advisory, say so; otherwise the report stays anonymous.
