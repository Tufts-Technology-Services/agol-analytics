"""
Check an ArcGIS Online scheduled task (e.g. a notebook's) from what ArcGISReportClient.get_scheduled_task and
get_scheduled_task_runs return.

AGOL's documentation shows only one run status, "succeeded", so anything else counts as not succeeded. A run
that hasn't succeeded yet may still be going, so runs that started within max_runtime are left out unless
they've already succeeded: the newest run judged is the newest that has had time to finish.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

SUCCEEDED = 'succeeded'
# how much of a failed run's result (a JSON string of the job's messages) goes into a problem
MAX_RESULT_CHARS = 500


def run_start(run: dict) -> datetime | None:
    """when the run started (its `created`, epoch milliseconds), in UTC; None if that's missing or unreadable"""
    created = run.get('created')
    if isinstance(created, bool) or not isinstance(created, (int, float)):
        return None
    return datetime.fromtimestamp(created / 1000, timezone.utc)


def run_succeeded(run: dict) -> bool:
    return str(run.get('status', '')).lower() == SUCCEEDED


def newest_settled_run(runs: list[dict], now: datetime, max_runtime: timedelta) -> dict | None:
    """the newest run that has succeeded or started at least max_runtime before now; None if there's none.
    Runs without a readable start time are left out (notebook_task_problems reports them)."""
    settled = [run for run in runs if run_start(run) is not None
               and (run_succeeded(run) or run_start(run) <= now - max_runtime)]
    return max(settled, key=run_start, default=None)


def notebook_task_problems(task: dict, runs: list[dict], now: datetime, max_age: timedelta,
                           max_runtime: timedelta) -> list[str]:
    """
    Every way the task isn't healthy, in words; empty if it is. It's healthy if it's active, and the newest
    settled run (see newest_settled_run) succeeded and started within max_age of now. now must be
    timezone-aware.
    """
    problems = []
    title = task.get('title') or task.get('id') or 'the task'

    state = task.get('taskState')
    if task.get('active') is not True or state != 'active':
        problems.append(f"{title} is not active (active={task.get('active')}, taskState={state}); "
                        "AGOL pauses a task after repeated failed runs")

    unreadable = [run.get('runId', '?') for run in runs if run_start(run) is None]
    if unreadable:
        problems.append(f"runs without a readable start time (created): {', '.join(map(str, unreadable))}")

    run = newest_settled_run(runs, now, max_runtime)
    if run is None:
        if runs:
            problems.append(f"{title} has no runs that started more than {max_runtime} ago")
        else:
            problems.append(f"{title} has no recorded runs (AGOL keeps only recent runs)")
        return problems

    started = run_start(run)
    if not run_succeeded(run):
        result = str(run.get('result', ''))[:MAX_RESULT_CHARS]
        problems.append(f"newest run of {title}, started {started:%Y-%m-%d %H:%M} UTC, has status "
                        f"'{run.get('status')}': {result}")
    if started < now - max_age:
        problems.append(f"newest run of {title} started {started:%Y-%m-%d %H:%M} UTC, more than {max_age} ago")
    return problems
