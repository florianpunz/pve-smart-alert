# Sources of the fixtures

Every fixture has its origin and its license recorded here ([ADR 0016](../../docs/adr/0016-test-strategy.md), NFR-20).
No fixture contains a real serial number or WWN.

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
