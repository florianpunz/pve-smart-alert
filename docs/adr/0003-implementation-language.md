# ADR 0003: Python standard library plus a minimal Perl bridge

- Status: Accepted
- Date: 2026-10-03

## Context

The tool has to parse nested JSON from smartctl, keep state between runs, apply a rule set with thresholds and time-based policies, render messages, and hand them to the Proxmox VE notification system.
The criteria set by the maintainer are: dependencies on a fresh Proxmox VE host, maintainability and testability.

What a fresh Proxmox VE 9 host provides (verified in the package dependency declarations, see [Research 01](../research/01-notification-integration.md) and [Research 02](../research/02-builtin-smart-handling.md)):

- **Perl** with the Proxmox VE modules and `libjson-perl`. Proxmox VE itself is written in Perl.
- **Python 3**. It is a hard, transitive dependency: `pve-manager` → `libpve-storage-perl` → `ceph-common` → `python3-rados` and other Python packages. `ifupdown2`, the default network stack, is a Python program as well. Debian 13 ships Python 3.13.
- **Bash** and the usual core utilities. `jq` is not among the dependencies.
- No Go or Rust toolchain, which only matters for building.

The notification interface with severity and metadata is a Perl module ([ADR 0008](0008-notification-integration.md)). Whatever language is chosen, a few lines of Perl are needed to call it.

## Options considered

| Option | Dependencies on the host | Maintainability | Testability |
| --- | --- | --- | --- |
| **Bash with jq** | Needs `jq`, an extra package | Poor for this problem: nested data, state machine and date arithmetic in shell | Poor: bats tests, no types, quoting bugs |
| **Perl** | None. Notification call in-process | Matches the Proxmox VE code base. Small and shrinking contributor base; Perl experience cannot be assumed for future contributors | Adequate (`Test::More`), tooling is dated |
| **Python, standard library only** | None | Good: readable, typed with annotations, large contributor base, strong tooling | Very good: `pytest`, fixtures, time injection, `mypy`, `ruff` |
| **Go** | None at run time (static binary) | Good | Very good. Needs a release pipeline that builds binaries; administrators cannot read or patch the installed tool |
| **Rust** | None at run time | Good, steep for contributors | Very good. Same pipeline cost as Go. Could link `proxmox-notify` directly, but that is an internal crate without a stable interface |

Further points:

- A sysadmin tool that runs as root on a hypervisor benefits from being readable in place. An interpreted tool can be inspected with a pager on the host.
- A pure Python package has architecture `all` and needs no compiler in the release pipeline.
- Go and Rust would still shell out to Perl for the notification call, so they do not remove the second language.
- Python's standard library covers everything needed: `json`, `tomllib` (since 3.11), `subprocess`, `dataclasses`, `fcntl`, `argparse`, `email`, `logging`.

## Decision

- The tool is written in **Python 3, using only the standard library at run time**.
- The call into the notification system is a **separate Perl script of minimal size** (the "notify bridge"), which receives a JSON document on standard input, calls `PVE::Notify`, and reports the result. It contains no logic beyond that.
- Third-party Python packages are allowed only as development tools (`pytest`, `ruff`, `mypy`). Nothing is installed with `pip` on a Proxmox VE host, and no virtual environment is created there.
- The code targets Python 3.11 syntax ([ADR 0002](0002-supported-platforms-and-version-baseline.md)) and is fully type-annotated.
- The installed program does not write byte code next to its sources, so that it leaves no untracked files under `/usr`.

## Consequences

- No additional package is pulled in by installing the tool.
- Two languages in the repository. The Perl part is expected to stay below about 80 lines and has its own contract test.
- A Proxmox VE major upgrade changes the Python minor version. With no compiled extensions and no third-party packages, the remaining risk is deprecated standard library modules; CI runs the tests on the newest Python to catch this early.
- Start-up cost of the interpreter is irrelevant for a job that runs twice an hour.
- If the Python dependency chain of Proxmox VE ever disappeared, the package dependency on `python3` would simply install it. The dependency is declared explicitly and not assumed.

## Revisit when

- Proxmox VE provides a supported command-line or API call for sending notifications. The Perl bridge could then be dropped.
- The standard library turns out to be insufficient for a required feature.
