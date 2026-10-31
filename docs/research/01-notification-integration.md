# Research 01: Feeding notifications into the Proxmox VE notification system

- Research date: 2026-10-03
- Applies to: Proxmox VE 9.2 (documentation 9.2.13) and the `master` branches of the Proxmox repositories. Statements about Proxmox VE 8 are marked.
- Used by: [ADR 0008](../adr/0008-notification-integration.md), [ADR 0009](../adr/0009-notification-policy.md)

## Summary

There is no supported, stable interface for third-party tools to send a notification with a severity and metadata.
Two routes work in practice:

1. **Mail to the local `root` user.** Documented and recommended by Proxmox staff for external scripts. The message always arrives with severity `unknown` and type `system-mail`, so it cannot be routed by severity or told apart from other system mail.
2. **The Perl module `PVE::Notify`.** The same module Proxmox VE uses internally. It accepts a severity and free metadata fields, but it is an internal interface. Proxmox staff call this use "not really a supported use case and potentially prone to breakage with future updates". Its signature changed once already, in June 2024.

The REST API has no endpoint for sending an arbitrary notification.

## How the notification system is built

All statements in this section are **Verified** unless marked otherwise.

- Configuration is cluster-wide: `/etc/pve/notifications.cfg` and `/etc/pve/priv/notifications.cfg` on pmxcfs.
- Targets: `sendmail`, `smtp`, `gotify`, `webhook`.
- Matchers route notifications to targets. Rule types: `match-field` (`exact:` or `regex:` on a metadata field), `match-severity`, `match-calendar`. A matcher without rules always matches. If a matched field does not exist in the notification, the rule does not match.
- How a matcher decides, **Verified** on 2026-10-06 in `matcher.rs` and `lib.rs` of `proxmox-notify` and in `PVE/Notify.pm` (`master`): `mode`, `all` by default or `any`, combines the rules within each rule type and then the results of the rule types. An `exact:` rule lists values separated by commas, each trimmed; a `regex:` rule matches when the expression is found anywhere in the value. `invert-match` inverts the result, except for a matcher without rules, which always matches. A disabled matcher is skipped. Of the targets a matcher returns, a disabled one is skipped and one that does not exist is logged as an error. Neither `PVE::Notify` nor the library adds a field to the fields of the caller; only a mail forwarded into the notification system gets `type` and `hostname` from the library.
- Severities: `info`, `notice`, `warning`, `error`, `unknown`.
- Built-in notification types and their metadata:

  | Event | `type` | Severity | Fields |
  | --- | --- | --- | --- |
  | Updates available | `package-updates` | `info` | `hostname` |
  | Node fenced | `fencing` | `error` | `hostname` |
  | Replication job failed | `replication` | `error` | `hostname`, `job-id` |
  | Backup succeeded / failed | `vzdump` | `info` / `error` | `hostname`, `job-id` |
  | Mail for root | `system-mail` | `unknown` | `hostname` |

- The built-in default configuration contains a `sendmail` target `mail-to-root` (recipient: the mail address of `root@pam`) and a matcher `default-matcher` without rules that routes everything to it. With an untouched configuration, every notification of any type therefore ends up as mail to the address configured for `root@pam`.
- Webhook targets can use `{{ title }}`, `{{ message }}`, `{{ severity }}`, `{{ timestamp }}`, `{{ fields.<name> }}` and `{{ secrets.<name> }}` in URL, headers and body. Metadata fields are therefore the only structured data a webhook receiver gets.

The implementation is the Rust crate `proxmox-notify` (repository `proxmox`), exposed to Perl as `Proxmox::RS::Notify` (repository `proxmox-perl-rs`) and wrapped by `PVE::Notify` (repository `pve-cluster`, binary package `libpve-notify-perl`).

## Route A: mail to root

**Verified.**

- The package `proxmox-mail-forward` writes `|/usr/libexec/proxmox-mail-forward` into `/root/.forward`. Mail delivered to the local `root` mailbox is piped to this helper.
- The helper reads the mail from standard input, builds a notification with `Notification::new_forwarded_mail`, and sends it through the notification configuration.
- `new_forwarded_mail` hard-codes the metadata: severity `Unknown`, field `type` = `system-mail`, field `hostname` = node name. Nothing in the mail (headers, subject, body) can influence severity or fields.
- Checked again on 2026-10-07 in `src/main.rs` and `debian/proxmox-mail-forward.postinst` of `proxmox-mail-forward` and in `lib.rs` of `proxmox-notify` (`master`): the helper sends into the notification configuration of Proxmox VE only if `/etc/pve` exists. It reads `/etc/pve/notifications.cfg` and `/etc/pve/priv/notifications.cfg`; a file it cannot read counts as empty. The maintainer script appends `|/usr/libexec/proxmox-mail-forward` to `/root/.forward` whenever the package is configured and the line is missing, and removes an older line with `/usr/bin/proxmox-mail-forward`. The metadata of `new_forwarded_mail` is unchanged.
- Whether mail to root reaches the helper at all is decided by the mail system. Postfix delivers mail for a local name to its alias first, then to the destinations in `~/.forward`, then to the mailbox (`local(8)`, Debian 13). An alias for `root` that leads elsewhere therefore bypasses `/root/.forward` and with it the notification system.
- `sendmail` targets forward the original mail unchanged. Other target types receive the subject as title and the first text part as body.
- `pve-manager` depends on `postfix | mail-transport-agent` and on `proxmox-mail-forward`, so the route exists on every Proxmox VE host.

Proxmox staff (Lukas Wagner, 2025-02-25/26, forum thread "Hook custom script into notifications system") recommend this route for custom scripts and confirm that severity-based filtering is not possible for `system-mail` notifications.

Assessment:

| Criterion | Result |
| --- | --- |
| Stability | High. Documented behavior, used by smartd, ZED and cron on every host. |
| Upgrade safety | High. No dependency on Proxmox VE internals. |
| Severity | Not possible. Always `unknown`. |
| Metadata for matchers | Only `type=system-mail` and `hostname`. A matcher cannot distinguish a PVE SMART Alert mail from a smartd, ZED or cron mail. |

## Route B: `PVE::Notify`

**Verified** in the source code; the usage by a third-party tool is **Reported** (forum) and not yet tested by this project.

Current interface (`pve-cluster`, `src/PVE/Notify.pm`):

```perl
PVE::Notify::notify($severity, $template_name, $template_data, $fields, $config);
PVE::Notify::info($template_name, $template_data, $fields, $config);     # also notice, warning, error
PVE::Notify::common_template_data();   # hostname, fqdn, cluster-name
```

- `$severity` is one of `info`, `notice`, `warning`, `error`.
- `$fields` is a hash of metadata fields. This is what `match-field` rules see.
- `$template_data` is arbitrary JSON-like data for the template.
- `$config` is optional; without it the module reads the cluster-wide configuration through pmxcfs. This requires the `pve-cluster` service and root privileges.
- Example of internal use (`pve-manager`, `PVE/API2/APT.pm`): `PVE::Notify::info("package-updates", $template_data, { type => 'package-updates', hostname => ... })`.

Templates:

- The body and subject are rendered from Handlebars files named `<template>-subject.txt.hbs`, `<template>-body.txt.hbs` and optionally `<template>-body.html.hbs`.
- Lookup order: override directory `/etc/pve/notification-templates/default/`, then vendor directory `/usr/share/pve-manager/templates/default/`.
- If no HTML template exists, the plain-text body is escaped and wrapped in `<pre>` for mail targets. Two files are therefore enough.
- If neither location has the template, rendering fails with "failed to render notification template, all template candidates are erroneous or missing".
- Plain-text templates are rendered without escaping.
- A subject template ends with a newline in the files `pve-manager` ships itself, checked against `templates/default/package-updates-subject.txt.hbs` in the `pve-manager` repository. The trailing newline of a template file is therefore not something a caller has to avoid.
- Precedent for a separate package shipping templates into the vendor directory: `pve-ha-manager` installs its `fencing-*.hbs` files into `/usr/share/pve-manager/templates/default/`.

Error behavior:

- `Proxmox::RS::Notify::send` returns an error only if the notification bus cannot be created from the configuration.
- Errors while rendering or delivering to a target are **not returned**. `Bus::send` logs `could not notify via target ...` and continues. A successful delivery is logged as `notified via target ...`.
- The logger of the Perl bindings writes to standard error and to the journal (`proxmox-perl-rs`, `common/src/logger.rs`). Whether these lines can be captured reliably from a helper process is **Assumed** and must be tested (see OPEN-QUESTIONS).

Addition of 2026-10-08: the acceptance run of milestone M1 on 2026-10-04, on the test cluster with Proxmox VE 9.2 ([ROADMAP.md](../../ROADMAP.md)), tested this route with the notify bridge of PVE SMART Alert. It settles the use by a third-party tool, which was only **Reported** above, and the capture of the log lines, which was **Assumed**. **Verified** in that run:

- A separate root process can call `PVE::Notify::notify($severity, $template, $data, $fields)` with these four arguments, without the configuration argument and without further initialization, and the notification is delivered.
- The library writes one line per target to standard error and to the journal, `` notified via target `NAME` `` or `` could not notify via target `NAME`: REASON ``, and the calling process receives these lines on its standard error.
- A missing template makes the call return success and log `failed to render notification template, all template candidates are erroneous or missing`.
- When no matcher matches, the call returns success and logs nothing, exactly as a delivery that logs nothing. [ADR 0020](../adr/0020-routing-check.md) answers this with a check of the routing.
- Seen in the acceptance run of that routing check on 2026-10-07: for a disabled matcher the library logs `skipping disabled matcher 'NAME'` instead of nothing.

Addition of 2026-10-31: the acceptance run of milestone M5 on `pve5`, a node of the test cluster with Proxmox VE 9.2.24 and the build `0.5.0~dev5`, tested this route on a node that had lost quorum: with `corosync` stopped, `pvecm status` reported `Cannot initialize CMAP service`. **Verified** in that run: `pve-smart-alert check` exited 0, and `test-notification --severity warning` was delivered through the bridge by the matcher `pve-smart-alert` to the target `docker-mailserver` and arrived in the inbox, so the notification configuration stays readable without quorum and the bridge needs no fallback. In the same state `pvecm status` printed the cluster name `miloodc` from the corosync configuration. The other half, pmxcfs not running, was measured on `pve1` on 2026-10-18: the fallback handed the message to the mail command, but `proxmox-mail-forward` found no address for `root@pam` without pmxcfs, so it reached no person ([ARCHITECTURE.md](../../ARCHITECTURE.md) section 11, [ROADMAP.md](../../ROADMAP.md) M5). **Not verified**: the tool's own read of `/etc/pve/corosync.conf` and the cluster name in a rendered notification body; the run did not log them (Q-N12).

History, as evidence for the stability risk:

| Date | Change | Effect on callers |
| --- | --- | --- |
| 2023-07-24 | `libpve-notify-perl` package added | First version of the module |
| 2023-11-17 | "adapt to matcher based notification system" | Interface adapted to matchers |
| 2024-06-03 | "use named template instead of passing template strings" | **Breaking**: callers must now pass a template name and ship template files. `libpve-notify-perl` declares `Breaks: pve-manager (<< 8.2.3)` |
| 2025-04-04 | `common_template_data` added | Additive |
| 2025-04-08 | Override directory for templates (`proxmox-notify`, fix for bug 6143) | Additive |

So the interface has been stable in its current form since June 2024, across Proxmox VE 8.2.3 to 9.2, but it has no compatibility promise.

A community member published a working wrapper for this route in February 2026 (same forum thread), with templates in the override directory and the explicit warning that it "may break at any time if package libpve-notify-perl changes".

Assessment:

| Criterion | Result |
| --- | --- |
| Stability | Medium. Internal interface, one breaking change in three years. |
| Upgrade safety | Medium. A change in the module or in the template lookup breaks delivery; rendering failures are only logged. |
| Severity | Yes: `info`, `notice`, `warning`, `error`. |
| Metadata for matchers | Yes: arbitrary fields. See the limitation of the web interface below. |

## Route C: REST API

**Verified.** `PVE/API2/Cluster/Notifications.pm` offers CRUD endpoints for targets and matchers, `matcher-fields`, `matcher-field-values`, and `POST /cluster/notifications/targets/{name}/test`.
There is no endpoint that sends an arbitrary notification through the matchers.
The test endpoint sends a fixed test message to one target and bypasses the matchers, so it is not a substitute.

## What matchers can see of a custom notification

**Verified** in `proxmox-widget-toolkit` (`src/window/NotificationMatcherEdit.js`) and `PVE/API2/Cluster/Notifications.pm`:

- The field selector in the web interface is not editable. It offers only the fields returned by `matcher-fields`, which is a hard-coded list: `type`, `hostname`, `job-id`.
- In "exact" mode the value selector is not editable either. It offers only known values (`package-updates`, `fencing`, `replication`, `vzdump`, `system-mail`, node names, job IDs).
- In "regex" mode the value is a free text field.
- The API handlers carry the comment `TODO: Adapt this API handler once we have a 'notification registry'`.

Consequences:

- A custom notification is matchable in the web interface only through the field `type` (or `hostname`) in regex mode, for example `^pve-smart-alert$`.
- Custom field names such as `serial` can be matched only by editing `/etc/pve/notifications.cfg` or calling the API directly. The server accepts any field name that is a valid identifier (`match-field (exact|regex):<name>=<value>`).
- Custom fields are still useful for webhook targets, which can read every field through `{{ fields.<name> }}`.

## Other routes considered

- **Linking against `proxmox-notify` from an own Rust binary**: full control, but a compile-time dependency on an internal crate and a reimplementation of the Proxmox VE context. Rejected as far too heavy.
- **Delivering directly to SMTP or webhooks**: independent of Proxmox VE, but it bypasses the central notification configuration, which is the point of the project.
- **A hook in smartd (`-M exec`)**: only relevant for forwarding smartd's own findings. See [Research 02](02-builtin-smart-handling.md).

## Outlook

- The Proxmox VE roadmap lists a "Health Checks" framework that covers "RAID/disk state" and shall "integrate health-check results into the notification system". No design or schedule is published. See [Research 02](02-builtin-smart-handling.md).
- The "notification registry" TODO suggests that registering custom notification types might become possible. Nothing is announced.

## Sources

- Proxmox VE Administration Guide, chapter "Notifications" (9.2.13): <https://pve.proxmox.com/pve-docs/chapter-notifications.html>
- `PVE::Notify`: <https://git.proxmox.com/?p=pve-cluster.git;a=blob;f=src/PVE/Notify.pm> and its history <https://git.proxmox.com/?p=pve-cluster.git;a=history;f=src/PVE/Notify.pm>
- `pvecm status`, which reads the corosync configuration through pmxcfs: <https://git.proxmox.com/?p=pve-cluster.git;a=blob;f=src/PVE/CLI/pvecm.pm>
- `libpve-notify-perl` package relations: <https://git.proxmox.com/?p=pve-cluster.git;a=blob;f=debian/control>
- `proxmox-notify`: context <https://git.proxmox.com/?p=proxmox.git;a=blob;f=proxmox-notify/src/context/pve.rs>, renderer <https://git.proxmox.com/?p=proxmox.git;a=blob;f=proxmox-notify/src/renderer/mod.rs>, core <https://git.proxmox.com/?p=proxmox.git;a=blob;f=proxmox-notify/src/lib.rs>, send <https://git.proxmox.com/?p=proxmox.git;a=blob;f=proxmox-notify/src/api/common.rs>, matcher <https://git.proxmox.com/?p=proxmox.git;a=blob;f=proxmox-notify/src/matcher.rs>
- Perl bindings: <https://git.proxmox.com/?p=proxmox-perl-rs.git;a=blob;f=common/src/bindings/notify.rs>, logger <https://git.proxmox.com/?p=proxmox-perl-rs.git;a=blob;f=common/src/logger.rs>
- `proxmox-mail-forward`: <https://git.proxmox.com/?p=proxmox-mail-forward.git;a=blob;f=src/main.rs>, <https://git.proxmox.com/?p=proxmox-mail-forward.git;a=blob;f=debian/proxmox-mail-forward.postinst>
- Notification API: <https://git.proxmox.com/?p=pve-manager.git;a=blob;f=PVE/API2/Cluster/Notifications.pm>
- Postfix local delivery agent, `local(8)`: <https://manpages.debian.org/trixie/postfix/local.8.en.html>
- Internal caller example: <https://git.proxmox.com/?p=pve-manager.git;a=blob;f=PVE/API2/APT.pm>
- Vendor templates: <https://git.proxmox.com/?p=pve-manager.git;a=tree;f=templates/default>
- Templates shipped by another package: <https://git.proxmox.com/?p=pve-ha-manager.git;a=blob;f=src/templates/Makefile>
- Matcher editor: <https://git.proxmox.com/?p=proxmox-widget-toolkit.git;a=blob;f=src/window/NotificationMatcherEdit.js>
- `pve-manager` dependencies: <https://git.proxmox.com/?p=pve-manager.git;a=blob;f=debian/control>
- Forum thread "Hook custom script into notifications system": <https://forum.proxmox.com/threads/hook-custom-script-into-notifications-system.162766/>
- Roadmap: <https://pve.proxmox.com/wiki/Roadmap>
