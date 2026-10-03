# ADR 0016: Test strategy: recorded fixtures and a fake smartctl

- Status: Accepted
- Date: 2026-10-03

## Context

The tool's correctness depends on hardware that nobody can produce on demand: a drive with 17 pending sectors, an NVMe drive with exhausted spare, a SAS disk behind a MegaRAID controller, an HPE controller with an empty bay.
The maintainer's test environment is a Proxmox VE cluster with SATA SSDs and NVMe drives. It has no hardware RAID and no failing drives to test with.
An alerting tool that is wrong in either direction is harmful: silence when a drive fails, or noise that trains people to ignore it.

Useful property of the design: the only input from hardware is the JSON output and exit status of smartctl ([ADR 0004](0004-smartctl-json-as-data-source.md)), and the only output is a call to a transport ([ADR 0008](0008-notification-integration.md)). Both can be replaced in a test.

## Options considered

1. **Manual testing on the real cluster only.** Cannot cover failing drives or RAID controllers at all.
2. **Unit tests with hand-written input.** Fast, but hand-written JSON reflects what the author believes smartctl prints, not what it prints.
3. **Unit tests with recorded smartctl output.** Real data, including the oddities of real firmware.
4. **End-to-end tests with a fake smartctl** that replays recorded output, including scan results, exit codes, delays and failures.
5. **Virtual hardware** (QEMU emulated NVMe and SCSI devices). Emulated devices report clean, synthetic SMART data and no RAID pass-through. Useful for packaging tests, not for health logic.
6. **Fault injection on real drives.** Not possible in a safe way.

## Decision

Tests are layered. Options 3 and 4 carry the weight.

### Layer 1: unit tests

- Parsers: every recorded output is parsed into a snapshot, and the snapshot is compared with an expected result stored next to the fixture.
- Checks: every check has at least one fixture or constructed snapshot that triggers each of its severities and one that does not trigger it.
- Policy: the notification planner is tested as a state machine with an injected clock. Each row of the table in [ADR 0009](0009-notification-policy.md) is a test.
- State: atomic replacement, corruption handling, migration between schema versions.
- Configuration: validation errors, overrides, last-good behavior.
- Rendering: subject and body are compared with golden files.

### Layer 2: scenario tests with a fake smartctl

- `tests/fake-smartctl` is an executable that receives the same arguments as smartctl and answers from a scenario directory: scan output, one file per device and type, exit status, optional delay or hang.
- A scenario is a sequence of host states, for example "healthy, then 3 pending sectors, then 20, then the drive is gone".
- The test runs the real command-line program once per state with a fake clock, a temporary state directory, the fake smartctl and a recording transport, and asserts which notifications were produced.
- Hardware RAID discovery, de-duplication, timeouts, standby and unreadable drives are tested at this layer.

### Layer 3: bridge contract test

- The Perl bridge is run against a stub of `PVE::Notify` that records its arguments. This checks the argument mapping and the error reporting without a Proxmox VE host.

### Layer 4: package tests

- CI builds the Debian package, runs lintian, installs it in a clean Debian container with the Proxmox VE package repository enabled, checks the installed files against the list in [ADR 0013](0013-packaging-and-installation.md), runs `pve-smart-alert doctor`, and purges it again, asserting that nothing is left.

### Layer 5: acceptance on a real cluster

- Each roadmap milestone ends with a short checklist that the maintainer runs on the test cluster.
- To exercise the full path on real hosts without failing drives, the path to smartctl is a configuration key. Pointing it at the fake smartctl with a failure scenario produces real notifications through the real notification system.
- Before every release: installation, upgrade and removal on a current Proxmox VE host, and one test notification per transport.

### Fixtures

- Location: `tests/fixtures/smartctl/<protocol-or-controller>/`. Each fixture is the unmodified JSON apart from anonymization, with a small metadata file: smartmontools version, drive class, controller, the command line used, the origin and the license.
- Sources:
  1. The maintainer's cluster (SATA SSD, NVMe).
  2. Public test data under compatible licenses, such as Scrutiny's (MIT).
  3. Output contributed by users. `pve-smart-alert dump-fixture` records scan and drive output for all or selected drives, replaces serial numbers, WWNs and other identifying values with stable placeholders, and writes an archive that can be attached to an issue.
- No fixture is committed with a real serial number. A test enforces this for known serial number fields.
- Degraded states that no real recording covers are derived from a real recording by changing the specific values. Derived fixtures are marked as such.

### Evidence levels for hardware support

Every controller family in the documentation carries one of these labels:

| Label | Meaning |
| --- | --- |
| Verified on hardware | Tested by the maintainer or a named contributor on a real system |
| Verified by fixtures | Recorded output from a real system passes the scenario tests |
| Experimental | Implemented from documentation; no recorded output yet |
| Not possible | Cannot be supported with smartctl |

### Tooling and gates

- `pytest` for tests, `ruff` for lint and formatting, `mypy` in strict mode, `shellcheck` for shell, `perl -c` and `perlcritic` for the bridge.
- CI runs on every push and pull request with Python 3.11, 3.13 and the newest release.
- A change that adds or alters a check must come with a fixture. A change to notification text must update the golden files.
- Tests need neither root nor network nor a Proxmox VE host.

## Consequences

- Health logic and policy are verified against real output of drives the project has never owned.
- Hardware RAID support can be developed and regression-tested without a controller. Its limit is the quality of the recordings: a fixture proves that recorded output is handled, not that the tool behaves well on that hardware in every situation. The evidence labels keep this honest.
- The same fake smartctl lets the maintainer watch a simulated drive failure travel through the real notification configuration.
- The fixture set needs care: origin, license, anonymization. `SOURCES.md` and the anonymization test are the controls.
- The remaining untested area is the real notification library. The bridge contract test and the acceptance checklist cover it; CI cannot.

## Revisit when

- A contributor offers continuous testing on real RAID hardware.
- Proxmox VE can be run headless in CI well enough to test the real notification path.
