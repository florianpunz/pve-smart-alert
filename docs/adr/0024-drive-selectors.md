# ADR 0024: Select drives by model pattern, serial number and WWN

- Status: Accepted
- Date: 2026-10-07
- Decided by: the maintainer

## Context

The configuration selects drives in two places: the exclude rules of `[discovery]` ([ADR 0005](0005-drive-discovery-and-identity.md), FR-107) and the per-drive overrides of `[[drive]]` ([ADR 0011](0011-configuration.md), FR-403). Both select by `serial`, `wwn` or a `model` pattern, and neither record says what a pattern is.
The selectors are public interface (NFR-21). Their meaning has to be fixed before the first one is read, because changing it later changes which drives an existing configuration selects.

Model names contain spaces, dashes, dots and slashes, such as `Samsung SSD 850 EVO 250GB` or `WDC PC SN720 SDAPNTW-512G-1016`. Hypervisors give their virtual disks fixed names, such as `QEMU HARDDISK`.

## Options considered

1. **Exact names only.** Simple, but one rule per model of a series.
2. **Shell patterns as in `fnmatch`**, with `*`, `?` and `[...]`. Familiar, but square brackets would be read as character classes, which nobody expects in a model name.
3. **Shell patterns with `*` and `?` only.** Familiar, and every other character means itself.
4. **Regular expressions.** Powerful, and easy to get wrong in a file that is edited by hand.

## Decision

Option 3 for the model, exact comparison for serial number and WWN:

- `model` is a pattern. `*` stands for any sequence of characters, also an empty one, `?` for exactly one character, and every other character stands for itself. Upper and lower case count. The pattern has to match the whole model name: `QEMU*` matches `QEMU HARDDISK`, `HARDDISK` does not.
- `serial` is compared with the whole serial number, exactly.
- `wwn` is compared with the whole WWN, exactly. The WWN is written as hexadecimal digits; an optional `0x` in front and the case of the digits do not count, because the tool, `lsblk` and the web interface write the same WWN in different notations.
- A drive is compared by its identity as the tool normalizes it: trimmed, with inner whitespace collapsed ([ADR 0005](0005-drive-discovery-and-identity.md)).
- One rule has exactly one selector. A rule with several selectors is an error for now; combining them with "and" can be added later without changing the meaning of any configuration that is valid today.
- The same syntax applies to the selectors of `[[drive]]` (FR-403) when the per-drive overrides arrive in milestone M3.
- An excluded drive is skipped with the reason `excluded` and shown by `pve-smart-alert scan`. It is still read once per run, because its identity is known only from its own output.

## Consequences

- A series of drives is excluded with one rule, such as `{ model = "QEMU *" }`.
- A model name that contains `*` or `?` cannot be matched literally. No such name is known.
- A rule written for another case of the letters does not match. `pve-smart-alert scan` shows the model exactly as it is compared.

## Revisit when

- Users ask for character classes, alternatives or for combining selectors.
