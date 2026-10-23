"""ArcGISReportClient, with requests faked so nothing reaches ArcGIS Online."""
from datetime import date, datetime

import pandas as pd
import pytest
import requests

from agol_analytics.agol.workflow import get_datetime
from agol_analytics.utils.agol import AgolTokenError, ArcGISReportClient, history_window
from agol_analytics.validation import HISTORY_COLUMNS, AgolDataError
from sample_data import FIXTURES_DIR, SAME_MILLISECOND_ROWS, FakeHttpResponse, load_login_history

API_BASE = "https://tuftsgis.maps.arcgis.com/sharing/rest"
HISTORY_HEADER = ",".join(HISTORY_COLUMNS) + "\n"


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

    # the second request, from the last login's time, brings nothing new
    [(url, params), _] = agol_api.gets
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


def test_an_error_reply_to_the_history_request_raises(agol_api, monkeypatch):
    # AGOL reports an expired or invalid token as JSON with HTTP 200, even when CSV was asked for
    error_reply = '{"error":{"code":498,"message":"Invalid token.","details":[]}}'
    monkeypatch.setattr(agol_api, "get", lambda url, params=None, **kwargs: FakeHttpResponse(text=error_reply))

    with pytest.raises(AgolDataError, match="sent an error instead of login history: 498; Invalid token."):
        ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))


def test_an_unreadable_json_reply_raises(agol_api, monkeypatch):
    monkeypatch.setattr(agol_api, "get", lambda url, params=None, **kwargs: FakeHttpResponse(text='{"items": ['))

    with pytest.raises(AgolDataError, match="a JSON reply, not CSV"):
        ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))


@pytest.mark.parametrize("reply", ["", "\n", "\r\n", HISTORY_HEADER, HISTORY_HEADER.replace("\n", "\r\n")])
def test_an_empty_reply_is_a_day_without_logins(agol_api, monkeypatch, reply):
    monkeypatch.setattr(agol_api, "get", lambda url, params=None, **kwargs: FakeHttpResponse(text=reply))

    history = ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))
    assert (len(history), history.columns.tolist()) == (0, HISTORY_COLUMNS)


def test_history_window_is_one_day_from_the_given_time():
    day = get_datetime("2026-11-01")  # the clocks go back: 25 hours
    from_date, to_date = history_window(day)
    assert (from_date, to_date.isoformat()) == (day, "2026-11-02T00:00:00-05:00")


class CappedAgolApi(FakeAgolApi):
    """Like AGOL: the sample's logins in the requested window, oldest first, at most `cap` per request."""

    def __init__(self, cap):
        super().__init__()
        self.cap = cap
        self.history = pd.read_csv(FIXTURES_DIR / "agol_history_sample.csv").sort_values("created")

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params))
        created = self.history["created"]
        in_window = self.history[(created >= params["fromDate"]) & (created < params["toDate"])]
        return FakeHttpResponse(text=in_window.head(min(self.cap, params["num"])).to_csv(index=False))


@pytest.mark.parametrize("cap", [68, 30, 7])
def test_a_day_over_the_per_request_limit_is_fetched_in_full(monkeypatch, cap):
    import agol_analytics.utils.agol

    api = CappedAgolApi(cap)
    monkeypatch.setattr(agol_analytics.utils.agol, "requests", api)

    history = ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))

    assert sorted(history["reqId"]) == sorted(api.history["reqId"])
    # each request after the first starts at the last login so far, inclusive
    starts = [params["fromDate"] for _, params in api.gets]
    assert starts[0] == ArcGISReportClient.get_timestamp(get_datetime("2026-10-21"))
    assert starts[1:] == sorted(starts[1:]) and len(set(starts)) == len(starts)


def test_logins_sharing_the_last_millisecond_are_kept_once(monkeypatch):
    import agol_analytics.utils.agol

    api = CappedAgolApi(cap=10)
    api.history.loc[api.history.index[9:12], "created"] = api.history["created"].iloc[9]  # rows 10-12 share a time
    monkeypatch.setattr(agol_analytics.utils.agol, "requests", api)

    history = ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))

    assert len(history) == 68
    assert history["reqId"].is_unique


def test_paging_that_never_finishes_raises(monkeypatch):
    import agol_analytics.utils.agol

    class EndlessAgolApi(FakeAgolApi):
        def get(self, url, params=None, **kwargs):
            self.gets.append((url, params))
            row = pd.read_csv(FIXTURES_DIR / "agol_history_sample.csv").head(1)
            row["reqId"], row["created"] = f"EXAMPLE-{len(self.gets)}", params["fromDate"] + 1
            return FakeHttpResponse(text=row.to_csv(index=False))

    monkeypatch.setattr(agol_analytics.utils.agol, "requests", EndlessAgolApi())
    with pytest.raises(AgolDataError, match="still had new logins after 20 requests"):
        ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))


def test_a_rejected_token_on_a_csv_request_raises(agol_api, monkeypatch):
    # for CSV, AGOL answers a bad token with HTTP 498 and an HTML page, not the JSON error it sends otherwise
    page = "<html><head><title>Invalid token</title></head><body>Invalid token.</body></html>"
    monkeypatch.setattr(agol_api, "get", lambda url, params=None, **kwargs: FakeHttpResponse(498, text=page))

    with pytest.raises(requests.HTTPError, match="498"):
        ArcGISReportClient().get_single_day_agol_logins(get_datetime("2026-10-21"))


def test_the_sample_is_stored_as_agol_sends_it():
    # .gitattributes keeps the CRLF line endings; git would otherwise convert them
    raw = (FIXTURES_DIR / "agol_history_sample.csv").read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") == 69

    history = load_login_history()
    assert (history["actor"] == history["id"]).all()
    assert history["data"].dropna().tolist() == ['{"keyName":"","securityKeyId":""}'] * 2
    assert history["ip"].isna().sum() == 1
    first, second = SAME_MILLISECOND_ROWS
    assert history.loc[first, "created"] == history.loc[second, "created"]
    assert history["clientId"].str.startswith("ip.").sum() == 1
