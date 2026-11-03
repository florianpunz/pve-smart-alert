#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Installs PVE SMART Alert on a Proxmox VE host (ADR 0013):
#   wget -qO- https://github.com/florianpunz/pve-smart-alert/releases/latest/download/install.sh | sh
# The checksum proves integrity only, not that the package is the intended one.
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

# Only the line of the downloaded package counts, and the name is matched as a
# fixed string: dots in a version make a pattern accept another file's line.
if ! awk -v name="$package" 'length($1) == 64 && $2 == name { print $1 "  " $2 }' \
	"$work/SHA256SUMS" >"$work/expected" || [ ! -s "$work/expected" ]; then
	echo "pve-smart-alert: SHA256SUMS has no checksum for $package" >&2
	exit 1
fi
if ! (cd "$work" && sha256sum --check --quiet expected); then
	echo "pve-smart-alert: the checksum of $package does not match; nothing was installed" >&2
	exit 1
fi

# A mirror can serve any package under the name this script expects, and the
# checksum comes from the same place, so the package itself has to say what it
# is before apt is asked to install it.
if ! package_name=$(dpkg-deb -f "$work/$package" Package 2>/dev/null); then
	echo "pve-smart-alert: $package is not a Debian package" >&2
	exit 1
fi
if [ "$package_name" != pve-smart-alert ]; then
	echo "pve-smart-alert: $package carries the package $package_name, not pve-smart-alert" >&2
	exit 1
fi
if [ -n "$version" ]; then
	package_version=$(dpkg-deb -f "$work/$package" Version)
	if [ "$package_version" != "$version" ]; then
		echo "pve-smart-alert: $package carries the version $package_version, not $version" >&2
		exit 1
	fi
fi

# apt reads a local package as the unprivileged user _apt where it can.
chmod 755 "$work"
chmod 644 "$work/$package"

# What apt did is read from dpkg, not from what apt prints, which is not an
# interface. The state comes with the version: a removed but unpurged package
# has one too, and installing it again is an installation, not a no-op.
installed_state() {
	dpkg-query --show --showformat='${db:Status-Status} ${Version}' pve-smart-alert \
		2>/dev/null || true
}

# "installed 0.5.1" for an installed package, "config-files 0.5.1" for a
# removed one. The full status name is used, not the three-character
# abbreviation, which runs into the version ("ii 0.5.1").
state_of() {
	printf '%s' "${1%% *}"
}

version_of() {
	printf '%s' "${1#* }"
}

is_installed() {
	case "$(state_of "$1")" in
	installed) return 0 ;;
	*) return 1 ;;
	esac
}

before=$(installed_state)
if ! apt install --yes "$work/$package"; then
	echo "pve-smart-alert: apt did not finish; see its output above" >&2
	after=$(installed_state)
	if [ -n "$after" ] && ! is_installed "$after"; then
		case "$(state_of "$after")" in
		unpacked | half-installed | half-configured)
			echo "pve-smart-alert: dpkg reports the package as $(state_of "$after"); 'apt --fix-broken install' may repair it" >&2
			;;
		*)
			echo "pve-smart-alert: dpkg reports the package as $(state_of "$after"); the package is not installed" >&2
			;;
		esac
	fi
	exit 1
fi
after=$(installed_state)

if [ -z "$after" ]; then
	echo "pve-smart-alert: dpkg does not know the package after apt reported success" >&2
	exit 1
fi
if ! is_installed "$after"; then
	echo "pve-smart-alert: dpkg reports the package as $(state_of "$after") after apt reported success" >&2
	exit 1
fi
if [ "$after" = "$before" ]; then
	echo "pve-smart-alert: $(version_of "$after") is installed already, nothing changed"
	exit 0
fi

# What the timer does rests on the postinst, and the script cannot see whether
# systemd runs at all (a container, a chroot): it reports what dpkg holds and
# points at the command that answers the rest.
before_version=$(version_of "$before")
after_version=$(version_of "$after")
if [ -z "$before_version" ]; then
	echo "pve-smart-alert: installed $after_version; see: pve-smart-alert status"
elif [ "$before_version" = "$after_version" ]; then
	echo "pve-smart-alert: installed $after_version again; see: pve-smart-alert status"
elif is_installed "$before"; then
	echo "pve-smart-alert: changed from $before_version to $after_version; see: pve-smart-alert status"
else
	echo "pve-smart-alert: installed $after_version in place of $before_version; see: pve-smart-alert status"
fi
