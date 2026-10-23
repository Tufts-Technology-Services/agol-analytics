# agol-analytics

## Description
Part of RT Analytics. Collects ArcGIS Online (AGOL) login history for the Tufts portal
(tuftsgis.maps.arcgis.com), adds each user's PR details, and stores the result in the
`agol_logins` table of the rt_analytics database.

The rt-analytics-airflow `update_agol_logins` DAG uses this package's client and functions
(see "Using the pieces" below).

## Installation
`database-interface` and `analytics-utils` aren't on PyPI, and `analytics-utils` (like this
repo) is private, so installing needs a GitHub SSH key with read access.

- With uv, the git sources in `pyproject.toml` are used:
  ```
  uv sync
  ```
  Projects that depend on agol-analytics need their own `[tool.uv.sources]` entries for
  `agol-analytics`, `analytics-utils` and `database-interface`.
- With pip, install the git dependencies from `requirements.txt` first:
  ```
  pip install -r requirements.txt
  pip install .
  ```

Requires Python 3.11+ and pandas 2.1.2 or later (pandas 3 works).

## Usage
Load everything that's missing, up to yesterday:
```python
from database_interface import DatabaseInterface
from agol_analytics import update_agol_logins

update_agol_logins(DatabaseInterface(user, passwd, host=host), agol_user, agol_pass)
```

### Using the pieces
```python
from agol_analytics.agol.workflow import get_datetime, clean_agol_logins, join_and_organize_logins
from agol_analytics.utils.agol import ArcGISReportClient

client = ArcGISReportClient()
client.get_token(username=agol_user, passwd=agol_pass)
history = client.get_single_day_agol_logins(get_datetime("2026-10-21"))
logins = join_and_organize_logins(clean_agol_logins(history), pr_df)
```

## Behaviour

### Fetching
- `ArcGISReportClient.get_token` raises `AgolTokenError` with AGOL's explanation if no token is
  issued (AGOL reports rejected credentials as HTTP 200 with an error body). The password is
  never included in the message.
- `get_single_day_agol_logins(day)` requests the portal's `login` history as CSV, from `day` to
  the same time the next day. It takes a timezone-aware `datetime`, including pendulum's;
  `get_datetime(date)` gives midnight Eastern.
- One request returns at most 10,000 logins. More than that in a day would be dropped without a
  warning.

### Dates
All dates are Tufts local time (`America/New_York`, with daylight saving):
- `request_date` is the Eastern date of the login, so a login at 00:30 EDT belongs to that day,
  not the previous one.
- Each day's query runs from Eastern midnight to the next midnight, which is 23 or 25 hours on
  the days the clocks change.

### Cleaning (`clean_agol_logins`)
- Drops `idType`, `orgId`, `action` and `ip`, and renames `reqId`, `clientId`, `request` and
  `created` to `request_id`, `application_id`, `request_slug` and `request_time` (epoch ms).
- Removes the `_TuftsGIS` suffix from the username in `id`. Only the suffix is removed, so
  usernames ending in those letters are unchanged.
- Keeps one row per `request_id` (the last).

### PR details (`join_and_organize_logins`)
- Left join on `pr_identity_utln`. Logins by people who aren't in the PR data are kept, with empty
  PR fields.
- Returns the `agol_logins` table's columns, in its order, including `user_pr_status`.

### Loading (`update_agol_logins`)
- Creates the table if it doesn't exist, from `agol_analytics/sql/create_agol_logins.sql`. The SQL
  ships with the package and matches the production table. `request_id` is the primary key;
  `pr_identity_prid` is `CHAR(20)` and PR columns may be empty.
- On the first run it starts at the start of the current semester (from `analytics_utils`); after
  that, the day after the last stored `request_date`. It stops at yesterday, so a second run on
  the same day fetches nothing.
- Reads PR details from `pr_fis_vw` and appends the logins. Because `request_id` is the primary
  key, loading a day that's already stored fails rather than duplicating rows. (The Airflow DAG
  upserts instead.)

## Tests
```
uv run pytest
```
The sample data in `tests/fixtures/` is sanitized (pseudonymized usernames, IDs and IP
addresses). Nothing in the tests reaches ArcGIS Online or a database.

## Changes in 0.2.0
- No longer depends on the `arcgis` package; the client calls the REST API with `requests`.
- Dates use `America/New_York` with daylight saving, instead of a fixed `EST` zone. The old
  pytz-based midnight was 18 minutes off, which shifted each day's query window.
- Only the `_TuftsGIS` suffix is removed from usernames (`rstrip` removed trailing letters too).
- Logins by people not in the PR data are kept (previously dropped), and `user_pr_status` is
  included.
- The table SQL matches production and is included in the package.
- `get_token` raises `AgolTokenError` instead of `KeyError: 'token'`.

## Support
contact Research Technology for information.

## Project status
In development
