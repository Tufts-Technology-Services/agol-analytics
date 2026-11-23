from os import path
import calendar
import requests
from datetime import datetime, timedelta
import pandas as pd
import io
import json

from ..validation import HISTORY_COLUMNS, AgolDataError

# the most logins AGOL returns per request: asking for more still returns 10,000 (checked October 2026)
HISTORY_ROW_LIMIT = 10000
# a day takes a request per HISTORY_ROW_LIMIT logins, plus one; busy days have had more than 10,000
MAX_HISTORY_REQUESTS = 20

# seconds to wait for a reply to a scheduled-task request
TASK_REQUEST_TIMEOUT = 60


class AgolTokenError(Exception):
    """ArcGIS Online didn't issue a token, e.g. because the credentials were rejected."""


class AgolRequestError(Exception):
    """ArcGIS Online answered a request with an error, e.g. a task that doesn't exist or can't be read."""


class ArcGISReportClient:
    token = None

    def __init__(self, baseurl='https://tuftsgis.maps.arcgis.com'):
        self.api_base = path.join(baseurl, 'sharing/rest')

    def get_token(self, username, passwd, client='requestip'):
        request_body = {
            'username': username,
            'password': passwd,
            'client': client,
            'f': 'json'
        }
        r = requests.post(path.join(self.api_base, 'generateToken'), data=request_body)
        r.raise_for_status()
        resp = r.json()
        # AGOL answers a failed login with HTTP 200 and {"error": {"code", "message", "details"}}
        if 'token' not in resp:
            error = resp.get('error', {})
            reason = '; '.join([error.get('message', 'no token in the response')] + error.get('details', []))
            raise AgolTokenError(f"couldn't get an ArcGIS Online token for {username}: {reason}")
        self.token = resp['token']

    def get_single_day_agol_logins(self, single_date: datetime):
        """
        every login from single_date to the same time the next day. AGOL returns at most
        HISTORY_ROW_LIMIT logins per request (asking for more doesn't help, and CSV ignores `start`),
        oldest first. So each request after the first starts at the time of the last login so far,
        until one brings nothing new. That costs one extra request on a normal day, and still works
        if AGOL lowers the limit.
        """
        assert isinstance(single_date, datetime)  # includes pendulum's DateTime
        from_date, to_date = history_window(single_date)
        pages = []
        seen_request_ids: set = set()
        page_start = from_date
        for _ in range(MAX_HISTORY_REQUESTS):
            page = read_history_csv(self.request_history(page_start, to_date).text)
            # from the last login's time, inclusive, since several can share a millisecond: drop the repeats
            new_logins = page[~page['reqId'].isin(seen_request_ids)] if 'reqId' in page.columns else page
            if pages and new_logins.empty:
                break
            pages.append(new_logins)
            if page.empty or 'reqId' not in page.columns or 'created' not in page.columns:
                break  # nothing to continue from; validation reports missing columns
            seen_request_ids.update(page['reqId'])
            last_created = pd.to_numeric(page['created'], errors='coerce').max()
            if pd.isna(last_created):
                break  # validation reports the unreadable times
            # from the epoch milliseconds themselves: adding the time since midnight to from_date would be
            # local clock arithmetic, an hour out once the clocks change during the day
            page_start = from_epoch_milliseconds(int(last_created), from_date.tzinfo)
        else:
            raise AgolDataError(f"login history from {from_date.isoformat()} still had new logins after "
                                f"{MAX_HISTORY_REQUESTS} requests")
        return pd.concat(pages, ignore_index=True) if len(pages) > 1 else pages[0]

    def request_history(self, from_date: datetime, to_date: datetime, num: int = HISTORY_ROW_LIMIT,
                        response_format: str = 'csv', **extra_params) -> requests.Response:
        """the portal's login history from from_date up to to_date, as the raw response"""
        endpoint = path.join(self.api_base, 'portals/self/history')
        params = {
            'all': True,
            'sortOrder': 'asc',
            'actions': 'login',
            'token': self.token,
            'fromDate': ArcGISReportClient.get_timestamp(from_date),
            'toDate': ArcGISReportClient.get_timestamp(to_date),
            'num': num,
            'f': response_format,
            **extra_params,
        }
        r = requests.get(endpoint, params=params)
        r.raise_for_status()
        return r

    def get_scheduled_task(self, owner: str, task_id: str) -> dict:
        """a scheduled task (e.g. a notebook's), as AGOL describes it: active, taskState, cronSchedule..."""
        return self.request_task_json(owner, task_id)

    def get_scheduled_task_runs(self, owner: str, task_id: str) -> list[dict]:
        """the runs AGOL keeps for a scheduled task (a limited history), in no guaranteed order"""
        return self.request_task_json(owner, task_id, 'runs').get('runs', [])

    def request_task_json(self, owner: str, task_id: str, *subpath: str) -> dict:
        """a JSON reply from community/users/<owner>/tasks/<task_id>[/subpath]. AGOL reports errors such as
        an unknown task or a token without access as HTTP 200 with {"error": ...}: those raise AgolRequestError"""
        endpoint = path.join(self.api_base, 'community/users', owner, 'tasks', task_id, *subpath)
        r = requests.get(endpoint, params={'f': 'json', 'token': self.token}, timeout=TASK_REQUEST_TIMEOUT)
        r.raise_for_status()
        resp = r.json()
        if 'error' in resp:
            error = resp['error'] if isinstance(resp['error'], dict) else {}
            parts = [str(error.get('code', '')), str(error.get('message', 'an error reply'))]
            parts += [str(detail) for detail in error.get('details') or []]
            reason = '; '.join(part for part in parts if part)
            raise AgolRequestError(f"ArcGIS Online couldn't return task {task_id} of {owner}: {reason}")
        return resp

    @staticmethod
    def get_timestamp(single_datetime):
        """milliseconds since the epoch, in whole numbers (a float timestamp * 1000 can come out 1 ms low).
        A naive datetime is local time, as datetime.timestamp() takes it."""
        if single_datetime.tzinfo is None:
            single_datetime = single_datetime.astimezone()
        return calendar.timegm(single_datetime.utctimetuple()) * 1000 + single_datetime.microsecond // 1000


def from_epoch_milliseconds(milliseconds: int, tz=None) -> datetime:
    """the time AGOL's `created` value stands for, in tz (local time, naive, if tz is None)"""
    seconds, remainder = divmod(milliseconds, 1000)
    return datetime.fromtimestamp(seconds, tz).replace(microsecond=remainder * 1000)


def history_window(single_date: datetime) -> tuple[datetime, datetime]:
    """the times get_single_day_agol_logins asks for: single_date to the same time the next day"""
    return single_date, single_date + timedelta(days=1)


def read_history_csv(text: str) -> pd.DataFrame:
    """
    the history CSV as a DataFrame. Raises AgolDataError if ArcGIS Online sent an error instead: it
    reports errors such as an expired token as JSON, with HTTP 200, even when CSV was asked for
    """
    if text.lstrip().startswith('{'):
        try:
            error = json.loads(text).get('error')
        except (ValueError, AttributeError):
            error = None
        if not isinstance(error, dict):
            error = {}
        parts = [str(error.get('code', '')), str(error.get('message', 'a JSON reply, not CSV'))]
        parts += [str(detail) for detail in error.get('details') or []]
        reason = '; '.join(part for part in parts if part)
        raise AgolDataError(f"ArcGIS Online sent an error instead of login history: {reason}")
    if not text.strip():
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.read_csv(io.StringIO(text))
