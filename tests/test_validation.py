"""Validation of the login history ArcGIS Online returns, before any processing."""
import json

import pandas as pd
import pytest

from agol_analytics.agol.workflow import clean_agol_logins, get_datetime
from agol_analytics.utils.agol import history_window
from agol_analytics.validation import (HISTORY_COLUMNS, AgolDataError, check_agol_history,
                                       validate_agol_history)
from sample_data import USER_NOT_IN_PR_FIS, load_login_history

SAMPLE_WINDOW = history_window(get_datetime("2026-10-21"))


def validate_sample(history=None, **options):
    return validate_agol_history(load_login_history() if history is None else history, *SAMPLE_WINDOW, **options)


def test_the_sample_day_passes_with_only_the_unsuffixed_user_noted():
    report = validate_sample()

    assert (report.row_count, report.errors) == (68, [])
    assert report.warnings == ["id doesn't end in _TuftsGIS in 5 of 68 rows, so those users' PR details won't be found"]


@pytest.mark.parametrize("column", ["id", "created", "request", "reqId", "clientId"])
def test_a_missing_column_the_processing_uses_is_an_error(column):
    report = validate_sample(load_login_history().drop(columns=[column]))
    assert f"missing column(s) {column}" in report.errors


@pytest.mark.parametrize("column", ["idType", "orgId", "action", "ip"])
def test_a_missing_column_that_cleaning_drops_is_a_warning(column):
    history = load_login_history().drop(columns=[column])
    report = validate_sample(history)

    assert report.errors == []
    assert f"missing column(s) {column} (not used)" in report.warnings
    assert len(clean_agol_logins(history)) == 68


def test_a_new_column_is_a_warning():
    history = load_login_history().assign(userAgent="EXAMPLE")
    report = validate_sample(history)

    assert report.errors == []
    assert "new column 'userAgent'" in report.warnings


def test_created_in_another_format_is_an_error():
    history = load_login_history()
    history["created"] = history["created"].astype(object)
    history.loc[[3, 7], "created"] = "2026-10-21T20:15:44Z"

    [error] = validate_sample(history).errors
    assert error.startswith("created isn't epoch milliseconds in 2 of 68 rows (e.g. reqId ")


def test_created_in_seconds_or_fractions_is_noticed():
    history = load_login_history()
    history["created"] = history["created"] / 1000  # seconds with a fraction

    [error] = validate_sample(history).errors
    assert error.startswith("created isn't epoch milliseconds in 68 of 68 rows")


def test_empty_keys_are_errors():
    history = load_login_history()
    history.loc[0, "reqId"] = None
    history.loc[1, "id"] = ""

    errors = validate_sample(history).errors
    assert "reqId is empty in 1 of 68 rows (e.g. row 0)" in errors
    assert any(error.startswith("id is empty in 1 of 68 rows") for error in errors)


def test_other_actions_are_errors():
    history = load_login_history()
    history.loc[0, "action"] = "delete"

    [error] = validate_sample(history).errors
    assert error.startswith("action isn't 'login' in 1 of 68 rows")


def test_logins_out_of_time_order_are_a_warning():
    # the client's paging continues from the latest login, so it relies on AGOL's oldest-first order
    history = load_login_history().iloc[::-1]
    report = validate_sample(history)

    assert report.errors == []
    assert "logins aren't in time order, so the client's paging may have missed some" in report.warnings


def test_a_day_without_logins_is_a_warning():
    report = validate_sample(pd.DataFrame(columns=HISTORY_COLUMNS))
    assert (report.errors, report.warnings) == ([], ["no logins returned"])


def test_logins_outside_the_window_are_a_warning():
    report = validate_agol_history(load_login_history(), *history_window(get_datetime("2026-10-22")))

    assert report.errors == []
    assert report.warnings[0].startswith("created is outside the requested window 2026-10-22T00:00:00-04:00 to "
                                         "2026-10-23T00:00:00-04:00 in 68 of 68 rows")


def test_repeats_empty_client_ids_and_other_id_types_are_warnings():
    history = load_login_history()
    history.loc[1, "reqId"] = history.loc[0, "reqId"]
    history.loc[2, "clientId"] = None
    history.loc[3, "idType"] = "a"

    report = validate_sample(history)
    assert report.errors == []
    assert [warning.split(" in ")[0] for warning in report.warnings[:3]] == [
        "idType isn't 'u'", "reqId is repeated (only the last is kept)", "clientId is empty"]


def test_reports_never_quote_usernames_or_ip_addresses():
    history = load_login_history()
    history.loc[0:4, "action"] = "delete"
    history.loc[5:9, "created"] = None
    report = validate_sample(history)

    text = json.dumps(report.as_dict())
    for username in history["id"].unique():
        assert username.removesuffix("_TuftsGIS") not in text
    assert USER_NOT_IN_PR_FIS not in text
    for address in history["ip"].dropna().unique():
        assert address not in text
    for username in history["actor"].unique():
        assert username not in text


def test_check_saves_the_report_next_to_the_raw_file(tmp_path):
    raw = tmp_path / "raw.csv"
    check_agol_history(load_login_history(), *SAMPLE_WINDOW, raw_data_path=raw)

    saved = json.loads((tmp_path / "raw.csv.validation.json").read_text())
    assert (saved["from_date"], saved["row_count"], saved["errors"]) == ("2026-10-21T00:00:00-04:00", 68, [])


def test_check_saves_the_report_then_raises_on_errors(tmp_path):
    raw = tmp_path / "raw.csv"
    with pytest.raises(AgolDataError, match="missing column"):
        check_agol_history(load_login_history().drop(columns=["reqId"]), *SAMPLE_WINDOW, raw_data_path=raw)

    assert json.loads((tmp_path / "raw.csv.validation.json").read_text())["errors"] == ["missing column(s) reqId"]
