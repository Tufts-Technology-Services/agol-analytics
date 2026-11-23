"""Checking a scheduled notebook task, and the client requests for it, with requests faked."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from agol_analytics.notebook_tasks import newest_settled_run, notebook_task_problems, run_start
from agol_analytics.utils.agol import AgolRequestError, ArcGISReportClient
from sample_data import FakeHttpResponse

API_BASE = "https://tuftsgis.maps.arcgis.com/sharing/rest"
NOW = datetime(2026, 11, 23, 14, 0, tzinfo=timezone.utc)
MAX_AGE = timedelta(hours=26)
MAX_RUNTIME = timedelta(hours=1)

# shaped like the example in AGOL's "Runs for Task" documentation
TASK = {"id": "EXAMPLE-task-id", "title": "Nightly refresh", "type": "ExecuteNotebook",
        "active": True, "taskState": "active", "cronSchedule": "0 6 * * ?"}


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def make_run(started: datetime, status: str = "succeeded", run_id: str = "EXAMPLE-run", **fields) -> dict:
    return {"runId": run_id, "status": status, "created": ms(started), "modified": ms(started) + 60_000,
            "result": '{"status":"COMPLETED"}', "task": TASK, **fields}


def problems_for(runs, task=TASK, now=NOW):
    return notebook_task_problems(task, runs, now, MAX_AGE, MAX_RUNTIME)


# --- the check


def test_a_recent_success_is_healthy():
    assert problems_for([make_run(NOW - timedelta(hours=8))]) == []


def test_the_newest_run_is_judged_whatever_the_order():
    runs = [make_run(NOW - timedelta(hours=8), run_id="new"),
            make_run(NOW - timedelta(hours=32), status="failed", run_id="old")]
    assert problems_for(runs) == []
    assert problems_for(runs[::-1]) == []


def test_a_failed_newest_run_is_reported_with_its_result():
    runs = [make_run(NOW - timedelta(hours=32)),
            make_run(NOW - timedelta(hours=8), status="failed", result='{"messages":["Kernel died"]}')]
    [problem] = problems_for(runs)
    assert "has status 'failed'" in problem
    assert "Kernel died" in problem
    assert "2026-11-23 06:00 UTC" in problem


def test_a_long_result_is_cut_short():
    [problem] = problems_for([make_run(NOW - timedelta(hours=8), status="failed", result="x" * 5000)])
    assert problem.count("x") < 600


def test_status_is_compared_without_case():
    assert problems_for([make_run(NOW - timedelta(hours=8), status="SUCCEEDED")]) == []


def test_an_old_success_is_reported():
    [problem] = problems_for([make_run(NOW - timedelta(hours=27))])
    assert "more than 1 day, 2:00:00 ago" in problem


def test_a_run_still_going_is_left_out():
    # started 10 minutes ago, not finished: yesterday's success is judged instead
    runs = [make_run(NOW - timedelta(hours=24)), make_run(NOW - timedelta(minutes=10), status="running")]
    assert problems_for(runs) == []
    assert newest_settled_run(runs, NOW, MAX_RUNTIME) is runs[0]


def test_a_run_going_longer_than_max_runtime_is_reported():
    runs = [make_run(NOW - timedelta(hours=24)), make_run(NOW - timedelta(hours=2), status="running")]
    [problem] = problems_for(runs)
    assert "has status 'running'" in problem


def test_a_recent_success_counts_at_once():
    assert newest_settled_run([make_run(NOW - timedelta(minutes=5))], NOW, MAX_RUNTIME) is not None


@pytest.mark.parametrize(("active", "state"), [(False, "paused"), (True, "paused"), (False, "active"),
                                               (True, "completed"), (None, None)])
def test_a_task_that_isnt_active_is_reported(active, state):
    task = {**TASK, "active": active, "taskState": state}
    [problem] = problems_for([make_run(NOW - timedelta(hours=8))], task=task)
    assert f"Nightly refresh is not active (active={active}, taskState={state})" in problem


def test_every_problem_is_listed():
    task = {**TASK, "active": False, "taskState": "paused"}
    problems = problems_for([make_run(NOW - timedelta(days=3), status="failed")], task=task)
    assert len(problems) == 3


def test_no_runs_is_reported():
    assert problems_for([]) == ["Nightly refresh has no recorded runs (AGOL keeps only recent runs)"]


def test_only_a_run_still_going_is_reported():
    [problem] = problems_for([make_run(NOW - timedelta(minutes=10), status="running")])
    assert "no runs that started more than 1:00:00 ago" in problem


@pytest.mark.parametrize("created", [None, "1700000000000", True])
def test_a_run_without_a_readable_start_is_reported(created):
    runs = [make_run(NOW - timedelta(hours=8)), {**make_run(NOW, run_id="odd"), "created": created}]
    assert problems_for(runs) == ["runs without a readable start time (created): odd"]


def test_run_start_is_utc_to_the_millisecond():
    assert run_start({"created": 1589457343123}) == datetime(2020, 5, 14, 11, 55, 43, 123000, tzinfo=timezone.utc)


# --- the client


class FakeTaskApi:
    """Stands in for the requests module inside agol_analytics.utils.agol."""

    def __init__(self):
        self.gets: list[tuple[str, dict, dict]] = []
        self.replies: dict[str, FakeHttpResponse] = {}

    def get(self, url, params=None, **kwargs):
        self.gets.append((url, params, kwargs))
        return self.replies[url]


@pytest.fixture
def task_api(monkeypatch):
    import agol_analytics.utils.agol

    api = FakeTaskApi()
    monkeypatch.setattr(agol_analytics.utils.agol, "requests", api)
    return api


@pytest.fixture
def client():
    client = ArcGISReportClient()
    client.token = "EXAMPLE-token"
    return client


TASK_URL = f"{API_BASE}/community/users/EXAMPLE-owner/tasks/EXAMPLE-task-id"


def test_get_scheduled_task(task_api, client):
    task_api.replies[TASK_URL] = FakeHttpResponse(json_body=TASK)

    assert client.get_scheduled_task("EXAMPLE-owner", "EXAMPLE-task-id") == TASK
    [(url, params, kwargs)] = task_api.gets
    assert params == {"f": "json", "token": "EXAMPLE-token"}
    assert kwargs["timeout"] > 0


def test_get_scheduled_task_runs(task_api, client):
    runs = [make_run(NOW - timedelta(hours=8))]
    task_api.replies[f"{TASK_URL}/runs"] = FakeHttpResponse(json_body={"runs": runs})

    assert client.get_scheduled_task_runs("EXAMPLE-owner", "EXAMPLE-task-id") == runs


def test_a_reply_without_runs_is_no_runs(task_api, client):
    task_api.replies[f"{TASK_URL}/runs"] = FakeHttpResponse(json_body={})
    assert client.get_scheduled_task_runs("EXAMPLE-owner", "EXAMPLE-task-id") == []


def test_an_error_reply_raises(task_api, client):
    # AGOL answers an unknown task with HTTP 200 and an error body
    task_api.replies[TASK_URL] = FakeHttpResponse(json_body={"error": {
        "code": 400, "message": "Task not found.", "details": ["Invalid task id."]}})

    with pytest.raises(AgolRequestError,
                       match="task EXAMPLE-task-id of EXAMPLE-owner: 400; Task not found.; Invalid task id."):
        client.get_scheduled_task("EXAMPLE-owner", "EXAMPLE-task-id")


def test_an_http_error_raises(task_api, client):
    task_api.replies[f"{TASK_URL}/runs"] = FakeHttpResponse(status_code=503)
    with pytest.raises(requests.HTTPError):
        client.get_scheduled_task_runs("EXAMPLE-owner", "EXAMPLE-task-id")
