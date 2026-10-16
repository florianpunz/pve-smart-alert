# Third-party notices

PVE SMART Alert is licensed under AGPL-3.0-or-later ([LICENSE](LICENSE)).
Some test fixtures are taken from the test data of other projects and keep the license of their source ([ADR 0026](docs/adr/0026-recordings-of-scsi-drives-and-of-other-projects.md)).
None of this data is part of the installed package; it is used by the tests only.

Each such fixture names its source in its `recording.json`: repository, commit, path, copyright and license text.
[`tests/fixtures/SOURCES.md`](tests/fixtures/SOURCES.md) lists them, and the license texts are kept unchanged in [`tests/fixtures/licenses/`](tests/fixtures/licenses/).
The fixtures are modified: identifying values are replaced by placeholders ([ADR 0023](docs/adr/0023-anonymization-of-recordings.md)).

| Project | Copyright | License | License text | Fixtures |
| --- | --- | --- | --- | --- |
| [libblockdev](https://github.com/storaged-project/libblockdev) | Copyright (C) 2014-2023 Red Hat, Inc. | LGPL-2.1-or-later | [`libblockdev-LGPL-2.1.txt`](tests/fixtures/licenses/libblockdev-LGPL-2.1.txt) | `tests/fixtures/smartctl/direct/libblockdev-*` |
| [smartctl_exporter](https://github.com/prometheus-community/smartctl_exporter) | Copyright The Prometheus Authors | Apache-2.0 | [`smartctl_exporter-Apache-2.0.txt`](tests/fixtures/licenses/smartctl_exporter-Apache-2.0.txt) | `tests/fixtures/smartctl/direct/exporter-*` |
| [Scrutiny](https://github.com/AnalogJ/scrutiny) | Copyright (c) 2020 Jason Kulatunga | MIT | [`scrutiny-MIT.txt`](tests/fixtures/licenses/scrutiny-MIT.txt) | `tests/fixtures/smartctl/*/scrutiny-*` |
| [Telegraf](https://github.com/influxdata/telegraf) | Copyright (c) 2015-2025 InfluxData Inc. | MIT | [`telegraf-MIT.txt`](tests/fixtures/licenses/telegraf-MIT.txt) | `tests/fixtures/smartctl/megaraid/telegraf-*` |
