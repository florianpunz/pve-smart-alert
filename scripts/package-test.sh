#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# The package test of ADR 0016, layer 4: install the package in a clean
# Debian container with the Proxmox VE package repository, check the
# installed files against ADR 0013, run the tool, purge it and check that
# nothing is left. Runs as root inside a debian:trixie container:
#
#   docker run --rm -v "$PWD:/work" -w /work debian:trixie \
#       sh scripts/package-test.sh dist/pve-smart-alert_0.5.0_all.deb
#
# Not for a real host: it adds the Proxmox VE repository to the container.
set -eu

package=$1
keyring=/usr/share/keyrings/proxmox-archive-keyring.gpg
# The archive key of Proxmox VE 9, the same file that a Proxmox VE 9.2 host
# has at this path (checked on 2026-10-13).
key_url=https://enterprise.proxmox.com/debian/proxmox-archive-keyring-trixie.gpg
key_sha256=136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45

step() { printf '\n=== %s\n' "$*"; }
fail() {
	echo "FAILED: $*" >&2
	exit 1
}

step "the Proxmox VE package repository"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -qq --yes --no-install-recommends ca-certificates wget >/dev/null
wget -q -O "$keyring" "$key_url"
echo "$key_sha256  $keyring" | sha256sum --check --quiet || fail "the archive key of Proxmox VE changed"
cat >/etc/apt/sources.list.d/proxmox.sources <<SOURCES
Types: deb
URIs: http://download.proxmox.com/debian/pve
Suites: trixie
Components: pve-no-subscription
Signed-By: $keyring
SOURCES
apt-get update -qq

step "install $package"
apt-get install -qq --yes "./$package"
dpkg -s pve-smart-alert | grep -E '^(Status|Version):'

step "the installed files (ADR 0013)"
for path in \
	/usr/sbin/pve-smart-alert \
	/usr/share/pve-smart-alert/pve_smart_alert/__init__.py \
	/usr/libexec/pve-smart-alert/notify-bridge \
	/usr/libexec/pve-smart-alert/report-failure \
	/usr/share/pve-manager/templates/default/pve-smart-alert-subject.txt.hbs \
	/usr/share/pve-manager/templates/default/pve-smart-alert-body.txt.hbs \
	/usr/lib/systemd/system/pve-smart-alert.service \
	/usr/lib/systemd/system/pve-smart-alert.timer \
	/usr/lib/systemd/system/pve-smart-alert-failure.service \
	/etc/pve-smart-alert/config.toml \
	/usr/share/doc/pve-smart-alert/config.reference.toml.gz \
	/usr/share/doc/pve-smart-alert/copyright; do
	[ -e "$path" ] || fail "not installed: $path"
	echo "ok $path"
done
[ -L /etc/systemd/system/timers.target.wants/pve-smart-alert.timer ] ||
	fail "the timer is not enabled"
echo "ok the timer is enabled"
if dpkg -L pve-smart-alert | grep -E '__pycache__|\.pyc$'; then
	fail "byte code was installed"
fi

step "the tool runs"
pve-smart-alert --version
pve-smart-alert config check
# Without systemd, pmxcfs and drives several lines fail; the command has to
# answer, not crash.
pve-smart-alert doctor >/tmp/doctor.txt 2>&1 || true
cat /tmp/doctor.txt
grep -q '^bridge:' /tmp/doctor.txt || fail "doctor did not answer"
if grep -q 'Traceback' /tmp/doctor.txt; then
	fail "doctor crashed"
fi
perl -c /usr/libexec/pve-smart-alert/notify-bridge
/usr/libexec/pve-smart-alert/notify-bridge --check || true

step "purge"
apt-get purge -qq --yes pve-smart-alert
for path in \
	/etc/pve-smart-alert \
	/var/lib/pve-smart-alert \
	/usr/share/pve-smart-alert \
	/usr/libexec/pve-smart-alert \
	/usr/sbin/pve-smart-alert \
	/usr/share/pve-manager/templates/default/pve-smart-alert-subject.txt.hbs \
	/usr/share/pve-manager/templates/default/pve-smart-alert-body.txt.hbs \
	/usr/lib/systemd/system/pve-smart-alert.timer \
	/etc/systemd/system/timers.target.wants/pve-smart-alert.timer; do
	if [ -e "$path" ] || [ -L "$path" ]; then
		fail "left after purge: $path"
	fi
done
if dpkg -l pve-smart-alert 2>/dev/null | grep -q '^[ir]'; then
	fail "the package is still known to dpkg"
fi
echo "ok nothing is left"

step "the package test passed"
