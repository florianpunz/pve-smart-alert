# ADR 0031: Switch a condition of the tool off, and name the monitored drives in the notice about an unsupported controller

- Status: Accepted
- Date: 2026-10-16
- Extends: [ADR 0009](0009-notification-policy.md), [ADR 0011](0011-configuration.md), [ADR 0030](0030-controllers-whose-drives-cannot-be-queried.md)

## Context

[ADR 0030](0030-controllers-whose-drives-cannot-be-queried.md) reports every SCSI host whose driver is on the list of drivers whose drives cannot be queried. The list holds `mpi3mr`, and its evidence is the RAID personality of smartmontools issue 313. The maintainer decided on 2026-10-16 to keep reporting every `mpi3mr` host in every personality until a recording of such a host exists (Q-R7), and to make the notice more helpful instead of adding a heuristic, because the notice was thin in two ways:

- It named the controller but not what that costs on this host. A host that monitors no drive at all looked the same as one whose remaining drives are fine.
- It offered no way to react when the notice is false. On a host whose `mpi3mr` controller runs in HBA personality, its drives appear in the device scan and are monitored, so the notice claims a limitation that does not apply. The configuration could not switch the condition off: `[checks."<id>"]` accepted only the identifiers of the drive catalog and rejected everything else as an unknown check (FR-405), and a condition of the tool had no key anywhere. The experimental HPE probe of milestone M6, slice 5, needs the same door (FR-103).

The severity of `tool.unsupported_controller` in the check catalog stays notice, as decided.

## Options considered

1. **A section of its own, such as `[tool]`.** A second place for the same idea, a second validator, and a second meaning of `enabled` to explain.
2. **The conditions of the tool in `[checks."<id>"]`, with `enabled` as their only key.** One table, one validator, one meaning of `enabled`, and the identifiers stay the ones of the check catalog and of the notifications ([ADR 0010](0010-health-evaluation-and-default-thresholds.md), NFR-21).
3. **No switch at all**, only the count in the notice. Whoever gets a false notice would still have no way to silence it but installing another tool.

## Decision

Option 2, and the notice names what it means for the host.

- `[checks."<id>"]` accepts the seven identifiers of `TOOL_CONDITIONS` besides the identifiers of the drive catalog. A condition of the tool takes `enabled` and nothing else: its severity is fixed, so a threshold would silently do nothing, and it has no confirmation count and no per-class values. An unknown key remains an error that names it and its line (FR-405). A table that only repeats the default (`enabled = true`) is dropped like on a check of a drive, so that the reference of the configuration changes nothing when it is loaded (ADR 0011).
- A condition of the tool that is switched off is not raised at all, and one that is active in the state is dropped without a recovery, exactly as a check of a drive that is switched off (ADR 0009). Switching it on again raises it as a new problem.
- The per-drive table `[drive.checks."<id>"]` still takes only the checks of a drive. A condition of the tool there is an error that says so, not a setting that is accepted and then ignored: it is about the host, not about one drive.
- The seven identifiers are repeated in `config.py`, which is where the table `[checks]` is validated; `tool_conditions.py` imports that module, so the other direction would be a cycle. A test keeps the two lists in step.
- `pve-smart-alert config show` lists the conditions of the tool after the checks of the drive catalog, each with its enabled state and the origin of that value; `config.reference.toml` documents each of them with `enabled = true`.
- The notice `tool.unsupported_controller` names, after the controller, how many drives this run monitors on the host (`no drive`, `1 drive`, `N drives`), and how it is switched off: `switch this notice off with [checks."tool.unsupported_controller"] enabled = false`. The count is left out when the run could not count, which is the case without smartctl and with a failed device scan, because then it did not look for all drives; each of those situations is a condition of its own.
- The text of a condition of the tool is cut to 1000 characters in a rendered message instead of 200. Reason: the message said less than the condition. The text of one `mpi3mr` host alone is longer than 200 characters, so the old cut removed the end of the sentence. The limit of 200 characters stays for strings that come from a drive; the only untrusted fragment of a tool text is the driver name of a SCSI host, and that is cut to 64 characters where it is read (ADR 0030).

## Consequences

- A host whose only noteworthy fact is such a controller now says how much is monitored with it, and a host in HBA personality, whose drives all appear in the scan, is silenced with three lines of configuration instead of a heuristic that the tool cannot verify.
- The identifiers of the conditions of the tool are configuration keys from now on; NFR-21 applies to them, and a rename would be a breaking change.
- Every condition of the tool can be switched off and on, `tool.smartctl_missing` included. That is the same door for all of them on purpose; a rule that allowed only some of them would need a second list and a second explanation.
- A switched-off condition disappears from the state, so `pve-smart-alert status` no longer shows it, and it is not reported as recovered. Whoever switches a condition off to test something should know that the state forgets it.
- `pve-smart-alert scan` and the line `controllers` of `pve-smart-alert doctor` are unchanged: they name the controller and its driver without the count, because the count belongs to a run, and both commands report one picture of the host rather than what a run made of it.
- The notice is longer. In the metadata of the notification the text of the finding is still cut to 128 characters, because those fields serve matchers and are not meant to be read.
- Q-R7 stays open: the tool still reports every `mpi3mr` host, whatever its personality, and only the text tells the reader what to do about a false notice.

## Revisit when

- A recording of a host with an `mpi3mr` controller in HBA personality answers Q-R7; a heuristic that leaves such a host out then gets its own record.
- A condition of the tool needs something that is not its enabled state, such as a threshold or a confirmation count; the two kinds then have to be told apart in the table `[checks]` again.
