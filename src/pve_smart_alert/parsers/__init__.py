# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translating the JSON of smartctl into snapshots (ADR 0004).

One parser per protocol. A missing key leaves its value out, which makes the
checks that need it not applicable (FR-206). `collect.py`,
`discovery/sources.py`, `dump.py`, `recording.py` and `scripts/make_fixtures.py`,
for example, read smartctl JSON without building a snapshot.
"""

from __future__ import annotations

from collections.abc import Mapping

from pve_smart_alert.model import Collection, DeviceAccess, Snapshot
from pve_smart_alert.parsers import ata, nvme, scsi
from pve_smart_alert.parsers.common import ParseError, protocol_of
from pve_smart_alert.parsers.scsi import Inquiry, inquiry_of

__all__ = ["Inquiry", "ParseError", "inquiry_of", "parse", "protocol_of"]


def parse(
    document: Mapping[str, object], *, access: DeviceAccess, collection: Collection
) -> Snapshot:
    """Return the snapshot of one drive output of smartctl.

    Raises `ParseError` for a protocol without a parser, and for an output
    without a model name.
    """
    protocol = protocol_of(document) or access.protocol
    if protocol == "ATA":
        return ata.parse(document, access=access, collection=collection)
    if protocol == "NVMe":
        return nvme.parse(document, access=access, collection=collection)
    if protocol == "SCSI":
        return scsi.parse(document, access=access, collection=collection)
    raise ParseError(f"no parser for the protocol {protocol or 'that smartctl did not name'}")
