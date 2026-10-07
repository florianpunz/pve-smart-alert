#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fake smartctl that replays a recording (ADR 0016).

It takes the arguments of smartctl and answers from a recording directory in
the layout of the fixtures (ADR 0023): `scan.json` for the device scan, one
file per device, and `recording.json`, which names the device, the type and
the exit status of every file. The directory is given in the environment
variable FAKE_SMARTCTL_RECORDING.

An optional `behavior.json` in the same directory changes the answer for
one file, by its name:

    {"sda.json": {"delay_seconds": 5}}        answers late, or hangs
    {"sda.json": {"standby": "STANDBY"}}      sleeps, when asked not to wake it
    {"sda.json": {"stdout": "...", "exit_status": 4}}   answers with this

A device the recording does not have fails to open, modelled on smartctl
("Smartctl open device: NAME failed: No such device", exit status 2). With
FAKE_SMARTCTL_LOG set, every call is appended to that file as one JSON line.

Only the standard library is used, so that the fake runs with any Python 3.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

RECORDING_VARIABLE: Final = "FAKE_SMARTCTL_RECORDING"
LOG_VARIABLE: Final = "FAKE_SMARTCTL_LOG"
FAILPOWER: Final = 2


def main(argv: Sequence[str]) -> int:
    recording = Path(os.environ[RECORDING_VARIABLE])
    _log(argv)
    files = json.loads((recording / "recording.json").read_text(encoding="utf-8"))["files"]
    behavior = _behavior(recording)

    if "--scan-open" in argv or "--scan" in argv:
        scan = next(entry for entry in files if entry["file"] == "scan.json")
        return _answer(recording, scan, behavior.get("scan.json", {}), argv)

    name, device_type = argv[-1], _device_type(argv)
    for entry in files:
        if entry.get("device") == name and entry.get("type") == device_type:
            return _answer(recording, entry, behavior.get(entry["file"], {}), argv)
    _print(
        _message_document(argv, f"Smartctl open device: {name} failed: No such device", "error", 2)
    )
    return 2


def _answer(
    recording: Path,
    entry: Mapping[str, object],
    behavior: Mapping[str, object],
    argv: Sequence[str],
) -> int:
    delay = behavior.get("delay_seconds")
    if isinstance(delay, (int, float)):
        time.sleep(delay)

    mode = behavior.get("standby")
    if isinstance(mode, str) and "--nocheck=standby" in argv:
        document = _message_document(argv, f"Device is in {mode} mode, exit(2)", "information", 2)
        document["power_mode"] = {"ata_value": 0, "name": mode}
        _print(document)
        return FAILPOWER

    stdout = behavior.get("stdout")
    status = behavior.get("exit_status", entry.get("exit_status") or 0)
    if isinstance(stdout, str):
        sys.stdout.write(stdout)
    else:
        name = str(entry["file"])
        _print(json.loads((recording / name).read_text(encoding="utf-8")))
    return status if isinstance(status, int) else 0


def _message_document(
    argv: Sequence[str], message: str, severity: str, status: int
) -> dict[str, object]:
    return {
        "json_format_version": [1, 0],
        "smartctl": {
            "version": [7, 5],
            "argv": ["smartctl", *argv],
            "messages": [{"string": message, "severity": severity}],
            "exit_status": status,
        },
    }


def _device_type(argv: Sequence[str]) -> str | None:
    for index, argument in enumerate(argv):
        if argument.startswith("--device="):
            return argument.removeprefix("--device=")
        if argument in ("-d", "--device") and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _behavior(recording: Path) -> dict[str, dict[str, object]]:
    path = recording / "behavior.json"
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _print(document: object) -> None:
    # smartctl --json=c writes one compact line.
    sys.stdout.write(json.dumps(document, separators=(",", ":")) + "\n")


def _log(argv: Sequence[str]) -> None:
    path = os.environ.get(LOG_VARIABLE)
    if path:
        with Path(path).open("a", encoding="utf-8") as log:
            log.write(json.dumps(list(argv)) + "\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
