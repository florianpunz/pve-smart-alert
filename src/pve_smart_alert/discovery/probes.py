# SPDX-License-Identifier: AGPL-3.0-or-later
"""The probe for the drives behind an HPE Smart Array controller (FR-103, ADR 0032).

A controller in RAID mode hides its physical drives from the device scan of
smartctl. smartctl reaches them through the controller with `-d cciss,N`,
where `N` is the position of the drive in the physical device list of the
controller (`cciss.cpp`: `cciss_getlun` copies entry `N` of the list that
`CISS_REPORT_PHYS` answers with). The probe reads `cciss,0` upwards on the
SCSI generic node of the controller and stops after
`CONSECUTIVE_FAILURES` device IDs in a row that answer nothing, so that an
empty bay ends the probe instead of a run through all 128 IDs that smartctl
accepts (`os_linux.cpp`, 7.5 line 3583).

Only the driver `hpsa` is probed. It is the driver whose hosts smartctl
itself expects `-d cciss,N` on: `is_hpsa_in_raid_mode` compares the
`proc_name` with `hpsa` and asks for the option when the logical volume
reports a RAID level (`os_linux.cpp`, 7.5 lines 3363 to 3414 and 3475 to
3477). The same controllers run with the driver `smartpqi` on other hosts,
and no source or recording shows that the pass-through works there, so such
a host is named in `scan` and `doctor` and is not probed (Q-R2).

The probe is experimental in version 1 and is switched off with
`probe_cciss = false` in `[discovery]`. It reads with the call of every other
drive, `--nocheck=standby` included, so that a drive in standby is not woken
(FR-203).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pve_smart_alert.collect import Collected, Status, collect_drive
from pve_smart_alert.config import SmartctlSettings
from pve_smart_alert.discovery.controllers import ScsiHost
from pve_smart_alert.discovery.enrichment import HOST, HostPaths, sg_node_of_host
from pve_smart_alert.discovery.sources import Candidate, Source
from pve_smart_alert.process import ProcessRunner, run_with_timeout

__all__ = [
    "CONSECUTIVE_FAILURES",
    "MAX_DEVICE_ID",
    "NAMED_DRIVERS",
    "PROBED_DRIVER",
    "HpeController",
    "Probing",
    "hpe_controllers",
    "probe_hpe",
]

#: The driver whose hosts smartctl reaches with `cciss,N` (ADR 0032).
PROBED_DRIVER: Final = "hpsa"

#: The drivers of HPE Smart Array controllers that are named but not probed:
#: no source shows that the pass-through works with them (Q-R2).
NAMED_DRIVERS: Final = frozenset({"smartpqi"})

#: The highest device ID that smartctl accepts for `cciss,N`
#: (`os_linux.cpp`, 7.5 line 3583: "must have 0 <= N <= 127").
MAX_DEVICE_ID: Final = 127

#: How many device IDs in a row may answer nothing before the probe stops
#: (ADR 0032). An ID at or beyond the end of the device list of a controller
#: fails at once, so three in a row keep one drive that answers nothing, such
#: as one that is broken, from ending the probe, at the price of three calls
#: that come back at once.
CONSECUTIVE_FAILURES: Final = 3


class NotProbed(StrEnum):
    """Why a controller was not probed (ADR 0032)."""

    # The probe is switched off in the configuration.
    SWITCHED_OFF = "switched-off"
    # smartctl supports the pass-through only for the driver hpsa.
    DRIVER = "driver"
    # The controller has no SCSI generic node, so the probe has no device.
    NO_NODE = "no-node"


@dataclass(frozen=True)
class HpeController:
    """One HPE Smart Array controller of the host (ADR 0032)."""

    host: int
    driver: str
    # What was read through the controller, `/dev/sg1`, when it was probed.
    node: str | None = None
    # The device IDs that answered, in the order they were probed.
    device_ids: tuple[int, ...] = ()
    reason: NotProbed | None = None

    @property
    def probed(self) -> bool:
        return self.reason is None

    def describe(self) -> str:
        """Return what `scan` and `doctor` say about this controller.

        The result of a probe is added by `scan`, which is where a run says
        what it read.
        """
        head = f"SCSI host {self.host} has the driver {self.driver}"
        if self.reason is None:
            return f"{head} and is probed as cciss,N on {self.node}"
        if self.reason is NotProbed.SWITCHED_OFF:
            return f"{head} and is not probed: the probe is switched off with probe_cciss = false"
        if self.reason is NotProbed.DRIVER:
            return (
                f"{head} and is not probed: smartctl supports -d cciss,N only for the driver"
                " hpsa (ADR 0032); its drives can be added as [[discovery.device]]"
            )
        return f"{head} and is not probed: no SCSI generic node (/dev/sgN) of this host was found"


@dataclass(frozen=True)
class Probing:
    """What the probe did: the controllers it looked at, and the devices it read."""

    controllers: tuple[HpeController, ...] = ()
    readings: tuple[tuple[Candidate, Collected], ...] = ()


def hpe_controllers(
    hosts: Sequence[ScsiHost], *, probe_cciss: bool, paths: HostPaths = HOST
) -> tuple[HpeController, ...]:
    """Return the HPE Smart Array controllers of the host and whether they are probed.

    Nothing is read here, so that `doctor` can name the controllers without
    touching a drive.
    """
    controllers: list[HpeController] = []
    for host in hosts:
        if host.driver is None:
            continue
        if host.driver in NAMED_DRIVERS:
            controllers.append(HpeController(host.number, host.driver, reason=NotProbed.DRIVER))
            continue
        if host.driver != PROBED_DRIVER:
            continue
        if not probe_cciss:
            controllers.append(
                HpeController(host.number, host.driver, reason=NotProbed.SWITCHED_OFF)
            )
            continue
        node = sg_node_of_host(host.number, paths)
        if node is None:
            controllers.append(HpeController(host.number, host.driver, reason=NotProbed.NO_NODE))
            continue
        controllers.append(HpeController(host.number, host.driver, node=node))
    return tuple(controllers)


def probe_hpe(
    hosts: Sequence[ScsiHost],
    *,
    probe_cciss: bool,
    smartctl: SmartctlSettings,
    paths: HostPaths = HOST,
    runner: ProcessRunner = run_with_timeout,
    on_device: Callable[[Candidate], None] | None = None,
) -> Probing:
    """Read the drives behind the HPE Smart Array controllers of this host (FR-103)."""
    controllers = hpe_controllers(hosts, probe_cciss=probe_cciss, paths=paths)
    readings: list[tuple[Candidate, Collected]] = []
    probed: list[HpeController] = []
    for controller in controllers:
        if controller.node is None:
            probed.append(controller)
            continue
        device_ids, found = _read_devices(
            controller.node, smartctl=smartctl, runner=runner, on_device=on_device
        )
        probed.append(
            HpeController(
                controller.host,
                controller.driver,
                node=controller.node,
                device_ids=device_ids,
            )
        )
        readings.extend(found)
    return Probing(tuple(probed), tuple(readings))


def _read_devices(
    node: str,
    *,
    smartctl: SmartctlSettings,
    runner: ProcessRunner,
    on_device: Callable[[Candidate], None] | None,
) -> tuple[tuple[int, ...], list[tuple[Candidate, Collected]]]:
    """Read `cciss,N` from 0 upwards until `CONSECUTIVE_FAILURES` IDs answer nothing."""
    answered: list[int] = []
    readings: list[tuple[Candidate, Collected]] = []
    failures = 0
    for device_id in range(MAX_DEVICE_ID + 1):
        candidate = Candidate(node, f"cciss,{device_id}", Source.PROBE)
        if on_device is not None:
            on_device(candidate)
        collected = collect_drive(node, candidate.type, settings=smartctl, runner=runner)
        if collected.status is Status.UNREADABLE:
            # Either an empty bay or a drive that answers nothing, which cannot
            # be told apart here: both count as a failure (ADR 0032).
            failures += 1
            if failures >= CONSECUTIVE_FAILURES:
                break
            continue
        # A drive that answered, in standby included: it exists, so the probe
        # reads on, and discovery keeps the previous state of a sleeping drive
        # (FR-203).
        failures = 0
        answered.append(device_id)
        readings.append((candidate, collected))
    return tuple(answered), readings
