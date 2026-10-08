# Research 07: Acceptance run on the standalone host pve1

What a run of milestone M2 on a standalone Proxmox VE host shows, and what it does not.
The run was made on 2026-10-08 with package 0.2.0 on `pve1`, a host that is not part of the test cluster. Everything in this note is **Verified** on that host, unless it is marked otherwise.

`pve1` has Proxmox VE 9.2.3 (kernel 7.0.6-2-pve), smartmontools 7.5, one Intenso SATA SSD with LVM-thin, and one USB stick from a KVM-over-IP device (`NanoKVM`). It has no NVMe drive. Its results are additional evidence and do not replace steps 1 to 4 on the nodes `pve5` to `pve7` ([ROADMAP.md](../../ROADMAP.md)).

The raw archive contains the real serial number and is not part of the repository ([ADR 0016](../adr/0016-test-strategy.md)). The anonymized recording is `tests/fixtures/smartctl/direct/standalone-pve1/`.

## Steps of the acceptance

| Step | Case | Result |
| --- | --- | --- |
| 1 | `scan` | The Intenso SSD is listed once, with model, serial number, class `ssd`, transport `sata`, volume group `pve`. The USB stick is not listed (see below). |
| 2 | Wear value | The API returns `wearout` 100. The web interface shows 0 % (see below). `scan` shows 3 % `(endurance_used)`. |
| 3 | `dump-fixture --all` | The archive contains no part of the real serial number. |
| 4 | Manual entry `/dev/sdz`, type `sat` | The scan completes, the entry is `unreadable`, reason `Smartctl open device: /dev/sdz [SAT] failed: No such device`. An entry needs `name` and `type`; with `name` alone the configuration is refused with status 2. |
| 5 | Routing, three cases | As expected, see below. |

## Step 2: the wear value

- The API `pvesh get /nodes/pve1/disks/list` returns `"wearout": 100` for the Intenso SSD. The vendor attribute 177 `Wear_Leveling_Count` has the normalized value 100 and the raw value 0.
- The Wearout column of the web interface renders `100 - value` (`Proxmox.DiskList` in `/usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js`, read on the host), so it shows **0 %**. This was read in the code of the renderer; the web interface itself was not opened.
- `scan` shows **3 % (endurance_used)**. The source is the "Percentage Used Endurance Indicator" of the ATA Device Statistics (`smartctl -x`, page 0x07), which smartmontools 7.5 reports as `endurance_used`.
- The values differ, so the first clause of the step does not hold. The second clause does: `scan` names the vendor-neutral source that gives the different value. The difference is below the 10 points at which [ADR 0021](../adr/0021-wear-value-source.md) makes `scan` show the value of the web interface as well, so the web interface value is not printed here. A user who compares both numbers sees 3 % against 0 % and the name of the source, but not an explanation that the web interface reads another attribute.

## Step 5: routing and fallback

State of the notification system before the run: the built-in `default-matcher` for all notifications to `mail-to-root`, no other matcher.

| Case | `doctor` | `test-notification` | As expected |
| --- | --- | --- | --- |
| Default matcher limited to `exact:type=vzdump`, no matcher for the tool | `routing` warn, `info, notice, warning, error` not routed, advice names the rule; `fallback` warn, `system-mail` not routed | `Delivered: yes`, `Matchers: none, no matcher routes this notification to an enabled target` | Yes |
| Plus matcher `pve-smart-alert` (`regex:type=^pve-smart-alert$`) for `warning,error` | `routing` warn, `info, notice` not routed; `fallback` warn | severity `info`: no matcher; severity `warning`: matcher `pve-smart-alert` | Yes |
| That matcher extended to all four severities | `routing` ok, by `pve-smart-alert`; `fallback` warn | `info` and `error`: matcher `pve-smart-alert`, log `notified via target mail-to-root` | Yes |

`test-notification` says `Delivered: yes` in the first two cases although no matcher routed the notification. The notification system accepts it without an error and drops it, as ADR 0020 describes; the line `Matchers:` is what tells.

### The line `fallback` (ADR 0022)

- ok case: with an additional matcher `exact:type=system-mail`, `fallback` reports `mail to root is routed as system-mail, by sysmail-test`. `/root/.forward` pipes to `/usr/libexec/proxmox-mail-forward`.
- warn case: with the default matcher limited to `vzdump`, `fallback` warns that no matcher routes `system-mail` to an enabled target (first row above).
- Bridge made unusable: the template `pve-smart-alert-body.txt.hbs` renamed, as in M1 step 4. `doctor` reports `templates` as `fail`. `test-notification` reports `Used: mail`, `Fallback: the notification system could not render the template`, `Matchers: sysmail-test, as system-mail`. The file was renamed back afterwards.

Where delivery was confirmed:

- Confirmed in the journal: the bridge error, the mail handed to `proxmox-mail-forward` by postfix (`delivered to command: /usr/libexec/proxmox-mail-forward`), the forwarder's `notified via target mail-to-root`, and the mail text with the line that the primary transport failed and why (`postcat` of the queued message).
- Not confirmed: that a mail reached an inbox. The address of `root@pam` on `pve1` is in a domain that does not resolve, so postfix keeps every message deferred in its queue and nothing leaves the host. What `pve1` shows is the path up to and including the mail system, not the last hop.

## The USB stick is absent from the scan

`pve-smart-alert scan` says `0 skipped` and does not mention the stick, though the web interface lists it (type `usb`, health `UNKNOWN`).

| Command | Contains `/dev/sdb`? |
| --- | --- |
| `smartctl --scan --json` | No. Only `/dev/sda`, type `scsi`. |
| `smartctl --scan-open --json` | No. Only `/dev/sda`, type `sat`. No entry, and no `open_error` entry either. |
| `smartctl --scan-open -d scsi --json` | Yes, as type `scsi`. |
| `smartctl -i --json /dev/sdb` | Exit status 1, message `Unknown USB bridge [0x3346:0x1009 (0x510)]`. |
| `lsblk` | Yes: `TRAN=usb`, `RM=1`, `HOTPLUG=1`, `FSTYPE=exfat`, vendor `NanoKVM`. |

- The tool reads the scan and then adds enrichment from `lsblk` to the devices of the scan. A device that only `lsblk` shows is never a candidate. This is the behavior of [ARCHITECTURE.md](../../ARCHITECTURE.md) section 5 and the same as on `pve5` ([Research 06](06-test-cluster-recordings.md)), where the recorded scan does not list the USB device either.
- [FR-108](../../REQUIREMENTS.md) asks for "every device found" and a reason for each skipped one. Read literally it is met: the stick is not found by a source, so it is not skipped. Read by what a user expects from `scan`, the line `0 skipped` hides a drive that the web interface shows.
- Why the scan omits the stick is **Assumed**: smartctl cannot find a working device type for the unknown USB bridge and leaves the device out without an entry. The source of the Linux scan was not read for this note. The open question is Q-S7.
- Q-S1 asked what a device that cannot be opened looks like in the scan. This run does not contradict the answer in [Research 03](03-smart-indicators.md) (an entry with `open_error`), but it shows a second case: a device for which no type is found does not appear at all.

Options, without a change in this run:

1. **Keep it.** [ADR 0017](../adr/0017-scope-of-version-1.md) monitors USB drives only if smartctl can read them, with no further effort. This stick cannot be read, and on this host and on `pve5` it is a virtual drive of a KVM device. Nothing is monitored that should be.
2. **List block devices that `lsblk` shows and the scan does not**, as skipped with a reason such as `not-scanned`, in `scan` only. It changes no monitoring, and `0 skipped` stops hiding the device. It adds a reason code, a line in ARCHITECTURE section 5 and a rule for virtual drives of KVM devices, which would show up in every `scan` of a node with such a device.
3. **Probe such devices with an explicit type.** It reads more drives than the scan finds, which ADR 0005 does not provide for, and it would read a virtual drive.

Recommendation: option 1 for version 1, with the finding recorded; reconsider option 2 if a contributor reports a real drive that the scan omits. Option 2 is cheap, but it needs a rule for virtual drives first.
