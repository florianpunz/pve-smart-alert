# ADR 0010: Health evaluation model and default thresholds

- Status: Accepted
- Date: 2026-10-03

## Context

The tool has to decide from SMART data whether a drive has a problem and how serious it is, with defaults that are useful without configuration and that an administrator can override.
The evidence is in [Research 03](../research/03-smart-indicators.md). The points that shape the model:

- Vendor thresholds on normalized values confirm a failure; they rarely predict one. Raw counters need their own thresholds.
- A few counters carry most of the predictive value. Most attributes are noise for alerting.
- SATA, SAS and NVMe report different things. One threshold table cannot cover them.
- Some values are states, others are cumulative counters where only a change is meaningful.
- Wear is a planning signal. A worn drive that still has spare capacity is not a failed drive.
- SMART misses a substantial share of failures. A drive that stops answering must be caught separately.

## Options considered

1. **Trust the drive's own verdict** (health status and vendor thresholds). This is what smartd and the web interface do. It is the gap the project exists to close.
2. **A score per drive**, computed from weighted attributes. Compact, but opaque. An administrator cannot see which value caused an alert or override one aspect.
3. **Failure-rate lookup per attribute**, as Scrutiny does. Well founded for hard disks, but only for attributes with public data, and the status depends on tables that users cannot easily adjust.
4. **A catalog of independent checks**, each with a documented source value, default thresholds and its own identifier. Transparent and overridable. The defaults can be founded on the same failure-rate data.
5. **Statistical or machine-learning prediction.** Needs history and training data. Out of proportion for this tool.

## Decision

### Model

- Evaluation is a **catalog of independent checks**. Each check has a stable identifier, the drive classes it applies to, the value it reads from the snapshot, default thresholds, and its kind (condition or event, see [ADR 0009](0009-notification-policy.md)).
- A check whose input is missing is **not applicable**. Missing data is never a finding. This matters for drives behind controllers that cannot return everything.
- Drive classes: `hdd`, `ssd` (SATA or SAS, by rotation rate), `nvme`. Unknown rotation rate is treated as `hdd`.
- Three severities, defined by the action they ask for:

  | Severity | Meaning | Proxmox VE severity |
  | --- | --- | --- |
  | notice | Worth knowing. No action needed now. | `notice` |
  | warning | Plan a replacement or fix the cause. | `warning` |
  | critical | Replace now. The drive reports failure or is very likely to fail. | `error` |

- A check can have a threshold for each severity, or be a plain flag with one fixed severity.
- Every threshold and the enabled state of every check can be overridden globally and per drive ([ADR 0011](0011-configuration.md)).
- The living list of checks and defaults is [`docs/check-catalog.md`](../check-catalog.md). This record fixes the model and the reasoning behind the initial numbers.

### Principles for the defaults

1. **The drive's own failure verdict is always critical**: failed health status, a pre-fail attribute at or below its vendor threshold, NVMe spare below threshold, NVMe read-only or reliability-degraded.
2. **Raw defect counters of hard disks** get thresholds from the observed failure rates: warning where the rate clearly leaves that of clean drives, critical where it is several times higher again. The source data counts drives as failed that were replaced because of these very attributes, so the rates overstate the risk. The critical thresholds are therefore set on the cautious side of what the table suggests.
3. **Any increase of a defect counter is reported as worsening**, subject to the cool-down. The trend matters more than the absolute number.
4. **Cumulative counters with harmless history** (CRC errors, error log count) are events relative to a baseline. Their old values never alert.
5. **Wear never becomes critical by default.** It is capped at warning. The failure signal for flash is the spare capacity.
6. **Temperature** is evaluated against class-specific limits and needs confirmation in two consecutive runs. Temperature attributes are excluded from the "attribute failing" check to avoid the well-known noise.
7. **Counters known to be unreliable** are off by default: the NVMe error log count, unsafe shutdowns, and raw values of the read error rate and seek error rate attributes.
8. **Self-tests are read, never started** ([ADR 0012](0012-read-only-and-coexistence-with-smartd.md)). A failed self-test in the log is a warning.

### Initial numbers and their reasons

| Check | notice | warning | critical | Reason |
| --- | --- | --- | --- | --- |
| Reallocated sectors (5) | 1 | 5 | 70 | Observed annual failure rate: 1–4 about 2.7 % (like clean drives), 4–16 about 7.5 %, 16–70 about 24 %, above 70 at least 36 % |
| Reported uncorrectable (187) | – | 1 | 20 | From the first error about 34 %, above 20 at least 84 % |
| Current pending sectors (197) | – | 1 | 16 | 1–2 about 34 %, above 16 at least 96 % |
| Offline uncorrectable (198) | – | 1 | 10 | From the first sector above 80 %, above 10 well above 100 % |
| Command timeouts (188) | – | 100 | – | Up to 100 like clean drives, above about 10 % |
| Spin retries (10), end-to-end errors (184) | – | 1 | – | Treated as critical attributes by Scrutiny; no rate table used |
| CRC errors (199) | event | – | – | Cable or backplane; only an increase counts |
| Wear, all SSD types | 80 % | 95 % | – | Planning signal; values above 100 % are legal for NVMe |
| NVMe available spare | – | threshold + 15 points | at or below threshold | The threshold is the drive's own; the margin gives lead time |
| NVMe media errors | – | 1 | – | Unrecovered data integrity errors; every increase is reported |
| SAS grown defects | 1 | 100 | – | No public rate data; working drives with dozens of defects exist; growth is reported |
| SAS uncorrected errors | – | 1 | – | Corrected errors are normal, uncorrected are not |
| Temperature HDD | – | 50 °C | 60 °C | Typical operating limit 55 to 60 °C |
| Temperature SATA/SAS SSD | – | 60 °C | 70 °C | Typical operating limit 70 °C |
| Temperature NVMe | – | 70 °C | 80 °C | Typical warning thresholds of drives are 70 to 85 °C |

The same numbers apply to SATA SSDs for the defect counters, because no better data was found. This is recorded as an open question.

All numbers are **provisional**. They are reviewed against recorded data in the milestone that implements the checks, and they can change without a new decision record as long as the model and the principles hold.

### What is deliberately not evaluated

- Normalized values compared with thresholds of the tool's own invention. Normalization is vendor-specific.
- Performance attributes.
- Power-on hours, power cycles and start-stop counts. They are shown in notifications as context.
- The state of pools, arrays and logical volumes.

## Consequences

- An administrator can see for every alert which check fired, with which value and which threshold, and can change or disable exactly that check for exactly that drive.
- The defaults will alert on drives that smartd and the web interface consider healthy. That is the purpose, and the first-run summary absorbs the initial burst.
- The defaults for hard disks have a published basis. Those for SATA SSDs, SAS and temperature rest on judgment and need feedback from real fleets.
- New checks can be added without touching existing ones. Each needs a fixture that triggers it ([ADR 0016](0016-test-strategy.md)).
- The catalog is a public interface: check identifiers appear in configuration files and must stay stable. Renaming one is a breaking change.

## Revisit when

- Data on SSD or SAS failure indicators becomes available.
- Feedback shows that a default is too noisy or too quiet.
- Proxmox VE ships smartmontools 7.5 or later; vendor-neutral wear and spare values would simplify two checks.
