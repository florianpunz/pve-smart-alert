# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the host tells about a drive besides smartctl, best effort (ADR 0005).

`lsblk` is read once per run, from the database of udev, which does not wake
a drive. It gives the transport, the removable flag, the type of a device,
its vendor and model, and what uses it. The links below `/dev/disk` give the
`by-id` and `by-path` names, and sysfs the transport of an NVMe controller
and the driver of a SCSI host. When any of it is missing, the drive is still
monitored, only without these details (FR-110).

A drive behind a RAID controller, read with a pass-through type such as
`sat+megaraid,14` on `/dev/bus/6`, is not a block device of the host: what
lsblk says about the device node is about the controller or a logical
volume, not about the drive. Its location is the controller, with the driver
of its SCSI host, and the device ID of the type (ADR 0028).

The volume group of a drive is read from the device-mapper names of its LVM
devices, as Research 06 verified against `pvs` on the test cluster: the name
up to the first single dash, with each doubled dash reduced to one. `pvs`
itself is not called; it reads labels from the disks. A ZFS pool is taken
from the label of a `zfs_member` file system and an md array from the name
of a `raid` device on the disk or its partitions; both are assumed (Q-S6).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

from pve_smart_alert.model import Location, Membership, pass_through_id
from pve_smart_alert.paths import DISK_LINKS_DIR, LSBLK_PATH, SYSFS_DIR
from pve_smart_alert.process import ProcessRunner, run_with_timeout

# The columns of lsblk this tool reads. Named explicitly: the set of `-O`
# changes between versions of util-linux.
# VENDOR and MODEL are the inquiry data of a SCSI device, which name a
# logical volume of a RAID controller (ADR 0028).
LSBLK_COLUMNS: Final = "NAME,KNAME,TYPE,TRAN,RM,HOTPLUG,FSTYPE,LABEL,VENDOR,MODEL"
LSBLK_TIMEOUT_SECONDS: Final = 10.0

# Transports on which the drive belongs to another host (FR-107). The names
# are those of lsblk for SCSI hosts and those of the kernel for NVMe over
# Fabrics; both are assumed (Q-S6).
REMOTE_TRANSPORTS: Final = frozenset({"iscsi", "fc"})
REMOTE_NVME_TRANSPORTS: Final = frozenset({"tcp", "rdma", "fc", "loop"})

# Device types of lsblk that are not disks (FR-107).
NOT_DISKS: Final = frozenset({"rom", "tape"})

_NVME_CONTROLLER: Final = re.compile(r"nvme[0-9]+")
# The device node through which smartctl reaches the drives of the SCSI host
# H with a MegaRAID controller. The pass-through types that address one drive
# behind it are read by `pass_through_id` of the model.
_SCSI_HOST_NODE: Final = re.compile(r"/dev/bus/([0-9]+)")
_VOLUME_GROUP: Final = re.compile(r"((?:[^-]|--)+)-")


@dataclass(frozen=True)
class HostPaths:
    """Where enrichment reads, so that tests can point it elsewhere (ADR 0014)."""

    lsblk: Path = LSBLK_PATH
    disk_links: Path = DISK_LINKS_DIR
    sysfs: Path = SYSFS_DIR


# The paths of an installed host.
HOST: Final = HostPaths()


@dataclass(frozen=True)
class BlockDevices:
    """The block devices of the host, by kernel name, as lsblk reported them."""

    devices: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True)
class Details:
    """What enrichment found about one device of the scan."""

    location: Location = field(default_factory=Location)
    membership: Membership = field(default_factory=Membership)
    lsblk_type: str | None = None
    # The inquiry data lsblk shows for the device, trimmed (ADR 0028).
    vendor: str | None = None
    model: str | None = None
    # Whether the name is a block device of the host, not a pass-through path.
    block_device: bool = False


def lsblk_command(paths: HostPaths) -> list[str]:
    return [str(paths.lsblk), "--json", "--output", LSBLK_COLUMNS]


def read_block_devices(
    paths: HostPaths = HOST, *, runner: ProcessRunner = run_with_timeout
) -> BlockDevices:
    """Run lsblk and return its devices; an error is reported, not raised."""
    try:
        result = runner(lsblk_command(paths), timeout=LSBLK_TIMEOUT_SECONDS)
    except OSError as failure:
        return BlockDevices(error=f"lsblk could not be started: {failure.strerror or failure}")
    if not result.ok:
        return BlockDevices(error="lsblk did not answer")
    return parse_block_devices(result.stdout)


def parse_block_devices(stdout: str) -> BlockDevices:
    """Return the devices of the JSON of `lsblk --json`, children included."""
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        return BlockDevices(error="lsblk answered without valid JSON")
    roots = document.get("blockdevices") if isinstance(document, dict) else None
    if not isinstance(roots, list):
        return BlockDevices(error="lsblk answered without a list of devices")

    devices: dict[str, Mapping[str, object]] = {}
    for node in _walk(roots):
        name = node.get("kname") or node.get("name")
        if isinstance(name, str):
            devices.setdefault(name, node)
    return BlockDevices(devices=devices)


def details_of(
    name: str,
    block_devices: BlockDevices,
    paths: HostPaths = HOST,
    *,
    device_type: str = "",
) -> Details:
    """Return what the host tells about the device with this name and type."""
    device_id = pass_through_id(device_type)
    if device_id is not None:
        return Details(location=Location(controller=_controller(name, paths), device_id=device_id))

    base = PurePosixPath(name).name
    disks = _disks(base, block_devices)
    if not disks:
        node = block_devices.devices.get(base)
        kind = node.get("type") if node is not None else None
        return Details(lsblk_type=kind if isinstance(kind, str) else None)

    first = disks[0]
    transport = _text(first, "tran")
    if _NVME_CONTROLLER.fullmatch(base):
        transport = _nvme_transport(base, paths) or transport
    location = Location(
        transport=transport,
        removable=_truth(first.get("rm")) or _truth(first.get("hotplug")),
        by_id=tuple(link for disk in disks for link in _links(paths, "by-id", disk)),
        by_path=next((link for disk in disks for link in _links(paths, "by-path", disk)), None),
    )
    return Details(
        location=location,
        membership=_membership(disks),
        lsblk_type=_text(first, "type"),
        vendor=_trimmed(first, "vendor"),
        model=_trimmed(first, "model"),
        block_device=True,
    )


def scsi_host_driver(host: int | str, paths: HostPaths = HOST) -> str | None:
    """Return the driver of a SCSI host, such as `megaraid_sas`, best effort.

    It is the `proc_name` of the host in sysfs; `None` when that is missing
    or empty.
    """
    try:
        text = (paths.sysfs / "class" / "scsi_host" / f"host{host}" / "proc_name").read_text()
    except OSError:
        return None
    return text.strip() or None


def is_remote(details: Details, name: str) -> bool:
    """Whether a device is reached over a network transport (FR-107)."""
    transport = details.location.transport
    if transport is None:
        return False
    if _NVME_CONTROLLER.fullmatch(PurePosixPath(name).name):
        return transport in REMOTE_NVME_TRANSPORTS
    return transport in REMOTE_TRANSPORTS


def volume_group_of(device_mapper_name: str) -> str | None:
    """Return the volume group in the name of an LVM device, such as `pm961--a-data`."""
    match = _VOLUME_GROUP.match(device_mapper_name)
    return match.group(1).replace("--", "-") if match is not None else None


def _disks(base: str, block_devices: BlockDevices) -> list[Mapping[str, object]]:
    """Return the disks of a device name: the disk, or the namespaces of an NVMe controller."""
    node = block_devices.devices.get(base)
    if node is not None:
        return [node] if node.get("type") == "disk" else []
    if _NVME_CONTROLLER.fullmatch(base):
        namespace = re.compile(rf"{base}n[0-9]+")
        return [
            node
            for name, node in sorted(block_devices.devices.items())
            if namespace.fullmatch(name) and node.get("type") == "disk"
        ]
    return []


def _membership(disks: Sequence[Mapping[str, object]]) -> Membership:
    """Return what the host builds on these disks.

    The volume groups come from every LVM device below a disk. A ZFS pool or
    an md array counts only on the disk itself or on its partitions: below a
    logical volume, lsblk also shows the file systems inside the disks of
    guests, such as the pool `zroot` of a virtual machine on the test cluster
    (Research 06).
    """
    groups: list[str] = []
    pools: list[str] = []
    arrays: list[str] = []
    for node in _walk(disks):
        name = _text(node, "name")
        if _text(node, "type") == "lvm" and name is not None:
            group = volume_group_of(name)
            if group is not None:
                groups.append(group)
    for node in _own_devices(disks):
        label = _text(node, "label")
        if _text(node, "fstype") == "zfs_member" and label:
            pools.append(label)
        for child in _children(node):
            kind, name = _text(child, "type"), _text(child, "name")
            if kind is not None and kind.startswith("raid") and name is not None:
                arrays.append(name)
    return Membership(
        zfs_pool=_joined(pools),
        md_array=_joined(arrays),
        volume_group=_joined(groups),
    )


def _own_devices(disks: Sequence[Mapping[str, object]]) -> Iterator[Mapping[str, object]]:
    """Return the disks and their partitions."""
    for disk in disks:
        yield disk
        yield from (child for child in _children(disk) if _text(child, "type") == "part")


def _children(node: Mapping[str, object]) -> list[Mapping[str, object]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, Mapping)]


def _joined(values: Sequence[str]) -> str | None:
    unique = list(dict.fromkeys(values))
    return ", ".join(unique) if unique else None


def _links(paths: HostPaths, kind: str, disk: Mapping[str, object]) -> Iterator[str]:
    """Return the links below /dev/disk/KIND that point to the disk itself."""
    name = _text(disk, "kname") or _text(disk, "name")
    directory = paths.disk_links / kind
    if name is None or not directory.is_dir():
        return
    for link in sorted(directory.iterdir()):
        try:
            target = link.readlink()
        except OSError:
            continue
        if PurePosixPath(target).name == name:
            yield str(link)


def _controller(name: str, paths: HostPaths) -> str:
    """Return the controller of a drive read through `name`: the device node and its driver.

    On `/dev/bus/H` the driver is the one of SCSI host H, where sysfs has it.
    """
    node = _SCSI_HOST_NODE.fullmatch(name)
    driver = scsi_host_driver(node.group(1), paths) if node is not None else None
    return f"{name} ({driver})" if driver is not None else name


def _nvme_transport(controller: str, paths: HostPaths) -> str | None:
    try:
        text = (paths.sysfs / "class" / "nvme" / controller / "transport").read_text()
    except OSError:
        return None
    return text.strip() or None


def _walk(nodes: Sequence[object]) -> Iterator[Mapping[str, object]]:
    """Return every device and its children, depth first."""
    for node in nodes:
        if isinstance(node, Mapping):
            yield node
            children = node.get("children")
            if isinstance(children, list):
                yield from _walk(children)


def _text(node: Mapping[str, object], key: str) -> str | None:
    value = node.get(key)
    return value if isinstance(value, str) else None


def _trimmed(node: Mapping[str, object], key: str) -> str | None:
    """Return a value of lsblk with its padding removed; inquiry data are padded."""
    value = _text(node, key)
    if value is None:
        return None
    return " ".join(value.split()) or None


def _truth(value: object) -> bool:
    """Return a flag of lsblk, which newer versions write as a boolean and older as "0" or "1"."""
    return value is True or value == "1" or value == 1
