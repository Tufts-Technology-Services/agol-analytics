"""ArcGISReportClient, with requests faked so nothing reaches ArcGIS Online."""
from datetime import date, datetime

import pytest

from agol_analytics.agol.workflow import get_datetime
from agol_analytics.utils.agol import AgolTokenError, ArcGISReportClient
from sample_data import FIXTURES_DIR, FakeHttpResponse

API_BASE = "https://tuftsgis.maps.arcgis.com/sharing/rest"


class FakeAgolApi:
    """Stands in for the requests module inside agol_analytics.utils.agol."""

    def __init__(self):
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.token_reply = {"token": "EXAMPLE-token", "expires": 1792628144007, "ssl": True}

    def post(self, url, data=None, **kwargs):
        self.posts.append((url, data))
        return FakeHttpResponse(json_body=self.token_reply)

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params))
        return FakeHttpResponse(text=(FIXTURES_DIR / "agol_history_sample.csv").read_text())


@pytest.fixture
def agol_api(monkeypatch):
    import agol_analytics.utils.agol

    api = FakeAgolApi()
    monkeypatch.setattr(agol_analytics.utils.agol, "requests", api)
    return api


def test_get_token_posts_credentials_and_keeps_the_token(agol_api):
    client = ArcGISReportClient()
    client.get_token("EXAMPLE-user", "EXAMPLE-placeholder")

    assert agol_api.posts == [(f"{API_BASE}/generateToken", {"username": "EXAMPLE-user",
                                                             "password": "EXAMPLE-placeholder",
                                                             "client": "requestip", "f": "json"})]
    assert client.token == "EXAMPLE-token"


def test_get_token_reports_rejected_credentials(agol_api):
    # AGOL answers a failed login with HTTP 200 and an error body
    agol_api.token_reply = {"error": {"code": 400, "message": "Unable to generate token.",
                                      "details": ["Invalid username or password."]}}
    client = ArcGISReportClient()

    with pytest.raises(AgolTokenError, match="Unable to generate token.; Invalid username or password.") as raised:
        client.get_token("EXAMPLE-user", "EXAMPLE-wrong")

    assert "EXAMPLE-user" in str(raised.value)
    assert "EXAMPLE-wrong" not in str(raised.value)
    assert client.token is None


def test_get_token_reports_a_reply_without_a_token(agol_api):
    agol_api.token_reply = {}
    with pytest.raises(AgolTokenError, match="no token in the response"):
        ArcGISReportClient().get_token("EXAMPLE-user", "EXAMPLE-placeholder")


def test_single_day_query_covers_midnight_to_midnight_eastern(agol_api):
    client = ArcGISReportClient()
    client.token = "EXAMPLE-token"

    history = client.get_single_day_agol_logins(get_datetime("2026-10-21"))

    [(url, params)] = agol_api.gets
    assert url == f"{API_BASE}/portals/self/history"
    assert params["fromDate"] == int(datetime.fromisoformat("2026-10-21T00:00:00-04:00").timestamp() * 1000)
    assert params["toDate"] == int(datetime.fromisoformat("2026-10-22T00:00:00-04:00").timestamp() * 1000)
    assert (params["actions"], params["f"], params["token"]) == ("login", "csv", "EXAMPLE-token")
    assert len(history) == 68


def test_single_day_query_is_capped_at_10000_logins(agol_api):
    # more logins than this in one day would be dropped silently
    client = ArcGISReportClient()
    client.get_single_day_agol_logins(get_datetime("2026-10-21"))
    assert agol_api.gets[0][1]["num"] == 10000


def test_single_day_query_accepts_datetime_subclasses(agol_api):
    # Airflow passes pendulum DateTimes, which subclass datetime
    class PendulumLikeDateTime(datetime):
        pass

    day = get_datetime("2026-10-21")
    ArcGISReportClient().get_single_day_agol_logins(PendulumLikeDateTime(2026, 10, 21, tzinfo=day.tzinfo))
    assert agol_api.gets[0][1]["fromDate"] == ArcGISReportClient.get_timestamp(day)


def test_single_day_query_needs_a_datetime(agol_api):
    with pytest.raises(AssertionError):
        ArcGISReportClient().get_single_day_agol_logins(date(2026, 10, 21))


def test_get_timestamp_is_epoch_milliseconds():
    assert ArcGISReportClient.get_timestamp(datetime.fromisoformat("2026-10-21T04:00:00+00:00")) == 1792555200000
