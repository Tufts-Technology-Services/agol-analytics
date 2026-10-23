"""Date handling and login cleaning in agol_analytics.agol.workflow."""
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from agol_analytics.agol.workflow import EASTERN, clean_agol_logins, generate_date_range, get_datetime


@pytest.mark.parametrize("query_date", [date(2026, 1, 15), datetime(2026, 1, 15, 13, 45), "2026-01-15"])
def test_get_datetime_is_midnight_eastern(query_date):
    assert get_datetime(query_date) == datetime(2026, 1, 15, tzinfo=EASTERN)


@pytest.mark.parametrize(("day", "utc_hours"), [("2026-01-15", -5), ("2026-07-15", -4)])
def test_get_datetime_uses_the_eastern_offset_for_the_season(day, utc_hours):
    assert get_datetime(day).utcoffset() == timedelta(hours=utc_hours)


def test_date_range_keeps_midnight_across_the_end_of_daylight_saving():
    days = generate_date_range("2026-10-31", "2026-11-02")

    assert [d.isoformat() for d in days] == ["2026-10-31T00:00:00-04:00", "2026-11-01T00:00:00-04:00",
                                             "2026-11-02T00:00:00-05:00"]
    # the API is queried from each midnight to the next, so the day the clocks change is 25 hours
    assert days[2].timestamp() - days[1].timestamp() == 25 * 3600


def login_row(request_id, utc_time):
    return {"idType": "u", "orgId": "org", "action": "login", "ip": "10.0.0.1", "request": "/sharing/rest/oauth2/token",
            "reqId": request_id, "clientId": "arcgisonline", "id": "u1234567_TuftsGIS",
            "created": int(utc_time.timestamp() * 1000)}


@pytest.mark.parametrize(("utc_time", "request_date"), [
    (datetime(2026, 7, 15, 4, 30, tzinfo=timezone.utc), "2026-07-15"),   # 00:30 EDT
    (datetime(2026, 7, 15, 3, 30, tzinfo=timezone.utc), "2026-07-14"),   # 23:30 EDT the day before
    (datetime(2026, 1, 15, 5, 30, tzinfo=timezone.utc), "2026-01-15"),   # 00:30 EST
])
def test_logins_are_dated_in_eastern_time(utc_time, request_date):
    cleaned = clean_agol_logins(pd.DataFrame([login_row("r1", utc_time)]))
    assert cleaned.request_date.tolist() == [request_date]
