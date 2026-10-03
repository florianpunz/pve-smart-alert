# ADR 0011: Configuration in a single TOML file

- Status: Accepted
- Date: 2026-10-03

## Context

The tool must work without any configuration and allow the defaults to be overridden: thresholds, policy intervals, excluded drives, per-drive exceptions, manual device entries.
The file is edited by hand by administrators and is likely to be templated by configuration management.
A mistake in it must not switch monitoring off silently.

## Options considered

| Format | Parser on the host | Comments | Types and nesting | Notes |
| --- | --- | --- | --- | --- |
| INI (`configparser`) | Standard library | Yes | Strings only, flat | Per-drive overrides and nested thresholds become awkward |
| JSON | Standard library | No | Yes | Not suitable for hand-edited files |
| YAML | Needs PyYAML, a third-party package | Yes | Yes | Rejected by [ADR 0003](0003-implementation-language.md); also error-prone when edited by hand |
| Proxmox VE section config | Would need an own parser | Yes | Limited | Familiar to Proxmox administrators, but it would be an imitation of an internal format |
| Shell-style `KEY=value` file | Trivial | Yes | Strings only | Same limits as INI |
| **TOML** (`tomllib`) | Standard library since Python 3.11 | Yes | Yes, including arrays of tables | Read-only parser, which is all that is needed |

Where the file lives:

- `/etc/pve-smart-alert/` on the node: owned by the tool, handled by dpkg as a configuration file.
- `/etc/pve/` on pmxcfs: would give one configuration for the whole cluster, but the tool does not write to pmxcfs and should not depend on it for its own operation.

## Decision

- Format: **TOML**. File: **`/etc/pve-smart-alert/config.toml`**, mode 0644, owned by root.
- The defaults are built into the program. The file only needs to contain what differs from them.
- The shipped `config.toml` contains only a short header that points to the reference. It rarely changes between releases, so package upgrades do not raise configuration-file prompts for administrators who edited it.
- The full reference, with every key, its default and a short explanation, is shipped as `/usr/share/doc/pve-smart-alert/config.reference.toml` and printed by `pve-smart-alert config show --defaults`. It is generated from the same definitions the program uses.
- Sections:
  - `[smartctl]`: path, timeout, detail level.
  - `[discovery]`: probes on or off, exclude rules, manual device entries.
  - `[notify]`: transport, grouping limit, recovery and first-run switches, reminder intervals, cool-downs.
  - `[checks."<check-id>"]`: `enabled` and the thresholds `notice`, `warning`, `critical` of one check.
  - `[[drive]]`: per-drive overrides. A drive is selected by `serial`, `wwn` or a `model` pattern. An override can exclude the drive, set its smartctl detail level, and override any check.
- Durations are strings with a unit: `"30m"`, `"6h"`, `"7d"`. `"never"` disables an interval.
- Check identifiers and key names are part of the public interface and follow the rule of English-only identifiers.

Validation and failure behavior:

- The whole file is validated before use: unknown keys, wrong types, values out of range and unknown check identifiers are errors with file position and a message that names the key.
- `pve-smart-alert config check` validates without running a check. `pve-smart-alert config show` prints the effective configuration, with the origin of each value (default or file).
- After every successful validation the effective configuration is saved as `last-good-config.json` in the state directory.
- If the file is invalid at run time, the run **continues with the last good configuration**, or with the built-in defaults if there is none, and raises a tool-level warning that names the error ([ADR 0009](0009-notification-policy.md)). A typing mistake therefore neither stops monitoring nor discards the administrator's overrides.

Not in version 1:

- A drop-in directory (`conf.d`).
- A cluster-wide configuration read from pmxcfs.

The loader is written as a list of layers that are merged in order, so that both can be added later without changing the format.

## Consequences

- No parser dependency. TOML requires Python 3.11, which is the language baseline anyway.
- Nested per-drive overrides are expressible and still readable.
- TOML is less familiar to some administrators than INI. The generated reference file is the main documentation and cannot drift from the program.
- On a cluster, each node has its own file. Identical settings on all nodes need configuration management or copying. This is the price of not depending on pmxcfs.
- Strict validation means an unknown key is an error, including keys from a newer version after a downgrade. The last-good mechanism softens this.

## Revisit when

- Users ask for one configuration per cluster.
- Configuration management users ask for a drop-in directory.
