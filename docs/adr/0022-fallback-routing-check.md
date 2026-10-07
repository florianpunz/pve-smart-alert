# ADR 0022: Check the route of the fallback, mail to root, as well

- Status: Accepted
- Date: 2026-10-07
- Decided by: the maintainer

## Context

[ADR 0020](0020-routing-check.md) checks whether the matchers route the notifications of the tool, the type `pve-smart-alert`.
The tool has a second route. When the notify bridge fails, `transport = auto` sends the same message as mail to root ([ADR 0008](0008-notification-integration.md)), and with `transport = mail` that is the only route.

The mail forwarder of Proxmox VE turns every mail to root into a notification with the type `system-mail`, the field `hostname` and the severity `unknown`, and the same matchers route it ([Research 01](../research/01-notification-integration.md), checked in the source on 2026-10-07).
Configuration B of the test cluster ([Research 06](../research/06-test-cluster-recordings.md)) limits the default matcher to `vzdump`. There, mail to root is dropped as well: with a broken bridge, the tool would fall silent in exactly the situation its fallback exists for (NFR-05). The check of ADR 0020 does not see this, and with `transport = mail` it was skipped.

Mail to root reaches the notification system only through a line in `/root/.forward` that pipes it to `proxmox-mail-forward`. The package of that name writes the line. An alias for `root` in the mail system bypasses the file (Research 01).

## Options considered

1. **Documentation only.** The README names the risk. Nobody reads it before the bridge breaks.
2. **Evaluate the route of mail to root like that of the notifications**, with the evaluation of ADR 0020, as a notification of the type `system-mail` with the severity `unknown`, and check that `/root/.forward` pipes mail to the forwarder.
3. **Send a real mail from `doctor`** and look for it. `doctor` sends nothing, and whether the mail arrived could not be seen from the host anyway.

## Decision

Option 2.

- The routing check evaluates a second notification: the type `system-mail`, the field `hostname` with the node name, the severity `unknown`. All of its fields are known, so a rule on any other field does not match.
- It reads `/root/.forward` and looks for a line that pipes mail to `proxmox-mail-forward`. The file is only read ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)). The aliases of the mail system are not read.
- `pve-smart-alert doctor`:
  - A new line `fallback`, for `transport = auto`: `ok` when a matcher routes mail to root to an enabled target, with the matchers named; `warn` when none does or when `/root/.forward` has no line for the forwarder, with what to do; `skip` when the matchers or the file cannot be read or the routing cannot be decided.
  - With `transport = mail` the line `routing` checks the route of mail to root, which is the route of every notification, instead of being skipped. The line `fallback` is skipped. With `transport = pve-notify` there is no fallback, and the line `fallback` is skipped.
  - The matchers and targets are read once for both lines.
- `pve-smart-alert test-notification` follows a test that went as mail as the notification the forwarder makes of it, names the matchers with "as system-mail", or says that none routes it or that the mail does not reach the notification system.
- For both routes, a matcher whose rules match but that is disabled, or whose targets are all disabled or missing, is named in the advice, instead of the general advice to add a matcher. Enabling it is the fix.
- As in ADR 0020, the result is a hint, and the notification system remains the authority on what is delivered.

## Consequences

- In configuration B, `doctor` warns on both lines, and the advice names the disabled matcher of the tool.
- The check rests on two more facts of Proxmox VE: the metadata the forwarder sets and the line in `/root/.forward`. Both are verified in the source and recorded in Research 01.
- An alias that sends mail for root elsewhere is not seen: `doctor` then reports the route through the notification system, which that mail does not take. Such mail still arrives at the alias.
- Reading `/root/.forward` needs root, like every other check of the tool. Without it the line `fallback` is skipped.

## Revisit when

- The mail forwarder changes the metadata of forwarded mail, or Proxmox VE handles mail to root another way.
- The failure reporter of milestone M5 is built: it mails root as well, also with `transport = pve-notify`.
