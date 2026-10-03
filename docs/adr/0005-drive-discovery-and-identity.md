# ADR 0005: Drive discovery and drive identity

- Status: Accepted
- Date: 2026-10-03

## Context

Drives must be found without per-drive configuration, on plain controllers and behind RAID controllers.
The set of drives changes: disks are replaced, device nodes are renumbered at boot, a MegaRAID device ID changes when a disk is swapped, USB disks come and go.
State is kept per drive ([ADR 0007](0007-state-storage.md)), so the tool needs an identity that survives all of this.
Evidence is in [Research 04](../research/04-hardware-raid.md).

## Options considered for discovery

1. **Enumerate block devices** (`/sys/block`, `lsblk`) and guess the smartctl type.
   Sees only what the kernel exposes as a block device. Physical drives behind a RAID controller are not block devices, so this fails for the main reason discovery is hard.
2. **`smartctl --scan-open --json`.**
   Returns name, type and protocol for SATA, SAS, NVMe and MegaRAID pass-through, and opens each device to refine the type. It is the same scan smartd uses.
3. **Proxmox VE's disk list** (`PVE::Diskmanage`, API).
   Block devices only, no `-d` types.
4. **Vendor tools** (`storcli`, `ssacli`).
   Authoritative for their controller, but not installed by default and different for every vendor.

## Options considered for identity

1. **Device node** (`/dev/sda`): changes between boots.
2. **`/dev/disk/by-id` or `by-path` link**: exists only for block devices; `by-path` changes when a disk moves to another bay.
3. **World Wide Name**: unique for most SATA and SAS drives, not reported by all drives and bridges, reported differently for NVMe.
4. **Model plus serial number**: reported by smartctl for practically every real drive on every protocol and through every pass-through type.

## Decision

Discovery is a pipeline of four steps.

1. **Sources.**
   - `smartctl --scan-open --json` is the primary source. Name and type are always kept together.
   - Probes add what the scan cannot see. Version 1 has one probe: `cciss,N` for HPE Smart Array controllers, started only if an `hpsa` or `smartpqi` SCSI host exists. It is labeled experimental until it is confirmed on hardware.
   - Manual entries from the configuration (device name plus smartctl type) cover every other controller.
2. **Enrichment** from `lsblk --json` and sysfs, best effort: transport, removable flag, `by-id` and `by-path` links, and membership in a ZFS pool, an md array or an LVM volume group. Enrichment failing never fails the run.
3. **Filtering.** A device is skipped, with a recorded reason and without any alert, if it is
   - a logical volume of a RAID controller, or a virtual disk of a hypervisor,
   - not a disk (enclosure, tape, optical),
   - a disk that has no SMART capability at all,
   - reached through a remote transport (iSCSI, Fibre Channel, NVMe over Fabrics),
   - matched by an exclude rule in the configuration.
   What a device is gets decided from the smartctl output and the transport, not from its name.
4. **De-duplication.** If the same drive is reachable through several paths, one path is kept and the others are recorded as aliases. A directly attached block device is preferred over a pass-through path.

Identity:

- The identity of a drive is the pair **model and serial number**, normalized (trimmed, internal whitespace collapsed).
- The WWN is stored as an additional attribute and used to match drives whose serial number is missing.
- Device node, smartctl type, controller device ID, bay and `by-path` link are attributes of the drive. They are updated on every run and shown in notifications, but they are never used as identity.
- If neither serial number nor WWN is available, the `by-path` link is used and the drive is flagged as having an unstable identity. Such a drive is monitored, but it is exempt from missing-drive detection.
- If two different devices report the same model and serial number through unrelated controllers, the path is appended to tell them apart and a notice is logged.

Visibility:

- `pve-smart-alert scan` lists every device found, the source that found it, and for skipped devices the reason.
- If a controller driver is loaded whose drives cannot be reached at all (`mpi3mr`), `pve-smart-alert scan` and `pve-smart-alert doctor` say so explicitly.

## Consequences

- A fresh installation monitors every drive that smartctl can reach without any configuration.
- Replacing a disk produces a "drive no longer present" event for the old serial number and a new drive record for the new one. This is correct and intended ([ADR 0009](0009-notification-policy.md)).
- Renumbered device nodes and changed MegaRAID device IDs have no effect on state.
- Coverage of HPE controllers rests on probing rules that could not be tested on hardware. The risk is contained by the experimental label, by fixtures, and by manual entries as a fallback.
- The filter rules decide silently by design. The `scan` command is the safeguard against a drive being skipped by mistake.
- Bay numbers for MegaRAID drives are not available without the vendor tool. Notifications show controller, device ID and serial number instead.

## Revisit when

- Recorded output from HPE, Adaptec or Areca hardware becomes available.
- smartmontools gains support for `mpi3mr` controllers.
- Users ask for bay numbers; an optional `storcli` enrichment would be the answer.
