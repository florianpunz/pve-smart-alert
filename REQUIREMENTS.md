# Requirements

Requirements for version 1 of PVE SMART Alert.
Scope and reasons are in [PROJECT.md](PROJECT.md) and [ADR 0017](docs/adr/0017-scope-of-version-1.md).

## Conventions

- "Shall" marks a requirement that version 1 must meet. "Should" marks one that may slip without blocking the release; these are flagged as such.
- Identifiers are stable. A removed requirement keeps its number and is marked as withdrawn.
- **Verification** says how the requirement is checked:
  - **T**: automated test in CI (unit or scenario test with recorded data).
  - **A**: acceptance step on a real Proxmox VE host, part of a milestone checklist in [ROADMAP.md](ROADMAP.md).
  - **I**: inspection of the package, the code or the documentation.
- "Run" means one execution of `pve-smart-alert check`.
- Default values named here are those of [docs/check-catalog.md](docs/check-catalog.md) and [ADR 0009](docs/adr/0009-notification-policy.md).

## Functional requirements

### Discovery

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-101 | The tool shall find all directly attached SATA, SAS and NVMe drives of the host without any per-drive configuration. | T, A |
| FR-102 | The tool shall find physical drives behind MegaRAID-family controllers as reported by the device scan of smartctl, without configuration. | T |
| FR-103 | The tool shall be able to find physical drives behind HPE Smart Array controllers by probing, where smartctl supports the pass-through, and shall name a controller that it does not probe. This function is experimental in version 1 and can be switched off. | T |
| FR-104 | The tool shall accept manually configured devices, each given as a device name and a smartctl device type. A type that smartctl reads by writing to the drive is refused ([ADR 0034](docs/adr/0034-manual-entries-of-other-pass-through-types.md), NFR-04). | T |
| FR-105 | The tool shall identify a drive by model and serial number. Device node, device type and controller device ID shall not be part of the identity. | T |
| FR-106 | A drive that is reachable through more than one path shall be evaluated and reported once per run. | T |
| FR-107 | The tool shall skip, without raising any finding: logical volumes of RAID controllers, virtual disks, devices that are not disks, disks without SMART capability, devices on remote transports (iSCSI, Fibre Channel, NVMe over Fabrics), and devices matched by an exclude rule. | T |
| FR-108 | `pve-smart-alert scan` shall list every device found, the source that found it, and for each skipped device the reason. | T, A |
| FR-109 | If a controller is present whose drives cannot be queried with smartctl, `pve-smart-alert scan` and `pve-smart-alert doctor` shall state this. | T |
| FR-110 | The tool should determine whether a drive belongs to a ZFS pool, an md array or an LVM volume group and include that in notifications. Failure to determine it shall not affect the run. | T, A |

### Data collection

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-201 | The tool shall obtain drive data only from the JSON output of smartctl, using the device name and type from discovery. | I, T |
| FR-202 | Each smartctl call shall be limited by a timeout (default 30 seconds). A drive that does not answer shall not delay the evaluation of other drives by more than this timeout. | T |
| FR-203 | The tool shall not wake a SATA drive that is in standby. Such a drive shall be skipped in that run and keep its previous state. | T |
| FR-204 | NVMe drives shall be queried through the controller device, not through a namespace device. | T |
| FR-205 | A failure to obtain or parse data for one drive shall not prevent the evaluation of the other drives. | T |
| FR-206 | Output with missing or unknown JSON keys shall be accepted. Checks whose input is missing shall be treated as not applicable. | T |

### Evaluation

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-301 | The tool shall evaluate each drive with the checks of the check catalog that apply to its class (hard disk, SSD, NVMe) and protocol. | T |
| FR-302 | Each finding shall have exactly one of the severities notice, warning, critical. | T |
| FR-303 | The drive's own failure verdict (failed health status, pre-fail attribute at or below threshold, NVMe spare below threshold, NVMe read-only or reliability-degraded) shall always produce a critical finding unless the check is disabled. | T |
| FR-304 | Raw defect and error counters shall be compared with thresholds per severity as defined in the check catalog. | T |
| FR-305 | For checks that track worsening, an increase of the value since the last notification shall be detected. | T |
| FR-306 | Cumulative counters classified as events (for example CRC errors) shall produce a finding only when they increase relative to the stored baseline. A non-zero value present when the drive is first seen shall not produce a finding. | T |
| FR-307 | SSD wear shall never produce a critical finding with default settings. | T |
| FR-308 | Temperature findings shall require confirmation in 2 consecutive runs before the first notification. | T |
| FR-309 | A drive that was present and is absent in 2 consecutive runs shall produce a finding, unless it is removable, attached through USB, or has no stable identity. | T |
| FR-310 | A drive that is listed but returns no usable SMART data in 2 consecutive runs shall produce a finding. | T |
| FR-311 | A drive with SMART available but disabled shall produce a notice that names the command to enable it. The tool shall not enable it. | T |
| FR-312 | The wear value shall be taken from the vendor-neutral sources first and from a vendor attribute only when none is present, in the order of [ADR 0021](docs/adr/0021-wear-value-source.md). A vendor attribute shall be found through the same attribute name list as the Proxmox VE web interface. The tool shall show which source it used. | T, A |

### Configuration

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-401 | The tool shall work with an empty configuration file. | T, A |
| FR-402 | Every threshold and the enabled state of every check shall be overridable globally in `/etc/pve-smart-alert/config.toml`. | T |
| FR-403 | Thresholds, the enabled state of checks, the smartctl detail level and exclusion shall be overridable for an individual drive selected by serial number, WWN or model pattern. | T |
| FR-404 | Reminder intervals, cool-downs, confirmation and clear counts, the grouping limit, the transport, recovery notifications and the first-run summary shall be configurable. | T |
| FR-405 | The configuration shall be validated completely before use. Unknown keys, wrong types, out-of-range values and unknown check identifiers shall be reported with the key name. | T |
| FR-406 | If the configuration file is invalid at run time, the run shall continue with the last configuration that passed validation, or with the built-in defaults if none exists, and shall raise a tool-level warning. | T |
| FR-407 | `pve-smart-alert config check` shall validate the file and exit non-zero on errors. `pve-smart-alert config show` shall print the effective configuration and the origin of each value. | T |
| FR-408 | The enabled state of every condition of the tool itself shall be overridable globally in `/etc/pve-smart-alert/config.toml`, in the same table as the checks of a drive and with the same meaning; such a condition shall take no threshold. | T |

### Notification

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-501 | Notifications shall be delivered through the Proxmox VE notification system with a severity of `info`, `notice`, `warning` or `error`, mapped from the finding severity. | A |
| FR-502 | Every notification shall carry the metadata fields `type` with the value `pve-smart-alert` and `hostname` with the node name. | T, A |
| FR-503 | A notification about a single drive shall in addition carry the fields `event`, `device`, `serial` and `model`, and, for a drive read through a pass-through type such as `megaraid,N`, the field `device-id` with its device ID. | T |
| FR-504 | A matcher with the rule `match-field regex:type=^pve-smart-alert$` shall match all notifications of the tool and no built-in notification. | A |
| FR-505 | If the primary transport fails, the same message shall be sent as mail to the local `root` user in the same run, with the severity in the subject. | T, A |
| FR-506 | The transport shall be selectable: automatic with fallback, primary only, or mail only. | T |
| FR-507 | A notification body shall contain: host name and, in a cluster, cluster name; device name and smartctl type; model; serial number; WWN if known; firmware version; capacity; drive class; location information (controller and device ID, or bus path); pool, array or volume group if known; and for each finding the check, the severity, the current value, the previous value if any, and the threshold. | T |
| FR-508 | The subject shall contain the severity, the host name, and for a single-drive notification the device name, the model, the serial number and the most severe finding. | T |
| FR-509 | A new condition shall produce exactly one notification. | T |
| FR-510 | An unchanged condition shall not be notified again before its reminder interval has passed (default: critical 3 days, warning 7 days, notice never). | T |
| FR-511 | A rise in severity shall be notified in the run in which it is detected. | T |
| FR-512 | A worsened value at unchanged severity shall be notified at most once per cool-down period per drive (default 6 hours). | T |
| FR-513 | When a condition has been absent for the clear count (default 2 runs), one recovery notification with severity `info` shall be sent, unless recovery notifications are switched off. | T |
| FR-514 | All findings that are due for one drive in one run shall be combined into one notification. | T |
| FR-515 | If more than the grouping limit (default 3) of drives have a notification due in one run, exactly one summary notification shall be sent instead. | T |
| FR-516 | On the first run, exactly one summary notification shall be sent that lists the monitored drives, the skipped devices and the existing findings. No other drive notification shall be sent in that run. | T, A |
| FR-517 | A state change that belongs to a notification shall be stored only after the notification was handed over. After a failed handover the notification shall be planned again in the next run. | T |
| FR-518 | Problems of the tool itself (smartctl missing or too old, scan failed, configuration invalid, state reset, transport degraded, unsupported controller) shall be notified under the same policy as drive conditions. | T |
| FR-519 | If a run ends with an unhandled error, a mail shall be sent to `root` by a mechanism that does not use the tool's own program code, at most once per day. | A |
| FR-520 | `pve-smart-alert test-notification` shall send a test message with a selectable severity through the configured transport, print the result reported by the notification system, and name the matchers that route the message or say that none does ([ADR 0020](docs/adr/0020-routing-check.md)). | T, A |

### Operation and commands

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-601 | `pve-smart-alert check` shall perform one run. With `--dry-run` it shall print the planned notifications, change no state and send nothing. | T |
| FR-602 | `pve-smart-alert status` shall show, from the stored state, every drive with its active conditions and the time and result of the last run. With `--json` the output shall be machine-readable. | T |
| FR-603 | `pve-smart-alert doctor` shall check and report: smartctl presence and version, Proxmox VE version, the notify bridge, the template files, the mail command, the timer state, the configuration, the state file, unsupported controllers, the probe for HPE Smart Array controllers, whether smartd is active and mailing, and whether the notification matchers route every severity of the tool and the fallback mail to root to an enabled target ([ADR 0020](docs/adr/0020-routing-check.md), [ADR 0022](docs/adr/0022-fallback-routing-check.md)). | T, A |
| FR-604 | `pve-smart-alert dump-fixture` shall record scan and drive output for all or selected drives with serial numbers, WWNs and other identifying values replaced by stable placeholders. | T |
| FR-605 | Two runs shall never execute at the same time. A second invocation shall exit with a message. | T |
| FR-606 | Each run shall log one summary line with the number of drives evaluated, skipped and failed, the number of active conditions per severity, and the number of notifications sent. | T |
| FR-607 | The exit status of `pve-smart-alert check` shall be 0 when the run completed, regardless of drive health, and non-zero when the run itself failed. | T |

### Installation and life cycle

| ID | Requirement | Verification |
| --- | --- | --- |
| FR-701 | The tool shall be installable on a Proxmox VE 9 host with one command line, without any prior or subsequent manual step. | A |
| FR-702 | After installation a run shall start automatically without a reboot, and further runs shall follow every 30 minutes. | A |
| FR-703 | After a reboot, runs shall resume without manual action. | A |
| FR-704 | An upgrade of the package shall keep configuration and state. | A |
| FR-705 | Removing the package shall stop the timer and remove all installed files. Purging shall also remove configuration and state. Nothing else on the host shall differ from the state before installation. | T, A |

## Non-functional requirements

| ID | Requirement | Verification |
| --- | --- | --- |
| NFR-01 | **Dependencies.** Installing the package on a standard Proxmox VE 9 host shall not pull in any package that is not already installed. | A, T |
| NFR-02 | **Platform.** The tool shall work on every Proxmox VE 9.x release that is supported by Proxmox at the time of a PVE SMART Alert release. | A |
| NFR-03 | **Host footprint.** The tool shall create, modify or delete only: files installed by its package, `/etc/pve-smart-alert/`, `/var/lib/pve-smart-alert/`, `/run/pve-smart-alert/`. It shall not modify files owned by other packages and shall not write to `/etc/pve`. | I, T |
| NFR-04 | **Drive footprint.** The tool shall only issue read commands to drives. It shall not enable SMART, start self-tests, or change any drive setting. | I, T |
| NFR-05 | **Upgrade safety.** A change in Proxmox VE that breaks the primary notification transport shall result in delivery through the fallback transport, not in silence. | T, A |
| NFR-06 | **Upgrade safety.** The installed program shall contain no compiled code and use no Python module outside the standard library. | I |
| NFR-07 | **Run time.** A run on a host with 24 responsive drives shall complete within 60 seconds. | T, A |
| NFR-08 | **Run time bound.** A run shall be terminated after a configured maximum duration (default 15 minutes), so that runs cannot accumulate. | T |
| NFR-09 | **Resource use.** No process of the tool shall remain between runs. Runs shall execute with reduced CPU and I/O priority. | I, A |
| NFR-10 | **Flood limit.** One run shall send at most as many notifications about drives as the grouping limit allows (default 3), plus at most one about the tool itself. | T |
| NFR-11 | **Crash safety.** Termination of the process at any point shall leave either the previous or the new state file, never a partial one. | T |
| NFR-12 | **Self-healing.** An unreadable state file shall be set aside and the run shall continue. The following notification shall be a single summary. | T |
| NFR-13 | **Security.** Configuration shall be writable by root only; state shall be readable by root only. External commands shall be executed without a shell and with validated arguments. The tool shall open no network socket of its own. | I, T |
| NFR-14 | **Privacy.** Serial numbers and WWNs shall appear only in notifications, in the state file and in the journal. Fixtures produced by `dump-fixture` shall not contain them. | T |
| NFR-15 | **Testability.** Every check and every rule of the notification policy shall be covered by an automated test that needs neither root nor a Proxmox VE host nor real drives. | T |
| NFR-16 | **Hardware coverage evidence.** Every controller family named in the documentation shall carry one of the evidence labels defined in [ADR 0016](docs/adr/0016-test-strategy.md). The labels are in [docs/hardware-support.md](docs/hardware-support.md). | I, T |
| NFR-17 | **Cluster independence.** A node shall evaluate its drives and send notifications when the cluster has no quorum. No state shall be shared between nodes. | A |
| NFR-18 | **Detection delay.** With default settings a new condition shall be notified within 35 minutes of becoming visible in SMART data, or within 65 minutes for checks that need confirmation. | T |
| NFR-19 | **Language.** All code, comments, documentation, configuration keys, log messages and notification texts shall be in English. | I |
| NFR-20 | **License.** Every source file shall carry an SPDX license identifier. Every fixture shall have a recorded origin and license. | T |
| NFR-21 | **Interface stability.** Command names, configuration keys, check identifiers and notification field names shall not change within a major version. | I |
| NFR-22 | **Code quality.** The Python code shall pass the configured linter and strict static type checking in CI. | T |

## Traceability

Which tests and acceptance steps relate to each requirement, and which requirements no test covers, is in [docs/traceability.md](docs/traceability.md).

| Goal in [PROJECT.md](PROJECT.md) | Requirements |
| --- | --- |
| 1. One-command installation, no care afterwards | FR-701 to FR-705, NFR-01, NFR-05, NFR-06 |
| 2. Automatic discovery | FR-101 to FR-110 |
| 3. Sensible defaults, overridable | FR-301 to FR-312, FR-401 to FR-408 |
| 4. No alert flood | FR-306, FR-308, FR-509 to FR-517, NFR-10 |
| 5. Messages that identify host, drive and value | FR-507, FR-508 |
| 6. Single host and cluster node alike | FR-502, NFR-17 |
| Read-only principle | NFR-03, NFR-04, FR-311 |
| Fail loudly | FR-406, FR-518, FR-519, FR-603 |
