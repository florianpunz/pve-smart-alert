# ADR 0020: Check the routing of the notifications through the public API

- Status: Proposed
- Date: 2026-10-04

## Context

The acceptance run of milestone M1 showed a failure that [ADR 0008](0008-notification-integration.md) did not foresee.
On the test cluster the default matcher had been restricted to the types `vzdump` and `system-mail`.
A notification of type `pve-smart-alert` matched no matcher. `PVE::Notify::notify` returned success and logged nothing, exactly as it does for a delivery that logs nothing. `pve-smart-alert test-notification` reported "Delivered: yes".
ADR 0008 states that the test command makes this case visible. It does not, and no check of the tool can tell the two cases apart from the outcome of the call.

For an alerting tool this is the worst failure: every run looks healthy, and no alert ever arrives.
The first run after installation cannot catch it, because nothing is wrong with the tool. It is a property of the routing configuration, which the administrator owns.

What was observed on the test cluster (`pvesh get /cluster/notifications/matchers`, Proxmox VE 9.2): each matcher has `name`, `mode`, `target` (a list), `match-field` (a list of strings such as `exact:type=vzdump,system-mail`), `match-severity` (a list of strings such as `info,notice,warning,error,unknown`) and `origin`. A disabled target has `disable: 1` in `pvesh get /cluster/notifications/targets`.
Assumptions that have not been checked yet: that matchers can also carry `invert-match`, `match-calendar`, `disable` and `comment`, and that `regex:` is the prefix of a regex rule (the web interface offers it).

## Options considered

1. **Documentation only.** The README names the problem. Costs nothing, and nobody reads it before the first missed alert.
2. **Read the matcher configuration in the bridge**, through `PVE::Notify` or by parsing `/etc/pve/notifications.cfg`. Uses an internal interface a second time and needs the bridge to grow a second operation. The file format is not a documented interface.
3. **Ask the public API with `pvesh get /cluster/notifications/matchers` and `.../targets`.** The REST API of Proxmox VE is documented and versioned, and `pvesh` is its supported command line client. The tool only reads.
4. **Check at every run and notify when no matcher matches.** The notification would itself be dropped by the same routing, so it cannot be the primary signal.

## Decision

Use option 3 for `pve-smart-alert doctor` and for `pve-smart-alert test-notification`, together with option 1.

- A new module of the Python side runs `pvesh get /cluster/notifications/matchers --output-format json` and the same for the targets, with a timeout, and evaluates them against the fields of the tool's own notifications (`type` = `pve-smart-alert`) for each severity.
- It evaluates `mode` (`all`, `any`), `match-field` rules (`exact:` and `regex:`), `match-severity`, `invert-match` and `disable`, and it requires that at least one target of the matching matcher is not disabled.
- Rules it cannot evaluate, such as a calendar rule, or fields it does not know, make the result `unknown` and never `ok`. The result is then reported as such and not as a failure.
- Reported by `doctor` as a line `routing`:
  - `ok`: for every severity of the tool, at least one matcher with an enabled target matches. The line names the severities that are not routed, if any.
  - `warn`: no enabled matcher matches one or more severities. The line names the severities and says how to add a matcher (regex `^pve-smart-alert$` on `type`).
  - `skip`: the API cannot be reached, for example without quorum or without `pvesh`. This is not an error.
- `test-notification` runs the same evaluation after sending and prints the matchers that matched, or says that none matched.
- The code does not import Proxmox VE code and calls only a documented command, so the rule "contact with Proxmox VE internals stays in the notify bridge" (ADR 0008) is not touched. The first call of `pvesh` is nevertheless a new dependency on the host, and it is listed under `Depends` or checked by `doctor` like the others.
- The result is a hint. The notification system remains the authority on what is delivered. The documentation says so.

## Consequences

- An administrator with a restricted default matcher sees the problem in `doctor` and in the test command, before the first drive fails.
- The tool contains an evaluation of matcher rules that has to follow changes in Proxmox VE. Unknown rules degrade to `unknown`, not to a wrong `ok`.
- Fixtures: recorded output of `pvesh` from several configurations, anonymized as required by [ADR 0016](0016-test-strategy.md). Tests need neither root nor a Proxmox VE host.
- The questions about `invert-match`, `match-calendar` and the `regex:` prefix are answered with the first recordings and written into `ARCHITECTURE.md`.
- A tool that runs for months without a matcher still cannot warn by itself. Running `doctor` after each Proxmox VE upgrade is the recommendation in the documentation, and the check of the timer in a later milestone can include the routing line.

## Revisit when

- Proxmox VE offers a supported way to ask whether a notification would be delivered, such as a dry-run in the API.
- The matcher model of Proxmox VE changes.
