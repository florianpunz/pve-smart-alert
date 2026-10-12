# Sources of the fixtures

Every fixture has its origin and its license recorded here ([ADR 0016](../../docs/adr/0016-test-strategy.md), NFR-20).
No fixture contains a real serial number or WWN; a test checks every fixture for it.

## Output of smartctl: `smartctl/`

Recordings of whole hosts, one directory per recording under the controller of its drives (`direct` for directly attached drives): `scan.json` from `smartctl --scan-open --json=c`, one file per device from `smartctl -x --json=c -d TYPE DEVICE`, `lsblk.json` from `lsblk -J -O`, and `recording.json` with the origin, the license and the smartmontools version, and the command line, exit status, protocol and class of every file.
They were written by [`scripts/make_fixtures.py`](../../scripts/make_fixtures.py) from the archives of [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh), which stay outside the repository, and are anonymized as [ADR 0023](../../docs/adr/0023-anonymization-of-recordings.md) describes: serial numbers, WWNs, EUI-64s, NGUIDs and UUIDs are replaced by counters in the order of the scan. Nothing else is changed; the JSON is written indented.

| Directory | Origin | Changes | License |
| --- | --- | --- | --- |
| `direct/test-cluster-pve5` | [Research 06](../../docs/research/06-test-cluster-recordings.md): the test cluster of the maintainer, node `pve5`, recorded on 2026-10-05 by the collection script. Fanxiang S301 256GB | Anonymized | AGPL-3.0-or-later |
| `direct/test-cluster-pve6` | Same, node `pve6`. Samsung SSD 750 EVO 500GB, WDC PC SN720 | Anonymized | AGPL-3.0-or-later |
| `direct/test-cluster-pve7` | Same, node `pve7`. Samsung SSD 850 EVO 250GB, two Samsung MZVLW256HEHP (PM961) | Anonymized | AGPL-3.0-or-later |
| `direct/standalone-pve1` | [Research 07](../../docs/research/07-standalone-host-pve1.md): the standalone test host `pve1` of the maintainer, not part of the test cluster, recorded on 2026-10-08 by the collection script. Intenso SSD; a USB device that the scan does not list | Anonymized | AGPL-3.0-or-later |
| `direct/failing-hdd` | Derived by hand from the recording of `test-cluster-pve7`: a hard disk that fails several checks at once, for the tests of the evaluation of milestone M3 and its acceptance step 2. Identity and values replaced, derived on 2026-10-12 | Anonymized and modified | AGPL-3.0-or-later |

## Scenarios: `../scenarios.py`

The scenario tests of the notification policy replay a host whose drives change from run to run ([ADR 0016](../../docs/adr/0016-test-strategy.md)). The steps are not committed as files: `tests/scenarios.py` derives each of them from a recording above when the tests run, or when `python3 tests/scenarios.py build NAME DIRECTORY` writes them for an acceptance run on a real host. Every step is therefore derived, and its license is that of its base recording.

| Scenario | Base | Changes |
| --- | --- | --- |
| `pending-sectors` | `direct/standalone-pve1` | The raw value of attribute 197 set to 3 and to 20, an attribute 197 entry with made-up flags added where the drive has none, and the drive removed from the scan and the recording |
| `five-hot` | `direct/standalone-pve1` | Four copies of the drive as `/dev/sdb` to `/dev/sde` with the serial numbers `ANON-SN-0002` to `ANON-SN-0005` and without WWN, and the temperature of all five set to 65 °C |

## Rendered notifications: `golden/`

The subject and body of every kind of notification, written by the renderer from plans that the tests in `tests/unit/test_render.py` build by hand ([ADR 0016](../../docs/adr/0016-test-strategy.md): rendering is compared with golden files). The drives in them are made up, with the placeholder serial numbers of the anonymization. A change to the text of a notification updates these files: `PVE_SMART_ALERT_UPDATE_GOLDEN=1 make test` writes them, and the diff is reviewed with the change. License AGPL-3.0-or-later.

## Notification configuration: `pvesh/`

The answers of `pvesh get /cluster/notifications/matchers --output-format json` and `pvesh get /cluster/notifications/targets --output-format json`, one directory per configuration, as `matchers.json` and `targets.json`.
The routing check of [ADR 0020](../../docs/adr/0020-routing-check.md) is tested with them.

| Directory | Origin | Changes | License |
| --- | --- | --- | --- |
| `test-cluster-a` | Configuration A of [Research 06](../../docs/research/06-test-cluster-recordings.md): the test cluster of the maintainer, node `pve7`, recorded by hand on 2026-10-05 | Target names replaced | AGPL-3.0-or-later |
| `test-cluster-b` | Configuration B of Research 06, recorded in the same session. The targets were recorded once in that session, so `targets.json` is the one of `test-cluster-a` | Target names replaced | AGPL-3.0-or-later |
| `test-cluster-c` | Configuration C of Research 06: node `pve7`, recorded on 2026-10-05 by [`scripts/collect-node-data.sh`](../../scripts/collect-node-data.sh) | Target names replaced | AGPL-3.0-or-later |
| `builtin-default` | Derived, not recorded: the built-in default configuration of Proxmox VE, `DEFAULT_CONFIG` in `proxmox-notify/src/context/pve.rs` (`master` on 2026-10-06, [Research 01](../../docs/research/01-notification-integration.md)), written in the form of the recorded answers. That an unchanged built-in entry has the origin `builtin` is assumed (Research 06) | Derived | AGPL-3.0-or-later |

The names of targets that the maintainer chose are replaced by `smtp-relay` and `smtp-provider`. The built-in names `default-matcher` and `mail-to-root` are kept.
