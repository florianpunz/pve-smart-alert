# SPDX-License-Identifier: AGPL-3.0-or-later
"""One run of `pve-smart-alert check` (ARCHITECTURE.md section 3).

Lock, configuration, state, preflight, discovery, collection, evaluation,
presence, planning, delivery, save, summary. Everything the run touches
outside the process is a field of `Environment`, so that a scenario test can
run it with a clock, a state directory, a fake smartctl and a transport of
its own (ADR 0016).

A state change that belongs to a notification is applied only after the
transport handed the notification over (FR-517); the state file is replaced
once, at the end (ADR 0007). With `dry_run`, nothing is locked, sent or
saved, and the state is read without setting a corrupt file aside.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pve_smart_alert.checks import counters, evaluate
from pve_smart_alert.config import (
    Config,
    NotifySettings,
    effective_checks,
    load_effective,
    save_last_good,
    tool_conditions_enabled,
)
from pve_smart_alert.discovery import Candidate, Discovery, HostPaths, Outcome, discover
from pve_smart_alert.discovery.controllers import read_scsi_hosts
from pve_smart_alert.discovery.enrichment import HOST
from pve_smart_alert.model import Finding, Notification, Severity, node_name
from pve_smart_alert.paths import (
    BRIDGE_PATH,
    CONFIG_PATH,
    COROSYNC_CONF_PATH,
    LAST_GOOD_CONFIG_PATH,
    LOCK_PATH,
    STATE_PATH,
)
from pve_smart_alert.planner import (
    DriveSeen,
    Observation,
    Plan,
    Planned,
    Presence,
    SkippedSeen,
    plan,
)
from pve_smart_alert.process import ProcessRunner, run_with_timeout
from pve_smart_alert.render import RenderContext, cluster_name, render
from pve_smart_alert.state import (
    Access,
    LastRun,
    State,
    identity_key,
    load_state,
    read_state,
    save_state,
)
from pve_smart_alert.tool_conditions import (
    UNSUPPORTED_CONTROLLER,
    config_invalid,
    scan_failed,
    smartctl_missing,
    smartctl_too_old,
    transport_degraded,
    unsupported_controller,
)
from pve_smart_alert.transports import Transport, TransportOutcome, build_transport

__all__ = ["Delivery", "Environment", "LockedError", "RunResult", "run_check"]

# The result of a run as the state file and the summary line name it.
RESULT_OK: Final = "ok"
RESULT_UNDELIVERED: Final = "notifications not delivered"


class LockedError(Exception):
    """Another run holds the lock (FR-605)."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Environment:
    """What a run touches outside the process. The defaults are those of a host."""

    config_path: Path = CONFIG_PATH
    last_good: Path = LAST_GOOD_CONFIG_PATH
    state_path: Path = STATE_PATH
    lock_path: Path = LOCK_PATH
    bridge_path: Path = BRIDGE_PATH
    corosync_path: Path = COROSYNC_CONF_PATH
    host_paths: HostPaths = HOST
    runner: ProcessRunner = run_with_timeout
    clock: Callable[[], datetime] = _now
    node: Callable[[], str] = node_name
    transport: Callable[[NotifySettings], Transport] = build_transport
    discover: Callable[..., Discovery] = discover
    on_device: Callable[[Candidate], None] | None = None


@dataclass(frozen=True)
class Delivery:
    """One planned notification, as rendered, and what became of it."""

    planned: Planned
    notification: Notification
    outcome: TransportOutcome | None = None

    @property
    def delivered(self) -> bool:
        return self.outcome is not None and self.outcome.delivered


@dataclass
class RunResult:
    """What one run did.

    `discovery` and `findings` feed the report of a dry run; `findings` is
    keyed by `Access.key`, the device name and the smartctl type. `ok` is
    false when a notification was not handed over or the state could not be
    saved, which makes the run fail (FR-607).
    """

    config: Config
    plan: Plan
    deliveries: list[Delivery]
    discovery: Discovery | None
    findings: dict[str, list[Finding]] = field(default_factory=dict)
    config_error: str | None = None
    state_error: str | None = None
    save_error: str | None = None
    summary: str = ""

    @property
    def ok(self) -> bool:
        undelivered = any(not delivery.delivered for delivery in self.deliveries)
        return not undelivered and self.save_error is None


def run_check(environment: Environment | None = None, *, dry_run: bool = False) -> RunResult:
    """Run one check (FR-601).

    Raises `LockedError` when another run holds the lock, and `OSError` when
    the lock or the state directory cannot be used.
    """
    env = environment if environment is not None else Environment()
    if dry_run:
        return _run(env, dry_run=True)
    with _lock(env.lock_path):
        return _run(env, dry_run=False)


def _run(env: Environment, *, dry_run: bool) -> RunResult:
    started = env.clock()
    node = env.node()

    config, error = load_effective(env.config_path, last_good=env.last_good)
    tool: list[Finding] = []
    if error is not None:
        fallback = (
            "the last good configuration"
            if config.source == env.last_good
            else "the built-in defaults"
        )
        tool.append(config_invalid(error, fallback=fallback))
    elif not dry_run:
        _save_last_good(config, env.last_good)

    state, state_reset, state_error = _state(env, started, dry_run=dry_run)

    discovery: Discovery | None = None
    missing = smartctl_missing(config.smartctl)
    if missing is not None:
        tool.append(missing)
    else:
        discovery = env.discover(
            config, runner=env.runner, paths=env.host_paths, on_device=env.on_device
        )
        too_old = smartctl_too_old(config.smartctl, discovery.smartctl_version, runner=env.runner)
        if too_old is not None:
            tool.append(too_old)
        else:
            failed = scan_failed(discovery.scan_error)
            if failed is not None:
                tool.append(failed)
    # The SCSI hosts need no smartctl: they are read in every run, so that a
    # missing smartctl does not clear the condition (ADR 0030). Discovery
    # has read them already when it ran.
    scsi_hosts = discovery.scsi_hosts if discovery is not None else read_scsi_hosts(env.host_paths)
    not_evaluated: frozenset[str] = frozenset()
    if scsi_hosts.error is not None:
        # sysfs could not be read: the condition stays as it is.
        not_evaluated = frozenset({UNSUPPORTED_CONTROLLER})
    else:
        unsupported = unsupported_controller(scsi_hosts.unsupported, _monitored(discovery))
        if unsupported is not None:
            tool.append(unsupported)
    degraded = transport_degraded(config.notify, env.bridge_path, runner=env.runner)
    if degraded is not None:
        tool.append(degraded)

    # A condition of the tool that the configuration switched off is not
    # raised at all; one that is active in the state is dropped by the planner
    # without a recovery (FR-408, ADR 0031).
    enabled = tool_conditions_enabled(config)
    tool = [finding for finding in tool if finding.check in enabled]

    observation, findings = _observe(
        discovery, config, state, tool, state_reset, not_evaluated=not_evaluated
    )
    result_plan = plan(state, observation, config, now=started, host=node)
    context = RenderContext(
        node=node,
        config=config,
        cluster=cluster_name(env.corosync_path),
        config_path=env.config_path,
    )
    deliveries = [
        Delivery(planned, render(planned, context)) for planned in result_plan.notifications
    ]
    result = RunResult(
        config=config,
        plan=result_plan,
        deliveries=deliveries,
        discovery=discovery,
        findings=findings,
        config_error=None if error is None else str(error),
        state_error=state_error,
    )
    if dry_run:
        return result

    transport = env.transport(config.notify)
    for index, delivery in enumerate(deliveries):
        outcome = transport.send(delivery.notification)
        deliveries[index] = Delivery(delivery.planned, delivery.notification, outcome)
        if outcome.delivered:
            result_plan.apply(delivery.planned)

    _finish(result, discovery, started=started, finished=env.clock())
    try:
        # A run killed before this point resends what it already delivered (ADR 0007).
        save_state(result_plan.state, env.state_path)
    except OSError as failure:
        result.save_error = f"the state could not be saved to {env.state_path}: {failure}"
    result.summary = _summary_line(result)
    return result


def _monitored(discovery: Discovery | None) -> int | None:
    """Return how many drives the run monitors, or `None` while it cannot count them.

    Without smartctl, and when the device scan failed, the run did not look
    for all drives, so the notice about a controller whose drives cannot be
    read leaves the number out (ADR 0031).
    """
    if discovery is None or discovery.scan_error is not None:
        return None
    return len(discovery.monitored)


def _state(
    env: Environment, now: datetime, *, dry_run: bool
) -> tuple[State, str | None, str | None]:
    """Return the state, why it was reset, and an error a dry run could not read past."""
    if dry_run:
        state, error = read_state(env.state_path, now=now)
        if error is not None:
            return State(), error, error
        return (state if state is not None else State()), None, None
    loaded = load_state(env.state_path, now=now)
    return loaded.state, loaded.reset, None


def _observe(
    discovery: Discovery | None,
    config: Config,
    state: State,
    tool: list[Finding],
    state_reset: str | None,
    *,
    not_evaluated: frozenset[str] = frozenset(),
) -> tuple[Observation, dict[str, list[Finding]]]:
    """Return what this run saw, for the planner, and the findings per device.

    The findings are keyed by the device name and smartctl type, because two
    drives behind one controller share the device name.
    """
    drives: list[DriveSeen] = []
    skipped: list[SkippedSeen] = []
    findings: dict[str, list[Finding]] = {}
    for found in discovery.devices if discovery is not None else ():
        access = Access(found.candidate.name, found.candidate.type)
        snapshot = found.snapshot
        if found.outcome is Outcome.MONITORED and snapshot is not None:
            settings = effective_checks(config, snapshot.identity, snapshot.drive_class)
            record = state.drives.get(identity_key(snapshot.identity, access))
            baselines = record.baselines if record is not None else {}
            drive_findings = evaluate(snapshot, settings, baselines)
            findings[access.key] = drive_findings
            drives.append(
                DriveSeen(
                    access,
                    Presence.READ,
                    snapshot=snapshot,
                    findings=tuple(drive_findings),
                    counters=counters(snapshot, settings),
                )
            )
        elif found.outcome is Outcome.STANDBY:
            drives.append(DriveSeen(access, Presence.STANDBY, reason=found.detail))
        elif found.outcome is Outcome.UNREADABLE:
            drives.append(DriveSeen(access, Presence.UNREADABLE, reason=found.detail))
        elif found.reason is not None:
            skipped.append(
                SkippedSeen(
                    access,
                    found.reason.value,
                    found.detail,
                    identity=None if snapshot is None else snapshot.identity,
                )
            )
    presence_known = discovery is not None and discovery.scan_error is None
    observation = Observation(
        drives=tuple(drives),
        skipped=tuple(skipped),
        tool=tuple(tool),
        tool_not_evaluated=not_evaluated,
        state_reset=state_reset,
        presence_known=presence_known,
        probe_off=not config.discovery.probe_cciss,
    )
    return observation, findings


def _finish(
    result: RunResult, discovery: Discovery | None, *, started: datetime, finished: datetime
) -> None:
    """Record the last run in the state (FR-602)."""
    devices = discovery.devices if discovery is not None else ()
    sent = sum(1 for delivery in result.deliveries if delivery.delivered)
    result.plan.state.last_run = LastRun(
        started=started,
        finished=finished,
        result=RESULT_OK if sent == len(result.deliveries) else RESULT_UNDELIVERED,
        drives_evaluated=sum(1 for found in devices if found.outcome is Outcome.MONITORED),
        drives_skipped=sum(
            1 for found in devices if found.outcome in (Outcome.SKIPPED, Outcome.STANDBY)
        ),
        drives_failed=sum(1 for found in devices if found.outcome is Outcome.UNREADABLE),
        notifications_sent=sent,
        notifications_failed=len(result.deliveries) - sent,
    )


def _summary_line(result: RunResult) -> str:
    """Return the one line a run logs (FR-606)."""
    state = result.plan.state
    run = state.last_run
    assert run is not None
    counts = dict.fromkeys((Severity.CRITICAL, Severity.WARNING, Severity.NOTICE), 0)
    conditions = [
        condition for record in state.drives.values() for condition in record.conditions.values()
    ]
    conditions += list(state.tool.conditions.values())
    for condition in conditions:
        if condition.severity in counts:
            counts[condition.severity] += 1
    active = ", ".join(f"{count} {severity.value}" for severity, count in counts.items())
    line = (
        f"run {run.result}: {run.drives_evaluated} drives evaluated, {run.drives_skipped}"
        f" skipped, {run.drives_failed} failed; active conditions: {active};"
        f" {run.notifications_sent} notifications sent, {run.notifications_failed} not delivered"
    )
    if result.save_error is not None:
        line += f"; {result.save_error}"
    return line


def _save_last_good(config: Config, path: Path) -> None:
    """Save the configuration as the last good one; a failure does not stop the run."""
    try:
        save_last_good(config, path)
    except OSError:
        return


@contextmanager
def _lock(path: Path) -> Iterator[None]:
    """Hold the lock of the run for its whole duration (ADR 0007, FR-605).

    The lock is an advisory lock on a file in the runtime directory. It is
    released by the kernel when the process ends, so a crashed run never
    leaves a stale lock behind.
    """
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockedError(f"another run holds the lock {path}") from error
        yield
    finally:
        os.close(descriptor)
