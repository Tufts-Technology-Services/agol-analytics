"""update_agol_logins: which days it fetches and what it stores, with a fake database and AGOL client."""
import importlib
from datetime import date, datetime

import pandas as pd
import pytest

from agol_analytics.agol.workflow import EASTERN
from agol_analytics.update_agol_logins import update_agol_logins
from sample_data import load_login_history, load_pr_fis

SAMPLE_DAY = date(2026, 10, 21)
# agol_analytics/__init__.py imports the update_agol_logins function over the submodule's name
update_module = importlib.import_module("agol_analytics.update_agol_logins")


class FakeAgolDatabase:
    """Enough of DatabaseInterface for update_agol_logins; records what it's asked to do."""

    def __init__(self, last_stored_date=None):
        self.last_stored_date = last_stored_date
        self.sql_files_run: list[str] = []
        self.reads: list[tuple[str, list]] = []
        self.appended: list[tuple[str, pd.DataFrame]] = []

    def execute_sql_file(self, sql_path, format_strings=None):
        self.sql_files_run.append(sql_path)

    def check_last_date(self, date_col, table_name, where_clause=None):
        assert (date_col, table_name) == ("request_date", "agol_logins")
        return self.last_stored_date

    def read_df(self, table_name=None, cols=None, sql=None):
        self.reads.append((table_name, cols))
        return load_pr_fis()[cols]

    def append_df(self, dataframe, table_name):
        self.appended.append((table_name, dataframe))


class FakeReportClient:
    """Stands in for ArcGISReportClient: the sample is the only day with logins."""

    instances: list["FakeReportClient"] = []

    def __init__(self):
        self.credentials = None
        self.days_requested: list[datetime] = []
        FakeReportClient.instances.append(self)

    def get_token(self, username, passwd):
        self.credentials = (username, passwd)

    def get_single_day_agol_logins(self, single_date):
        self.days_requested.append(single_date)
        history = load_login_history()
        return history if single_date.date() == SAMPLE_DAY else history.iloc[0:0]


@pytest.fixture
def agol_client(monkeypatch):
    FakeReportClient.instances = []
    monkeypatch.setattr(update_module, "ArcGISReportClient", FakeReportClient)
    return FakeReportClient


def run_on(monkeypatch, today: date, db: FakeAgolDatabase):
    class FrozenDate(date):
        @classmethod
        def today(cls):
            return today

    monkeypatch.setattr(update_module, "date", FrozenDate)
    update_agol_logins(db, "EXAMPLE-user", "EXAMPLE-placeholder")


def days_requested():
    return [d.date() for client in FakeReportClient.instances for d in client.days_requested]


def test_first_run_starts_at_the_semester_start(monkeypatch, agol_client):
    run_on(monkeypatch, date(2026, 10, 22), FakeAgolDatabase(last_stored_date=None))

    requested = days_requested()
    assert (requested[0], requested[-1], len(requested)) == (date(2026, 9, 1), SAMPLE_DAY, 51)


def test_later_runs_start_after_the_last_stored_day(monkeypatch, agol_client):
    run_on(monkeypatch, date(2026, 10, 22), FakeAgolDatabase(last_stored_date=date(2026, 10, 19)))
    assert days_requested() == [date(2026, 10, 20), SAMPLE_DAY]


def test_each_day_is_requested_from_eastern_midnight(monkeypatch, agol_client):
    run_on(monkeypatch, date(2026, 10, 22), FakeAgolDatabase(last_stored_date=date(2026, 10, 20)))
    [day] = FakeReportClient.instances[0].days_requested
    assert day == datetime(2026, 10, 21, tzinfo=EASTERN)


def test_a_rerun_the_same_day_fetches_and_stores_nothing(monkeypatch, agol_client):
    db = FakeAgolDatabase(last_stored_date=SAMPLE_DAY)
    run_on(monkeypatch, date(2026, 10, 22), db)

    assert FakeReportClient.instances == []
    assert db.appended == []


def test_appends_the_processed_logins(monkeypatch, agol_client):
    db = FakeAgolDatabase(last_stored_date=date(2026, 10, 20))
    run_on(monkeypatch, date(2026, 10, 22), db)

    [(table, logins)] = db.appended
    assert table == "agol_logins"
    assert len(logins) == 68  # including the user who isn't in pr_fis, with empty PR fields
    assert FakeReportClient.instances[0].credentials == ("EXAMPLE-user", "EXAMPLE-placeholder")


def test_reads_the_pr_fields_it_needs_from_pr_fis_vw(monkeypatch, agol_client):
    db = FakeAgolDatabase(last_stored_date=date(2026, 10, 20))
    run_on(monkeypatch, date(2026, 10, 22), db)

    [(table, cols)] = db.reads
    assert table == "pr_fis_vw"
    assert cols == load_pr_fis().columns.tolist()


def test_the_table_is_ensured_on_every_run(monkeypatch, agol_client):
    db = FakeAgolDatabase(last_stored_date=SAMPLE_DAY)
    run_on(monkeypatch, date(2026, 10, 22), db)
    assert len(db.sql_files_run) == 1


def test_a_day_that_fails_validation_stops_the_run_before_anything_is_stored(monkeypatch, agol_client):
    from agol_analytics.validation import AgolDataError

    def history_without_request_ids(self, single_date):
        self.days_requested.append(single_date)
        return load_login_history().drop(columns=["reqId"])

    monkeypatch.setattr(FakeReportClient, "get_single_day_agol_logins", history_without_request_ids)
    db = FakeAgolDatabase(last_stored_date=date(2026, 10, 19))

    with pytest.raises(AgolDataError, match="missing column"):
        run_on(monkeypatch, date(2026, 10, 22), db)
    assert db.appended == []
    assert days_requested() == [date(2026, 10, 20)]
