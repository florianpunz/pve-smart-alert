# SPDX-License-Identifier: AGPL-3.0-or-later
#
# A stub of PVE::Notify for the contract test of the notify bridge (ADR 0016).
# It neither knows Proxmox VE nor sends anything.
#
# Every call is appended to the file named by PVE_SMART_ALERT_STUB_LOG, one
# JSON document per line. How the stub behaves is chosen by
# PVE_SMART_ALERT_STUB_MODE, which is read when the module is loaded:
#
#   ok                  one target got the message (default)
#   all-targets-failed  every matched target failed
#   render-failed       the template could not be rendered
#   die                 the call dies instead of returning
#   no-notify           the module does not offer notify() at all
#   no-common           the module does not offer common_template_data()

package PVE::Notify;

use strict;
use warnings;
use JSON::PP;

sub _mode {
    return $ENV{PVE_SMART_ALERT_STUB_MODE} // 'ok';
}

sub _record {
    my ($severity, $template, $data, $fields) = @_;
    my $path = $ENV{PVE_SMART_ALERT_STUB_LOG};
    return unless defined $path && length $path;

    open my $handle, '>>', $path or die "cannot append to $path: $!";
    print {$handle} JSON::PP->new->utf8->canonical->encode(
        {
            severity => $severity,
            template => $template,
            data     => $data,
            fields   => $fields,
        }
    ), "\n";
    close $handle;
}

sub _notify {
    my ($severity, $template, $data, $fields) = @_;
    my $mode = _mode();

    _record($severity, $template, $data, $fields);

    die "the stub was told to die\n" if $mode eq 'die';
    if ($mode eq 'render-failed') {
        print STDERR "failed to render notification template '$template':"
            . " all template candidates are erroneous or missing\n";
    } elsif ($mode eq 'all-targets-failed') {
        print STDERR "could not notify via target 'mail-to-root'\n";
    } elsif ($mode eq 'ok') {
        print STDERR "notified via target 'mail-to-root'\n";
    }
}

sub _common_template_data {
    return { hostname => 'pve1', fqdn => 'pve1.example.test', 'cluster-name' => 'test' };
}

# A module without notify() has to be built at run time: a named sub inside a
# conditional block would be installed at compile time all the same.
*notify = \&_notify if _mode() ne 'no-notify';
*common_template_data = \&_common_template_data if _mode() ne 'no-common';

1;
