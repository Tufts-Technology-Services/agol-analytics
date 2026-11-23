# agol-analytics

## Description
Part of RT Analytics. Collects ArcGIS Online (AGOL) login history for the Tufts portal
(tuftsgis.maps.arcgis.com), adds each user's PR details, and stores the result in the
`agol_logins` table of the rt_analytics database.

The rt-analytics-airflow `update_agol_logins` DAG uses this package's client and functions
(see "Using the pieces" below).

## Installation
Neither this package nor `database-interface` is on PyPI; both install from GitHub over HTTPS.

- With pip, from another project (`database-interface` first, since pip would look for it on PyPI):
  ```
  pip install "database-interface @ git+https://github.com/Tufts-Technology-Services/analytics-database-interface.git"
  pip install "agol-analytics @ git+https://github.com/Tufts-Technology-Services/agol-analytics.git@v0.3.0"
  ```
- With uv, the git sources in `pyproject.toml` are used:
  ```
  uv sync
  ```
  Projects that depend on agol-analytics need their own `[tool.uv.sources]` entries for
  `agol-analytics` and `database-interface`.
- With pip, install the git dependencies from `requirements.txt` first:
  ```
  pip install -r requirements.txt
  pip install .
  ```

Requires Python 3.11+ and pandas 2.1.2 or later (pandas 3 works).

## Usage
Load everything that's missing, up to yesterday:
```python
from datetime import date
from database_interface import DatabaseInterface
from agol_analytics import update_agol_logins

dbi = DatabaseInterface(user, passwd, host=host)
update_agol_logins(dbi, agol_user, agol_pass)

# on an empty table, say where to start
update_agol_logins(dbi, agol_user, agol_pass, first_day=date(2026, 9, 1))
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
- AGOL returns at most 10,000 logins per request, oldest first. Asking for more doesn't help, and
  the CSV format ignores `start`. So the client asks again from the time of the last login so far
  (its exact `created` value, so this holds on the days the clocks change), dropping the repeats,
  until a request brings nothing new. A normal day takes two requests. Busy
  days do pass 10,000: on 2026-10-20 one account's ArcGIS Pro token requests did.
- AGOL sends some errors, such as an invalid token, as JSON with HTTP 200 even when CSV was asked
  for. Those raise `AgolDataError` with AGOL's code and message. Others come back as HTTP errors.
- A day with no logins comes back as just the header line, which gives an empty table.

### Validation (`agol_analytics.validation`)
`check_agol_history(history, from_date, to_date, raw_data_path=None)` checks a day's history before
any processing, so changes at AGOL get noticed. `update_agol_logins` runs it on every day, and so
does the Airflow DAG's extract task.
- Errors raise `AgolDataError`:
  - a column the processing uses (`id`, `created`, `request`, `reqId`, `clientId`) is missing;
  - `created` isn't whole epoch milliseconds;
  - `reqId` or `id` is empty;
  - an action other than `login`.
- Warnings are logged and the run carries on:
  - a new column, or a missing column that cleaning drops anyway;
  - a day with no logins;
  - logins outside the requested window, or out of time order (the paging relies on the order);
  - repeated `reqId`s or empty `clientId`s;
  - usernames without the `_TuftsGIS` suffix. A few dozen logins a day is normal; those users get
    no PR details.
- With `raw_data_path`, the report is saved next to the raw file as `<raw file>.validation.json`,
  before raising. Reports quote request IDs, never usernames or IP addresses.

`scripts/probe_agol_history.py` checks these assumptions against the live portal (see its
docstring). Its summary is safe to share; its `raw/` folder isn't.

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
- Starts the day after the last stored `request_date`. On an empty table it starts at
  `first_day`, and raises `ValueError` before fetching anything if that isn't given. It stops at
  yesterday, so a second run on the same day fetches nothing.
- Reads PR details from `pr_fis_vw` and appends the logins. Because `request_id` is the primary
  key, loading a day that's already stored fails rather than duplicating rows. (The Airflow DAG
  upserts instead.)

## Tests
```
uv run pytest
```
The sample data in `tests/fixtures/` is sanitized (pseudonymized usernames, IDs and IP
addresses). Nothing in the tests reaches ArcGIS Online or a database.

## Changes in 0.3.0
- No longer depends on `analytics-utils`. On an empty table, `update_agol_logins` now starts at
  the new `first_day` argument instead of the start of the current semester, and raises
  `ValueError` without it.

## Changes in 0.2.1
- On the days the clocks change, paging past the 10,000-row cap no longer skips (in November) or
  refetches (in March) an hour of logins: each request continues from the last login's exact time.

## Changes in 0.2.0
- Days with more than 10,000 logins are fetched in full. Before, everything after the 10,000th
  login of a day was lost without a warning.
- AGOL's history is validated before processing (see "Validation"). Error replies raise
  `AgolDataError` instead of being read as CSV.
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
