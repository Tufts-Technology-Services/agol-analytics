"""Check the login history ArcGIS Online returns before any processing, so changes at the source get noticed.

Each day's history CSV is checked against what the processing relies on:

- A breaking change is an error. These are: a column the processing uses is missing; ``created``
  isn't epoch milliseconds; ``reqId`` (the table's primary key) or ``id`` is empty; or an action
  other than login.
  The caller saves the raw data and the report, then fails.
- Anything else unusual is a warning: it's logged and recorded in the report, and the run carries on.
  That covers new columns, missing columns that cleaning drops anyway, a day with no logins, logins
  outside the requested window or out of time order (the client's paging relies on the order),
  repeated ``reqId``s, empty ``clientId``s, and usernames without the ``_TuftsGIS`` suffix (their PR
  details won't be found; a few dozen a day is normal).

Reports quote request IDs, never usernames or IP addresses, so they can be shared.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# the history CSV's columns, in its order (checked against ArcGIS Online in October 2026)
HISTORY_COLUMNS = ['id', 'idType', 'orgId', 'owner', 'actor', 'ip', 'action', 'created', 'created_utc',
                   'request', 'reqId', 'clientId', 'data']
# used by clean_agol_logins and join_and_organize_logins
USED_COLUMNS = frozenset({'id', 'created', 'request', 'reqId', 'clientId'})
# clean_agol_logins drops these, so they can go missing without harm
DROPPED_COLUMNS = frozenset({'idType', 'orgId', 'action', 'ip'})

USERNAME_SUFFIX = '_TuftsGIS'
# how many example request IDs to quote for each problem
EXAMPLES_PER_PROBLEM = 3


class AgolDataError(Exception):
    """ArcGIS Online returned login history the processing can't handle correctly."""


@dataclass
class ValidationReport:
    from_date: str
    to_date: str
    row_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"from_date": self.from_date, "to_date": self.to_date, "row_count": self.row_count,
                "errors": self.errors, "warnings": self.warnings}

    def log_findings(self) -> None:
        for message in self.errors:
            log.error("AGOL history from %s: %s", self.from_date, message)
        for message in self.warnings:
            log.warning("AGOL history from %s: %s", self.from_date, message)

    def raise_if_errors(self) -> None:
        if self.errors:
            raise AgolDataError(f"ArcGIS Online returned login history from {self.from_date} that can't be "
                                "processed: " + "; ".join(self.errors))


def _examples(history: pd.DataFrame, rows: pd.Series) -> str:
    """A few request IDs (or row numbers) for the rows flagged in ``rows``, to quote in a message."""
    flagged = history[rows].head(EXAMPLES_PER_PROBLEM)
    if 'reqId' in history.columns:
        labels = [f"reqId {request_id}" if pd.notna(request_id) else f"row {position}"
                  for position, request_id in zip(flagged.index, flagged['reqId'])]
    else:
        labels = [f"row {position}" for position in flagged.index]
    return ', '.join(labels)


def _is_empty(values: pd.Series) -> pd.Series:
    return values.isna() | (values.astype(str).str.strip() == '')


def validate_agol_history(history: pd.DataFrame, from_date: datetime, to_date: datetime) -> ValidationReport:
    """Check one request's login history (as get_single_day_agol_logins returns it) for the given window."""
    report = ValidationReport(from_date.isoformat(), to_date.isoformat())
    if not isinstance(history, pd.DataFrame):
        report.errors.append(f"expected a table of logins, got {type(history).__name__}")
        return report
    history = history.reset_index(drop=True)
    total = report.row_count = len(history)
    columns = set(history.columns)

    missing_used = sorted(USED_COLUMNS - columns)
    if missing_used:
        report.errors.append(f"missing column(s) {', '.join(missing_used)}")
    missing_dropped = sorted(DROPPED_COLUMNS - columns)
    if missing_dropped:
        report.warnings.append(f"missing column(s) {', '.join(missing_dropped)} (not used)")
    for name in [name for name in history.columns if name not in HISTORY_COLUMNS]:
        report.warnings.append(f"new column '{name}'")

    if total == 0:
        report.warnings.append("no logins returned")
        return report

    def flag(rows: pd.Series, message: str, findings: list[str]) -> None:
        count = int(rows.sum())
        if count:
            findings.append(f"{message} in {count} of {total} rows (e.g. {_examples(history, rows)})")

    for name in ('reqId', 'id'):
        if name in columns:
            flag(_is_empty(history[name]), f"{name} is empty", report.errors)

    if 'created' in columns:
        created = pd.to_numeric(history['created'], errors='coerce')
        # whole numbers only: a fraction or text means the format changed
        unreadable = created.isna() | (created % 1 != 0)
        flag(unreadable & ~_is_empty(history['created']), "created isn't epoch milliseconds", report.errors)
        flag(_is_empty(history['created']), "created is empty", report.errors)
        readable = created[~unreadable]
        start_ms, end_ms = from_date.timestamp() * 1000, to_date.timestamp() * 1000
        outside = pd.Series(False, index=history.index)
        outside[readable.index] = (readable < start_ms) | (readable >= end_ms)
        flag(outside, f"created is outside the requested window {report.from_date} to {report.to_date}",
             report.warnings)
        if not readable.is_monotonic_increasing:
            report.warnings.append("logins aren't in time order, so the client's paging may have missed some")

    if 'action' in columns:
        flag(history['action'].astype(str) != 'login', "action isn't 'login'", report.errors)
    if 'idType' in columns:
        flag(history['idType'].astype(str) != 'u', "idType isn't 'u'", report.warnings)
    if 'reqId' in columns:
        repeated = history['reqId'].duplicated(keep=False) & ~_is_empty(history['reqId'])
        flag(repeated, "reqId is repeated (only the last is kept)", report.warnings)
    if 'clientId' in columns:
        flag(_is_empty(history['clientId']), "clientId is empty", report.warnings)
    if 'id' in columns:
        # counted, not quoted: the examples would be usernames
        unsuffixed = int((~history['id'].astype(str).str.endswith(USERNAME_SUFFIX) & ~_is_empty(history['id'])).sum())
        if unsuffixed:
            report.warnings.append(f"id doesn't end in {USERNAME_SUFFIX} in {unsuffixed} of {total} rows, "
                                   "so those users' PR details won't be found")
    return report


def check_agol_history(history: pd.DataFrame, from_date: datetime, to_date: datetime,
                       raw_data_path=None) -> ValidationReport:
    """
    Validate a request's login history and log the findings. If ``raw_data_path`` is given, save the
    report next to it as <raw file>.validation.json. Raises AgolDataError, after saving, if anything
    is breaking.
    """
    report = validate_agol_history(history, from_date, to_date)
    report.log_findings()
    if raw_data_path is not None:
        raw_data_path = Path(raw_data_path)
        report_path = raw_data_path.with_name(raw_data_path.name + ".validation.json")
        report_path.write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    report.raise_if_errors()
    return report
