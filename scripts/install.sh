#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Installs PVE SMART Alert on a Proxmox VE host (ADR 0013).
#
#   wget -qO- https://github.com/florianpunz/pve-smart-alert/releases/latest/download/install.sh | sh
#
# It downloads the package and SHA256SUMS of a release, verifies the package
# against its checksum and installs it with apt. Everything that changes the
# system is done by the package; this script changes nothing else.
#
# PVE_SMART_ALERT_VERSION=0.5.0 installs that version instead of the newest.
# PVE_SMART_ALERT_BASE_URL replaces the download location, for a mirror.
set -eu

repository="https://github.com/florianpunz/pve-smart-alert"
version="${PVE_SMART_ALERT_VERSION:-}"

if [ -n "$version" ]; then
	case "$version" in
	*[!0-9A-Za-z.~+-]*)
		echo "pve-smart-alert: not a version: $version" >&2
		exit 1
		;;
	esac
	base="${PVE_SMART_ALERT_BASE_URL:-$repository/releases/download/v$version}"
	package="pve-smart-alert_${version}_all.deb"
else
	base="${PVE_SMART_ALERT_BASE_URL:-$repository/releases/latest/download}"
	package="pve-smart-alert.deb"
fi

if [ "$(id -u)" -ne 0 ]; then
	echo "pve-smart-alert: run this as root" >&2
	exit 1
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

echo "pve-smart-alert: downloading $base/$package"
wget -q -O "$work/$package" "$base/$package"
wget -q -O "$work/SHA256SUMS" "$base/SHA256SUMS"

# Only the line of the downloaded package counts; a missing line is an error.
if ! grep -E "^[0-9a-f]{64}  $package\$" "$work/SHA256SUMS" >"$work/expected"; then
	echo "pve-smart-alert: SHA256SUMS has no checksum for $package" >&2
	exit 1
fi
if ! (cd "$work" && sha256sum --check --quiet expected); then
	echo "pve-smart-alert: the checksum of $package does not match; nothing was installed" >&2
	exit 1
fi

# apt reads a local package as the unprivileged user _apt where it can.
chmod 755 "$work"
chmod 644 "$work/$package"
apt install --yes "$work/$package"
echo "pve-smart-alert: installed; the first check runs now, see: pve-smart-alert status"
