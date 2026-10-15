# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test of the failure reporter, the script of pve-smart-alert-failure.service.

The script runs with a stand-in for the mail command and for journalctl and
with a temporary runtime directory, so it needs neither root nor a mail
system nor systemd (ADR 0016). What systemd hands it about the failed run
is set in the environment, as systemd 251 and later set it for a unit started
through OnFailure= (systemd.exec(5)).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
REPORTER = REPOSITORY / "libexec" / "report-failure"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="a shell is needed to run the reporter"
)

# A mail command that keeps its arguments and the message, one file per mail.
FAKE_SENDMAIL = """\
#!/bin/sh
count=$(ls "{mails}" | wc -l)
echo "$@" > "{mails}/$count.args"
cat > "{mails}/$count.mail"
exit {status}
"""

# A journalctl that answers with two lines for the run it is asked about.
FAKE_JOURNALCTL = """\
#!/bin/sh
echo "$@" > "{directory}/journalctl.args"
echo "2026-10-15T10:00:00+0000 pve1 pve-smart-alert[1234]: Traceback (most recent call last):"
echo "2026-10-15T10:00:00+0000 pve1 pve-smart-alert[1234]: OSError: broken on purpose"
"""

FAILED_RUN = {
    "MONITOR_UNIT": "pve-smart-alert.service",
    "MONITOR_SERVICE_RESULT": "exit-code",
    "MONITOR_EXIT_CODE": "exited",
    "MONITOR_EXIT_STATUS": "1",
    "MONITOR_INVOCATION_ID": "0123456789abcdef0123456789abcdef",
}


def today() -> date:
    """Return the day the reporter names its stamp after."""
    return datetime.now(UTC).date()


class Host:
    """A runtime directory, a mail command and a journal for the reporter."""

    def __init__(self, directory: Path, *, sendmail_status: int = 0) -> None:
        self.directory = directory
        self.run_dir = directory / "run"
        self.mails = directory / "mails"
        self.mails.mkdir()
        self.sendmail = self._script(
            "sendmail", FAKE_SENDMAIL.format(mails=self.mails, status=sendmail_status)
        )
        self.journalctl = self._script("journalctl", FAKE_JOURNALCTL.format(directory=directory))

    def _script(self, name: str, content: str) -> Path:
        path = self.directory / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        return path

    def report(
        self, monitor: dict[str, str] | None = None, *, sendmail: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the reporter as the failure unit would, and return the process."""
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            # The stamp is named after the local day, which UTC makes the
            # same day as the one the test expects.
            "TZ": "UTC",
            "PVE_SMART_ALERT_RUN_DIR": str(self.run_dir),
            "PVE_SMART_ALERT_SENDMAIL": str(sendmail or self.sendmail),
            "PVE_SMART_ALERT_JOURNALCTL": str(self.journalctl),
            **(FAILED_RUN if monitor is None else monitor),
        }
        return subprocess.run(
            ["sh", str(REPORTER)],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def sent(self) -> list[str]:
        """Return the messages handed to the mail command, in order."""
        return [
            path.read_text(encoding="utf-8")
            for path in sorted(self.mails.glob("*.mail"), key=lambda path: int(path.stem))
        ]

    def stamp(self, day: date | None = None) -> Path:
        return self.run_dir / f"failure-reported-{(day or today()).isoformat()}"


def test_a_failure_is_reported_to_root(tmp_path: Path) -> None:
    host = Host(tmp_path)

    process = host.report()

    assert process.returncode == 0, process.stderr
    [mail] = host.sent()
    headers, _, body = mail.partition("\n\n")
    assert "To: root" in headers.splitlines()
    assert any(
        line.startswith("Subject: PVE SMART Alert: a run failed on ")
        for line in headers.splitlines()
    )
    assert "Auto-Submitted: auto-generated" in headers.splitlines()
    assert "Unit:    pve-smart-alert.service" in body
    assert "Result:  exit-code" in body
    assert "Exit:    exited 1" in body
    # The same arguments the mail transport of the tool uses.
    assert (host.mails / "0.args").read_text(encoding="utf-8").split() == ["-i", "-t"]


def test_the_report_carries_the_last_lines_of_the_failed_run(tmp_path: Path) -> None:
    host = Host(tmp_path)

    host.report()

    [mail] = host.sent()
    assert "OSError: broken on purpose" in mail
    arguments = (tmp_path / "journalctl.args").read_text(encoding="utf-8").split()
    assert "_SYSTEMD_INVOCATION_ID=0123456789abcdef0123456789abcdef" in arguments


def test_a_second_failure_on_the_same_day_sends_nothing(tmp_path: Path) -> None:
    host = Host(tmp_path)

    host.report()
    process = host.report()

    assert process.returncode == 0
    assert len(host.sent()) == 1
    assert "already reported today" in process.stdout


def test_the_stamp_lives_in_the_runtime_directory(tmp_path: Path) -> None:
    host = Host(tmp_path)

    host.report()

    # Under /run on a host, which a reboot empties: one more mail per boot.
    assert [path.name for path in host.run_dir.iterdir()] == [host.stamp().name]


def test_a_stamp_of_an_earlier_day_does_not_hold_back_the_report(tmp_path: Path) -> None:
    host = Host(tmp_path)
    host.run_dir.mkdir()
    yesterday = host.stamp(today() - timedelta(days=1))
    yesterday.touch()
    (host.run_dir / "lock").touch()

    host.report()

    assert len(host.sent()) == 1
    assert not yesterday.exists()
    assert host.stamp().exists()
    # Only the stamps of the reporter are cleaned up.
    assert (host.run_dir / "lock").exists()


def test_without_the_description_of_systemd_the_failure_is_reported_all_the_same(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path)

    process = host.report(monitor={})

    assert process.returncode == 0, process.stderr
    [mail] = host.sent()
    assert "Unit:    pve-smart-alert.service" in mail
    assert "Result:  unknown" in mail
    assert "(not available)" in mail
    assert not (tmp_path / "journalctl.args").exists()


def test_a_mail_command_that_refuses_leaves_no_stamp(tmp_path: Path) -> None:
    host = Host(tmp_path, sendmail_status=75)

    process = host.report()

    assert process.returncode == 1
    assert "refused" in process.stderr
    # The next failure tries again.
    assert not host.stamp().exists()


def test_a_missing_mail_command_is_an_error(tmp_path: Path) -> None:
    host = Host(tmp_path)

    process = host.report(sendmail=tmp_path / "missing")

    assert process.returncode == 1
    assert "the mail command is missing" in process.stderr
    assert not host.stamp().exists()
