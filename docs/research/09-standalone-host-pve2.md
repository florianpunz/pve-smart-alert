# Research 09: The standalone host pve2 as a test host

What the second standalone test host is, and what its device scan shows.
Everything in this note is **Verified** on that host on 2026-11-03, unless it is marked otherwise.

`pve2` (`pve2.local`) is a stand-alone Proxmox VE host, not part of the test cluster. It runs Proxmox VE 9.1.1 (kernel 6.17.2-1-pve) with smartmontools 7.4, so it covers the older 9.x line next to the cluster, which runs 9.2 with smartmontools 7.5 ([Research 06](06-test-cluster-recordings.md)). The maintainer made it available on 2026-11-03 for the complete test cycle: a package is installed, upgraded and purged there, and every command runs against its real drives.

Its drives, with model, size and transport (the serial numbers and WWNs are not part of this note; the raw recordings stay on the host, [ADR 0016](../adr/0016-test-strategy.md)):

| Device | Model | Size | Transport | Class |
| --- | --- | --- | --- | --- |
| `/dev/sda` | WDC WD10EZEX-60WN4A0 | 1 TB | sata | hdd |
| `/dev/sdb` | Samsung SSD 850 EVO 250GB | 250 GB | sata | ssd |
| `/dev/sdc` | WDC WD50NDZW-11A8JS1 | 5 TB | usb | hdd |
| `/dev/nvme0n1` | Samsung MZVLW256HEHP-000H1 | 256 GB | nvme | nvme |
| `/dev/sdd` | USB Mass Storage | 21.2 GB | usb | disk |

## The device that the scan omits (Q-S7)

`smartctl --scan-open` on the host lists four devices: `/dev/sda`, `/dev/sdb`, `/dev/sdc` and `/dev/nvme0`, each with the ATA or NVMe type. It does not list `/dev/sdd`, the 21.2 GB USB mass-storage device that `lsblk -d` shows with the transport `usb`, and it reports no `open_error` for it. `pve-smart-alert scan` therefore reports `4 monitored, 0 in standby, 0 unreadable, 0 skipped`.

This is the same behaviour that [Research 07](07-standalone-host-pve1.md) records for the USB device of the KVM-over-IP device on `pve1`: a block device with a USB transport can be absent from the scan without an entry and without an error. Whether smartctl finds no working device type for it and drops it there was not read in the source; the note records the observation on a second host, not the reason (Q-S7).

## What a run of the tool shows on this host

On 2026-11-03, with the test build `0.5.0~dev6`: the first run monitors all four drives the scan lists, the SATA SSD reports a wear of 4 % from the vendor attribute and the NVMe drive 15 % from the health log, `check --dry-run` finds nothing, and every line of `doctor` is `ok`. The line `controllers` names six SCSI hosts with the drivers `ahci` and `usb-storage` and no controller whose drives smartctl cannot read; the line `probe` finds no HPE Smart Array controller. The host has no SAS drive and no RAID controller, so it is no evidence for the families of milestone M6.

`dump-fixture --all` on this host writes an archive of the four drives that keeps the node names (`sda`, `sdb`, `sdc`, `nvme0`) and file names, and a search over every file of the archive found no real serial number or WWN; the archive stays on the host.

## Commands used

- `smartctl --version`, `smartctl --scan-open`
- `lsblk -d -o NAME,MODEL,SIZE,TRAN,TYPE,ROTA`
- `pve-smart-alert scan`, `check --dry-run`, `doctor`, `status`, `test-notification`, `dump-fixture --all`
- `apt-get install`, `apt-get purge` of the test builds `0.5.0~dev5` and `0.5.0~dev6`
