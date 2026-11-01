# SPDX-License-Identifier: AGPL-3.0-or-later
"""The run time of a run with many drives (NFR-07).

NFR-07 asks that a run on a host with 24 responsive drives completes within
60 seconds. The scenario `twenty-four-drives` makes 24 drives of one recorded
SATA SSD; the run is the command as the timer starts it, against the fake
smartctl, with an injected clock, a temporary state directory and a
recording transport. The bound is generous on purpose: the test guards
against a run that grows with a per-drive delay, not against a slow machine.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from frame import ScenarioHost

from pve_smart_alert import cli
from pve_smart_alert.model import EventType

#: The number of drives of NFR-07.
DRIVES = 24

#: The bound of NFR-07, in seconds.
LIMIT_SECONDS = 60.0


@pytest.fixture
def host(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScenarioHost:
    scenario = ScenarioHost(tmp_path, monkeypatch, "twenty-four-drives")
    scenario.install()
    return scenario


def test_a_run_with_24_drives_completes_within_a_minute(host: ScenarioHost) -> None:
    started = time.monotonic()
    (summary,) = host.run("01-healthy")
    elapsed = time.monotonic() - started

    assert host.exit_status == cli.EXIT_OK
    assert summary.event is EventType.FIRST_RUN
    for number in range(1, DRIVES + 1):
        assert f"ANON-SN-{number:04d}" in summary.body
    assert len(host.read_devices()) == DRIVES
    assert elapsed < LIMIT_SECONDS, f"a run with {DRIVES} drives took {elapsed:.1f} seconds"
