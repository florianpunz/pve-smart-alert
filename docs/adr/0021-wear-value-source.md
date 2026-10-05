# ADR 0021: Take the wear value from the vendor-neutral sources first

- Status: Accepted
- Date: 2026-10-05
- Decided by: the maintainer

## Context

The check catalog and FR-312 took the wear value of a SATA SSD from the same vendor attribute that the Proxmox VE web interface uses, so that both show the same number. The vendor-neutral values were only a fallback for drives without such an attribute.

The first recordings from the test cluster ([Research 06](../research/06-test-cluster-recordings.md)) show a drive for which this gives the wrong answer. The Fanxiang S301 on `pve5` reports 0 % used through attribute 177 `Wear_Leveling_Count`, which is what the web interface shows. The same drive reports 44 % in the "Percentage Used Endurance Indicator" of the ATA Device Statistics, the value defined by the ATA standard, and smartmontools 7.5 reports 44 % as `endurance_used`. Attribute 231 says 18 %.

The meaning of a vendor attribute is defined by the vendor and is sometimes guessed by the drive database. The device statistics value has one meaning for every drive. For an alerting tool, reporting 0 % for a drive that may be half worn is the worse error: the wear check would never fire.

Proxmox VE 9.2 ships smartmontools 7.5, package `7.5-pve2` ([Research 06](../research/06-test-cluster-recordings.md)), so `endurance_used` is available on the current release line. For the other five drives of the test cluster, every source that exists agrees with the web interface.

## Options considered

1. **Keep the list of the web interface first.** Both always show the same number. The Fanxiang drive would show 0 % and never trigger the wear check.
2. **Vendor-neutral sources first, the list of the web interface as the fallback.** Standard values win where the drive provides them. The number differs from the web interface on drives like the Fanxiang.
3. **Take the highest value of all sources.** Never too low, but a misread vendor attribute could raise a false warning, and the source of the number would be hard to explain.

## Decision

Option 2. The wear value of a drive is taken from the first of these sources that is present:

1. `endurance_used.current_percent` (smartmontools 7.5 and later, ATA, SCSI and NVMe).
2. ATA: the "Percentage Used Endurance Indicator" of the ATA Device Statistics. NVMe: `percentage_used` of the SMART health log. SAS: `scsi_percentage_used_endurance_indicator`.
3. ATA only: the vendor attribute found through the attribute name list of the web interface, as `100 - normalized value`.

- The snapshot records which source was used, and `pve-smart-alert scan` shows it next to the value, for example `44 % (device statistics)`.
- When the source used differs from the attribute of the web interface by 10 percentage points or more, `scan` shows both values, so that the difference to the web interface is explained where it is seen.
- FR-312 is changed accordingly; its ID stays.

## Consequences

- On most drives the tool shows the same wear as the web interface. Where it does not, it says why.
- The acceptance step of milestone M2 compares with the web interface only where the tool uses the same source, and otherwise checks that the other source is named.
- The wear check can fire on drives the web interface shows as new. Wear is capped at warning by default ([ADR 0010](0010-health-evaluation-and-default-thresholds.md)), so the cost of a wrong vendor-neutral value is one warning.
- On hosts with smartmontools older than 7.5 the second and third sources still give the same order: standard first, vendor attribute last.

## Revisit when

- A drive is found whose vendor-neutral value is clearly wrong and whose vendor attribute is right.
- Proxmox VE changes the source of its "Wearout" column.
