#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Collects the raw data of one node: smartctl, lsblk, LVM, the disk list and
# the notification configuration. It only reads (ADR 0012), and the archive
# holds real serial numbers, so it stays out of the repository (ADR 0016).

# Usage as root: sh collect-node-data.sh [LABEL]. The archive is written to
# the current directory and its path is printed at the end.

set -u

LABEL="${1:-}"
NODE="$(hostname)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="pve-smart-alert-data-${NODE}${LABEL:+-$LABEL}-${STAMP}"
WORK="$(mktemp -d)"
OUT="${WORK}/${NAME}"
TIMEOUT=60

mkdir -p "${OUT}/smart"
: > "${OUT}/errors.txt"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this script as root; smartctl needs it to read the drives." >&2
    exit 1
fi

# run FILE COMMAND...: writes stdout to FILE and stderr to FILE.stderr, and
# records a missing command or a non-zero exit status in errors.txt.
run() {
    file="$1"
    shift
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "missing: $1 (for $(basename "$file"))" >> "${OUT}/errors.txt"
        return
    fi
    timeout "${TIMEOUT}" "$@" > "${file}" 2> "${file}.stderr"
    status=$?
    echo "${status}" > "${file}.exit"
    [ -s "${file}.stderr" ] || rm -f "${file}.stderr"
    if [ "${status}" -ne 0 ]; then
        echo "exit ${status}: $*" >> "${OUT}/errors.txt"
    fi
}

echo "Collecting data of node ${NODE} ..."

{
    echo "node: ${NODE}"
    echo "label: ${LABEL}"
    echo "collected: ${STAMP}"
} > "${OUT}/info.txt"

run "${OUT}/pveversion.txt" pveversion -v
run "${OUT}/smartctl-version.txt" smartctl --version
run "${OUT}/scan.json" smartctl --scan-open --json=c

# SMART data of every device of the scan, read with the device type the scan
# reported. smartctl sets bits in its exit status for drive conditions, so a
# non-zero status here is data, not an error of this script.
smartctl --scan-open 2>/dev/null | while read -r dev _ type _; do
    case "${dev}" in
        /dev/*) ;;
        *) continue ;;
    esac
    base="$(basename "${dev}")"
    echo "  ${dev} (${type})"
    run "${OUT}/smart/${base}.json" smartctl -x --json=c -d "${type}" "${dev}"
done

run "${OUT}/lsblk.json" lsblk -J -O
run "${OUT}/pvs.json" pvs --reportformat json -o +pv_uuid
run "${OUT}/vgs.json" vgs --reportformat json
run "${OUT}/lvs.json" lvs --reportformat json -a -o +lv_layout,pool_lv,devices
if command -v zpool >/dev/null 2>&1; then
    run "${OUT}/zpool-status.txt" zpool status -P
    run "${OUT}/zpool-list.txt" zpool list -v -P
fi

# The disk list of the web interface, including the wearout column.
run "${OUT}/pve-disks.json" pvesh get "/nodes/${NODE}/disks/list" --output-format json
run "${OUT}/matchers.json" pvesh get /cluster/notifications/matchers --output-format json
run "${OUT}/targets.json" pvesh get /cluster/notifications/targets --output-format json

# Output of the installed tool. Only commands that send nothing are run.
if command -v pve-smart-alert >/dev/null 2>&1; then
    mkdir -p "${OUT}/tool"
    run "${OUT}/tool/version.txt" pve-smart-alert --version
    run "${OUT}/tool/doctor.txt" pve-smart-alert doctor
    if pve-smart-alert --help 2>/dev/null | grep -q '\bscan\b'; then
        run "${OUT}/tool/scan.txt" pve-smart-alert scan
    fi
else
    echo "missing: pve-smart-alert (the tool is not installed)" >> "${OUT}/errors.txt"
fi

ARCHIVE="$(pwd)/${NAME}.tar.gz"
tar czf "${ARCHIVE}" -C "${WORK}" "${NAME}"
rm -rf "${WORK}"

echo
if [ -s "${ARCHIVE}" ]; then
    echo "Written: ${ARCHIVE}"
fi
echo "The archive contains real serial numbers. Do not commit it."
