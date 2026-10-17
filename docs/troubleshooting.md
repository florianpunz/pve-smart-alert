# Troubleshooting

What to do when PVE SMART Alert does not do what you expect.
Run every command below as root: the state directory, the drives and the notification configuration are readable by root only, and as another user `status` fails, `doctor` skips and warns, and drives look unreadable.
Start with `pve-smart-alert doctor`: it reports one line per part of the host the tool works with, as `ok`, `warn`, `fail` or `skip`, and adds advice below a line where something can be done.
The commands are described in the [README](../README.md#commands) and in the manual page; `man ./man/pve-smart-alert.8` shows its source in the repository.

## No notification arrives

1. Look at the journal of the runs: `journalctl -u pve-smart-alert.service`. A run logs `sent (<transport>): <subject>` for each notification it handed over and `not delivered (<reason>): <subject>` for each it could not, and one summary line. A notification that was sent and did not arrive was dropped or held by the notification system; one that was not delivered is planned again on the next run.
2. Send a test: `pve-smart-alert test-notification --severity warning`. It prints whether the notification was handed over, which transport took it, what the notification system logged, and the line `Matchers`: which matchers route it, or that none routes it to an enabled target.
3. If no matcher routes it, the notification system dropped it without an error. When `doctor` names a matcher or a target that would route it but is disabled, enable it; otherwise add a matcher under Datacenter → Notifications with the field `type` and the regular expression `^pve-smart-alert$`, and route all four severities of the tool to a target ([README](../README.md#notification-routing)). `doctor` reports `routing` as `warn` and names each severity of the tool that reaches no enabled target.
4. If the line `bridge` of `doctor` fails, the tool cannot load the notification library of Proxmox VE; `/usr/libexec/pve-smart-alert/notify-bridge --check` shows the error. With the default `transport = "auto"`, every notification then goes as mail to root instead, where the notification system sees it without the severity of the tool, and each run reports `tool.transport_degraded`; with `transport = "pve-notify"` nothing can be delivered.
5. If the line `fallback` warns, the mail to root that replaces a notification would be dropped as well. It has two causes, and the advice of the line names the one that applies: no matcher routes the type `system-mail` with the severity `unknown`, which is how Proxmox VE routes mail to root, or `/root/.forward` does not hand mail to `proxmox-mail-forward`, which reinstalling that package repairs. With `transport = "pve-notify"` or `"mail"` the line is `skip`.
6. If the line `templates` fails, a template file of the tool is missing from `/usr/share/pve-manager/templates/default`. Reinstalling the package puts it back.
7. If the line `mail` reports that `/usr/sbin/sendmail` is missing, the host has no mail command. With `transport = "mail"` it is the only route and the line fails; with `auto` it is the fallback and the route of the failure mail; with `pve-notify` it is only the route of the failure mail, and the line warns.

## The first-run summary did not come

- `doctor` reports the timer in the line `timer`; when it fails, `systemctl enable --now pve-smart-alert.timer` starts it. `systemctl list-timers pve-smart-alert.timer` shows the next run.
- `pve-smart-alert status` shows the last run. "the next run is a first run and sends one summary" means that no summary was handed over yet. If the line `Last run:` shows notifications not delivered, the run took place and could not hand the summary over: follow "No notification arrives"; the next run sends the summary again.
- The summary is sent once. `first_run_summary = false` in `[notify]` switches it off. Deleting `/var/lib/pve-smart-alert/state.json` makes the next run a first run again.

## A drive is missing from `scan`

- `scan` lists what the device scan of smartctl, the HPE probe and the manual entries find. A block device that the scan of smartctl does not list, such as a USB device behind a bridge smartctl does not know, does not appear at all ([ARCHITECTURE.md](../ARCHITECTURE.md), section 5).
- A device that is listed as `skipped` names its reason: `excluded`, `remote`, `not-a-disk`, `logical-volume`, `no-smart` or `duplicate`. A drive reached through two paths is kept once, and the other path is shown as a duplicate.
- A drive shown as "in standby, not woken" was not read in that run and keeps its previous state; it is read when it is awake.
- Drives behind a controller that the scan does not cover are added by hand: a `[[discovery.device]]` entry with the device name and the smartctl type, such as `name = "/dev/sg3"` and `type = "areca,2"`. Which type each controller takes, and how each was verified, is in [docs/hardware-support.md](hardware-support.md).
- A controller whose drives smartctl cannot read, such as one with the driver `mpi3mr`, is named above the devices of `scan`, in the line `controllers` of `doctor`, and as the notice `tool.unsupported_controller`. If the controller runs in HBA mode and all its drives appear in `scan`, switch the notice off in the configuration:

  ```toml
  [checks."tool.unsupported_controller"]
  enabled = false
  ```

- For HPE Smart Array, the line `probe` of `doctor` and the line `HPE Smart Array:` of `scan` say whether the drives were probed, and if not, why.

## A drive is reported that should not be

- Exclude it with a rule in `[discovery]`, by model pattern, serial number or WWN: `exclude = [{ model = "QEMU HARDDISK" }]`. `scan` then shows it as `skipped, excluded`.
- Switch one check off for one drive with a `[[drive]]` entry that selects it and a table `[drive.checks."<check-id>"]` with `enabled = false`, or for all drives with `enabled = false` in `[checks."<check-id>"]`, as the reference configuration shows. The check identifiers are in [docs/check-catalog.md](check-catalog.md).
- `pve-smart-alert check --dry-run` shows what a run would find and send now, without sending anything or changing the state.

## The configuration does not seem to apply

- `pve-smart-alert config check` validates the file and names the first error it finds, with its key and, where it can be found, its line; run it again after each fix. A file that passes is saved as the last good configuration.
- A file that does not validate never stops a run: the last configuration that passed is used, or the built-in defaults, and the run reports `tool.config_invalid`. `doctor` says in the line `config` which configuration runs continue with. `scan`, `test-notification` and `dump-fixture` stop with exit status 2 on an invalid file instead.
- `pve-smart-alert config show` prints every key with its effective value and whether it comes from the file or is the default. While the file is invalid, the values are those of the last good configuration, and the origins are not reliable.
- The interval of the timer is not a key of this file; [README](../README.md#installation) says how to change it.

## The same problem arrives twice

smartd, which Proxmox VE runs, mails root about some of the problems this tool reports. The line `smartd` of `doctor` says whether it does. The README describes how to quiet smartd by hand ([Coexistence with smartd](../README.md#coexistence-with-smartd)); the tool never changes smartd.

## A mail says that a run failed

The failure mail is sent by the failure unit of the package, which systemd starts through `OnFailure=` when a run of `pve-smart-alert.service` fails, at most once a day and once more after a reboot. It holds the last 30 lines of that run from the journal. A run fails when it exits with a status other than 0 and 3: for example 1, when a notification could not be handed over, or when it runs longer than the limit of 15 minutes of the unit. A run of `pve-smart-alert check` typed in a shell is a real run, which sends what is due and updates the state, but it never sends the failure mail and runs outside the sandbox of the unit; `systemctl start pve-smart-alert.service` and `journalctl -u pve-smart-alert.service` repeat what the timer does.

## Reporting a problem

Attach the output of `pve-smart-alert doctor`. For a problem with a drive or a controller, record the host with `pve-smart-alert dump-fixture --all` as [docs/hardware-support.md](hardware-support.md#how-to-record-a-host) describes; the archive has serial numbers, WWNs and UUIDs replaced by placeholders, and you look at it before you share it. The output of `pve-smart-alert scan` shows the real serial numbers and WWNs: remove them before you share it.
