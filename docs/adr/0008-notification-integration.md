# ADR 0008: Notifications through `PVE::Notify`, with mail to root as fallback

- Status: Accepted
- Date: 2026-10-03

## Context

The purpose of the project is to deliver drive alerts through the central notification system of Proxmox VE, so that they follow the targets and matchers configured under Datacenter → Notifications.
The maintainer wants to know which route is stable, which survives upgrades, and which can carry a severity and metadata for matchers.

The full analysis is in [Research 01](../research/01-notification-integration.md). In short:

| Route | Severity | Metadata | Status |
| --- | --- | --- | --- |
| A. Mail to local `root`, forwarded by `proxmox-mail-forward` | Always `unknown` | Always `type=system-mail`, `hostname` | Documented, recommended by Proxmox staff for external scripts |
| B. Perl module `PVE::Notify` | `info`, `notice`, `warning`, `error` | Free fields | Internal interface. Stable since June 2024, one breaking change before that. Proxmox staff: "not really a supported use case and potentially prone to breakage with future updates" |
| C. REST API | – | – | No endpoint sends an arbitrary notification |
| D. Own binary linked against the `proxmox-notify` crate | Full | Full | Internal crate, heavy coupling |
| E. Direct delivery to SMTP or webhooks | – | – | Bypasses the central configuration, which defeats the purpose |

No route is both supported and able to carry a severity.

## Options considered

1. **Route A only.** Safe, but drive alerts would be indistinguishable from cron and smartd mail in matchers, and "send errors to the pager, everything else by mail" would be impossible. This removes most of the value over smartd.
2. **Route B only.** Full functionality, but a change inside Proxmox VE could silently stop all drive alerts. For an alerting tool this is the worst failure mode.
3. **Route B with automatic fallback to route A.** Uses the rich route as long as it works and degrades to the safe route when it does not.

## Decision

Use route B as the primary transport and route A as the automatic fallback.

### Transports

The transport is an interface with two implementations and a configuration key `notify.transport`:

| Value | Behavior |
| --- | --- |
| `auto` (default) | Try `pve-notify`. If it fails, send the same message with `mail` in the same run. |
| `pve-notify` | Route B only. A failure is retried on the next run. |
| `mail` | Route A only, for administrators who prefer the supported route over severity. |

### The notify bridge (route B)

- A Perl script, installed as `/usr/libexec/pve-smart-alert/notify-bridge`, is the only code that touches Proxmox VE internals.
- Input on standard input: one JSON document with `severity`, `template`, `data` and `fields`.
- It calls `PVE::Notify::notify($severity, $template, $data, $fields)`, adding the common template data (host name, FQDN, cluster name) if the module provides it.
- Output: a JSON document with `ok` and, on failure, `error`. Exit status 0 on success, non-zero otherwise. Before calling, it checks that the module loads and offers the expected function, so that an incompatible version produces a clear error instead of undefined behavior.
- The Python side runs it with a timeout, because delivery to SMTP or webhook targets happens inside this call.

### Templates

- Template name: `pve-smart-alert`. Two files: `pve-smart-alert-subject.txt.hbs` and `pve-smart-alert-body.txt.hbs`.
- They are pass-through templates: the subject template prints `{{subject}}`, the body template prints `{{body}}`. Subject and body are rendered by the tool itself.
  - The same text is used for both transports.
  - Rendering is covered by the tool's own tests and does not depend on the Handlebars helpers of a particular Proxmox VE version.
- The structured data (drive, findings, values, thresholds) is passed in `data` as well. An administrator can therefore override the templates through the standard override directory `/etc/pve/notification-templates/default/` and build a different layout.
- No HTML template in version 1. Proxmox VE wraps the plain text in `<pre>` for mail targets.
- The files are installed into the vendor directory `/usr/share/pve-manager/templates/default/` by the tool's own package. This is the only place where the notification system looks for templates besides the override directory on pmxcfs. `pve-ha-manager` installs its templates into the same directory, so there is precedent for a second package doing so. The files are owned by the `pve-smart-alert` package and removed with it. No file of another package is changed.

### Severity and metadata

| Internal | Proxmox VE severity |
| --- | --- |
| notice | `notice` |
| warning | `warning` |
| critical | `error` |
| recovery, first-run summary without findings, test | `info` |

Fields on every notification: `type` = `pve-smart-alert`, `hostname` = node name.
Fields on notifications about a single drive, in addition: `event`, `device`, `serial`, `model`.

- `type` is the field to route on. In the web interface it has to be matched in regex mode (`^pve-smart-alert$`), because the exact-match selector only offers the built-in types.
- The other fields cannot be selected in the web interface. They are for webhook bodies (`{{ fields.serial }}`) and for matchers written directly into the configuration file.
- Field values never contain commas, because the exact matcher splits its value list on commas.

### Mail (route A)

- A plain-text message to `root`, handed to `/usr/sbin/sendmail`.
- Because the severity is lost on this route, the subject starts with it: `[pve-smart-alert] WARNING ...`.
- When mail is used as fallback, the body ends with a line saying that the primary transport failed and why.

### When the fallback is used

- The bridge is missing, cannot be started, exits non-zero, or times out.
- The output of the notification library shows that the template could not be rendered.

Delivery errors of individual targets are a different matter. Proxmox VE does not return them to the caller; it logs them. The bridge passes the log output back. If it shows that every matched target failed and none succeeded, the notification counts as not delivered and is planned again on the next run ([ADR 0007](0007-state-storage.md)). If no known log line can be recognized, the handover counts as successful. This feedback is best effort and is the first thing to verify on a real host.

### Self-checks

- `pve-smart-alert test-notification` sends a test message through the configured transport and prints what the notification system logged, so that the administrator sees which targets fired.
- `pve-smart-alert doctor` checks that the bridge loads, that the template files exist, and that the mail command exists.

## Consequences

- With the default Proxmox VE notification configuration (one matcher without rules, one mail target), PVE SMART Alert notifications arrive as mail to the address of `root@pam` without any setup, like every other notification.
- Administrators can route by severity and by `type`.
- The project depends on an internal interface. The dependency is confined to one small file and two template files, it is checked on every run, and its failure degrades to the documented route instead of to silence.
- If no matcher matches, nothing is sent. That is the administrator's routing decision and not an error. The test command makes it visible.
- A failure that the fallback cannot see remains possible: a future change that makes the library accept the call and drop the message without logging. The test command and the release tests on a real host are the mitigation.
- Mail fallback messages arrive with severity `unknown` and may be routed differently from normal PVE SMART Alert notifications.

## Revisit when

- Proxmox VE introduces a supported way to send custom notifications, or the "notification registry" mentioned in its source code.
- The interface of `PVE::Notify` or the template lookup changes.
- The health-check framework on the Proxmox VE roadmap is released.
