# Troubleshooting

What to do when PVE SMART Alert does not do what you expect.
Start with `pve-smart-alert doctor`: it reports one line per part of the host the tool works with, as `ok`, `warn`, `fail` or `skip`, and adds advice below a line where something can be done.
The commands are described in the [README](../README.md#commands) and in the manual page source [`man/pve-smart-alert.8`](../man/pve-smart-alert.8).

## No notification arrives

1. Send a test: `pve-smart-alert test-notification --severity warning`. It prints whether the notification was handed over, which transport took it, what the notification system logged, and which matchers route it.
2. If it says that no matcher matched, the notification system dropped the message without an error. Add a matcher under Datacenter → Notifications, for example with the rule `match-field regex:type=^pve-smart-alert$`, and route the severities you want to a target. `doctor` reports `routing` as `warn` and names each severity of the tool that reaches no enabled target ([README](../README.md#notification-routing)).
3. If the line `bridge` of `doctor` fails, the tool cannot load the notification library of Proxmox VE. With the default `transport = "auto"`, every notification then goes as mail to root instead, without its severity, and each run reports `tool.transport_degraded`; with `transport = "pve-notify"` nothing can be delivered. Run `/usr/libexec/pve-smart-alert/notify-bridge --check` to see the error.
4. If the line `fallback` warns, the mail to root that replaces a notification would be dropped too: Proxmox VE routes it as the type `system-mail` with the severity `unknown`. Route that type, as the advice of the line says.
5. If the line `templates` fails, a template file of the tool is missing from `/usr/share/pve-manager/templates/default`. Reinstalling the package puts it back.
6. If the line `mail` fails, the host has no `/usr/sbin/sendmail`; the fallback and the failure mail need it.

## The first-run summary did not come

- The first run starts right after the installation, and 3 minutes after a boot. `systemctl list-timers pve-smart-alert.timer` shows the next run, and `journalctl -u pve-smart-alert.service` one line per run.
- `pve-smart-alert status` shows the last run. "the next run is a first run" means that no run has completed yet.
- If the summary was sent but did not arrive, follow "No notification arrives".
- The summary is sent once. `first_run_summary = false` in `[notify]` switches it off. Deleting `/var/lib/pve-smart-alert/state.json` makes the next run a first run again.

## A drive is missing from `scan`

- `scan` lists what the device scan of smartctl, the HPE probe and the manual entries find. A block device that the scan of smartctl does not list, such as a USB device behind a bridge smartctl does not know, does not appear at all ([ARCHITECTURE.md](../ARCHITECTURE.md), section 5).
- A device that is listed as `skipped` names its reason: `excluded`, `remote`, `not-a-disk`, `logical-volume`, `no-smart` or `duplicate`. A drive reached through two paths is kept once, and the other path is shown as a duplicate.
- Drives behind a controller that the scan does not cover are added by hand: a `[[discovery.device]]` entry with the device name and the smartctl type, such as `name = "/dev/sg3"` and `type = "areca,2"`. Which type each controller takes, and how each was verified, is in [docs/hardware-support.md](hardware-support.md).
- A controller whose drives smartctl cannot read, such as one with the driver `mpi3mr`, is named above the devices of `scan`, in the line `controllers` of `doctor`, and as the notice `tool.unsupported_controller`. If the controller runs in HBA mode and all its drives appear in `scan`, switch the notice off with `[checks."tool.unsupported_controller"] enabled = false`.
- For HPE Smart Array, the line `probe` of `doctor` and the line `HPE Smart Array:` of `scan` say whether the drives were probed, and if not, why.

## A drive is reported that should not be

- Exclude it with a rule in `[discovery]`, by model pattern, serial number or WWN: `exclude = [{ model = "QEMU HARDDISK" }]`. `scan` then shows it as `skipped, excluded`.
- Switch one check off for one drive with a `[[drive]]` entry that selects it and a table `[drive.checks."<check-id>"]` with `enabled = false`, or for all drives with `enabled = false` in `[checks."<check-id>"]`, as the reference configuration shows. The check identifiers are in [docs/check-catalog.md](check-catalog.md).
- `pve-smart-alert check --dry-run` shows what a run would find and send now, without sending anything or changing the state.

## The configuration does not seem to apply

- `pve-smart-alert config check` validates the file and names the key and the line of every error.
- A file that does not validate never stops a run: the last configuration that passed is used, or the built-in defaults, and the run reports `tool.config_invalid`. `doctor` says in the line `config` which configuration runs continue with.
- `pve-smart-alert config show` prints every key with its effective value and whether it comes from the file or is the default.
- The interval of the timer is not a key of this file. Change it with `systemctl edit pve-smart-alert.timer`.

## The same problem arrives twice

smartd, which Proxmox VE runs, mails root about some of the problems this tool reports. The line `smartd` of `doctor` says whether it does. The README describes how to quiet smartd by hand ([Coexistence with smartd](../README.md#coexistence-with-smartd)); the tool never changes smartd.

## A mail says that a run failed

The failure mail is sent by the failure unit of the package, which systemd starts when `pve-smart-alert check` ends with an error, at most once a day and once more after a reboot. It contains the lines of the failed run from the journal. `journalctl -u pve-smart-alert.service` shows the run; `pve-smart-alert check` run by hand shows the error on the terminal. A run that ends because another one holds the lock exits with status 3, which counts as success.

## Reporting a problem

Attach the output of `pve-smart-alert doctor` and `pve-smart-alert scan`. For a problem with a drive or a controller, record the host with `pve-smart-alert dump-fixture --all` as [docs/hardware-support.md](hardware-support.md#how-to-record-a-host) describes; the archive has serial numbers, WWNs and UUIDs replaced by placeholders, and you look at it before you share it.
