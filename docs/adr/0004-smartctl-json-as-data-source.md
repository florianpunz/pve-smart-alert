# ADR 0004: smartctl JSON output as the only source of drive data

- Status: Accepted
- Date: 2026-10-03

## Context

The tool needs health data for SATA, SAS and NVMe drives, including drives that are only reachable through a controller pass-through option.
Several ways exist to get this data on a Proxmox VE host.
Evidence is in [Research 02](../research/02-builtin-smart-handling.md), [Research 03](../research/03-smart-indicators.md) and [Research 05](../research/05-prior-art.md).

## Options considered

1. **`smartctl --json`**, one process per drive.
   Structured output since smartmontools 7.0, the same interface for all three protocols and for every pass-through type. `smartmontools` is a hard dependency of Proxmox VE. Scrutiny and smartctl_exporter are built on exactly this.
2. **Parsing the text output of smartctl**, as the Proxmox VE web interface does.
   Fragile, differs per protocol, and unnecessary since JSON exists.
3. **The Proxmox VE API** (`/nodes/{node}/disks/list`, `/disks/smart`).
   Returns only a health verdict, a wear-out value and the ATA attribute table. Never passes `-d`, so drives behind RAID controllers are invisible. Uses the NVMe namespace device. Not enough data and the wrong device coverage.
4. **smartd as the engine**: read its state and attribute log files, or hook into `-M exec`.
   The files are an internal format. The hook only fires for smartd's fixed set of conditions. Making smartd check more would mean editing `/etc/smartd.conf`, which the tool must not touch ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)).
5. **Direct device access** from the tool (ioctl, sysfs) or through a library such as pySMART or libatasmart.
   Re-implements smartmontools, including its drive database and its controller support. A library would be a third-party dependency ([ADR 0003](0003-implementation-language.md)).
6. **`nvme-cli` for NVMe**, smartctl for the rest.
   `nvme-cli` is not a dependency of Proxmox VE, and smartctl already returns the same health log.

## Decision

`smartctl --json` is the only source of drive data.

Invocation rules:

- One call per drive: `smartctl --json=c --xall --device=<type> <name>`, with name and type exactly as discovery returned them ([ADR 0005](0005-drive-discovery-and-identity.md)).
- `--xall` is the default because it includes the ATA device statistics (vendor-neutral wear value) and SCT temperature data. `--all` can be selected globally or per drive for hardware that reacts badly to the extended logs.
- For ATA drives `--nocheck=standby` is added so that sleeping disks are not spun up. A drive in standby is skipped for this run and keeps its previous state.
- NVMe drives are addressed through the controller device (`/dev/nvme0`), never through a namespace block device. smartctl 7.4 can increment a drive's error log counter when the self-test log is read through a namespace device.
- Only options that read are ever passed. No option that changes a drive setting, enables SMART or starts a test.
- Each call has a timeout (default 30 seconds). The process group is killed on expiry. Drives are queried one after the other.
- Arguments are passed as a list, never through a shell. Device names and types are validated against a strict pattern before use.

Interpretation rules:

- The exit status is a bit mask. Bits 0 and 1 mean that no usable data was obtained. Bit 2 alone is tolerated, because it is common when a drive lacks one of the extended logs. Bits 3 to 7 are hints; the findings are derived from the JSON content, not from the exit status.
- The JSON is accepted if `json_format_version` has major version 1. Unknown keys are ignored. Missing keys make the checks that need them "not applicable"; they never produce a finding.
- Values that exist only in newer smartmontools versions (`endurance_used`, `spare_available`, `power_mode`) are used when present and never required.
- The only text that is parsed is the content of JSON string values, for example `raw.string` of an ATA attribute.
- Protocol-specific parsers (ATA, SCSI, NVMe) translate the JSON into one internal snapshot model. The checks work on the model, not on the JSON.

## Consequences

- No additional dependency. The controller support of smartmontools is inherited, and so are its gaps: drives behind `mpi3mr` controllers cannot be read ([Research 04](../research/04-hardware-raid.md)).
- Data quality depends on the smartmontools version and its drive database. Proxmox VE 9 ships 7.4; some conveniences of 7.5 are missing and are derived by the tool.
- Recorded JSON output is a complete test input. This is what makes testing without hardware possible ([ADR 0016](0016-test-strategy.md)).
- A drive that hangs costs at most the timeout per run.
- The internal snapshot model is the seam for any future second data source.

## Revisit when

- A controller family that matters cannot be covered by smartmontools and a vendor tool would be needed.
- smartmontools changes the major version of its JSON format.
