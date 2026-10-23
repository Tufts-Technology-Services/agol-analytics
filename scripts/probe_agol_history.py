"""See what ArcGIS Online's portal history actually returns, and check it against what agol-analytics expects.

Run from the repo root:

    uv run python scripts/probe_agol_history.py

It asks for the AGOL username and password (those of Airflow's `agol` connection) unless AGOL_USERNAME
and AGOL_PASSWORD are set. They're only sent to ArcGIS Online. Neither they nor the token are written
to disk.

What it checks:
- Each of the last --days Eastern days, fetched as the client does (CSV), plus today so far. Also
  yesterday as JSON, to compare counts and see the JSON reply's paging fields.
- Whether `num` is honoured: one request covering all those days with num 10000, and one with 20000.
  Small pages (num 5, start 1 and 6) show whether paging works.
- What a window with no logins looks like (in the future), and how far back history goes (--old-days).
- What an invalid token returns, as CSV and as JSON. It doesn't try a wrong password, so the account
  can't get locked.

Writes to --out (default tmp_data/agol_history_probe/<timestamp>/, which git ignores):
  raw/               the responses as returned. They contain real usernames and IP addresses: keep
                     them private.
  summary.json/.txt  status codes, content types, columns, counts, value shapes (digits -> 9, letters
                     -> a/A), where each day's logins fall relative to the window, error replies, and
                     agol-analytics' validation results. No usernames or IP addresses, so safe to share.
"""
from __future__ import annotations

import argparse
import getpass
import io
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from agol_analytics.agol.workflow import EASTERN, get_datetime  # noqa: E402
from agol_analytics.utils.agol import (HISTORY_ROW_LIMIT, ArcGISReportClient, history_window,  # noqa: E402
                                      read_history_csv)
from agol_analytics.validation import USERNAME_SUFFIX, AgolDataError, validate_agol_history  # noqa: E402

# columns whose values say nothing about a person, so their counts can be shared. Not actor or owner:
# they hold usernames (actor is blank only in the sanitized fixtures)
SHAREABLE_VALUE_COLUMNS = ["idType", "action", "request", "clientId", "data"]
# for error replies, empty replies and the JSON paging fields: enough to read, too short for many rows
BODY_PREVIEW_CHARS = 400


def value_shape(value) -> str:
    """A value with its characters replaced by class, so it can be shared: 2026-10-20 -> 9999-99-99."""
    text = re.sub(r"\d", "9", str(value))
    text = re.sub(r"[A-Z]", "A", text)
    return re.sub(r"[a-z]", "a", text)[:60]


def body_preview(text: str) -> str:
    """The start of a reply with no logins in it (an error, a bare header), or a note if it has some."""
    is_json = text.lstrip().startswith("{")
    if USERNAME_SUFFIX in text or (not is_json and len(text.strip().splitlines()) > 1):
        return f"(not shown: {len(text.strip().splitlines())} lines, which may name users)"
    return text[:BODY_PREVIEW_CHARS]


def fetch(client, label, from_date, to_date, raw_dir: Path, **request_options) -> tuple[dict, str]:
    """One history request, saved to raw/<label>; returns what's safe to share about it, and the body."""
    started = time.monotonic()
    try:
        response = client.request_history(from_date, to_date, **request_options)
    except requests.HTTPError as failed:
        response = failed.response
    extension = "json" if request_options.get("response_format") == "json" else "csv"
    (raw_dir / f"{label}.{extension}").write_text(response.text, encoding="utf-8")
    params = {key: value for key, value in request_options.items() if key != "response_format"}
    return {"label": label, "from": from_date.isoformat(), "to": to_date.isoformat(),
            "format": request_options.get("response_format", "csv"), "params": params,
            "status": response.status_code, "content_type": response.headers.get("Content-Type"),
            "bytes": len(response.content), "seconds": round(time.monotonic() - started, 2)}, response.text


def summarize_csv(text: str, from_date: datetime, to_date: datetime) -> dict:
    """What a CSV reply holds: columns, counts, value shapes and where the logins fall in the window."""
    if text.lstrip().startswith("{") or not text.strip():
        return {"rows": 0, "body_start": body_preview(text)}
    rows = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    summary = {"rows": len(rows), "columns": list(rows.columns), "fields": {}}
    for name in rows.columns:
        values = rows[name]
        info = {"empty": int((values.str.strip() == "").sum()), "distinct": int(values.nunique()),
                "shapes": dict(Counter(values.map(value_shape)).most_common(5))}
        if name in SHAREABLE_VALUE_COLUMNS:
            # some clientIds are an address (ip.<address>)
            shareable = values.where(~values.str.startswith("ip."), "ip.(address)")
            info["values"] = dict(Counter(shareable).most_common(15))
        summary["fields"][name] = info
    if len(rows) == 0:
        summary["body_start"] = body_preview(text)
        return summary
    if "created" in rows.columns:
        created = pd.to_numeric(rows["created"], errors="coerce")
        start_ms, end_ms = from_date.timestamp() * 1000, to_date.timestamp() * 1000
        hours = (created - start_ms) / 3_600_000
        summary["created"] = {
            "unreadable": int(created.isna().sum()),
            "before_window": int((created < start_ms).sum()), "after_window": int((created >= end_ms).sum()),
            "first_hours_after_start": round(float(hours.min()), 2),
            "last_hours_after_start": round(float(hours.max()), 2),
            "sorted_ascending": bool(created.is_monotonic_increasing),
            "latest_login_hours_ago": round((time.time() * 1000 - float(created.max())) / 3_600_000, 2),
        }
    if "reqId" in rows.columns:
        summary["repeated_reqIds"] = int(rows["reqId"].duplicated().sum())
    if "id" in rows.columns:
        summary["users"] = int(rows["id"].nunique())
        summary["ids_without_suffix"] = int((~rows["id"].str.endswith(USERNAME_SUFFIX)).sum())
        summary["users_without_suffix"] = int(rows.loc[~rows["id"].str.endswith(USERNAME_SUFFIX), "id"].nunique())
    try:
        summary["validation"] = validate_agol_history(read_history_csv(text), from_date, to_date).as_dict()
    except AgolDataError as rejected:
        summary["validation"] = {"error": str(rejected)}
    return summary


def summarize_json(text: str) -> dict:
    """A JSON reply's top-level fields (lists only by length), and the keys of its items."""
    try:
        body = json.loads(text)
    except ValueError:
        return {"not_json": True, "starts_with_shape": value_shape(text[:40])}
    if not isinstance(body, dict):
        return {"type": type(body).__name__}
    summary = {"fields": {}, "item_keys": {}}
    for key, value in body.items():
        if isinstance(value, list):
            summary["fields"][key] = f"list of {len(value)}"
            summary["item_keys"][key] = dict(Counter(k for item in value if isinstance(item, dict) for k in item))
        elif key == "error" or not isinstance(value, dict):
            summary["fields"][key] = value
        else:
            summary["fields"][key] = f"object with keys {sorted(value)}"
    return summary


def request_ids(text: str) -> list[str]:
    if text.lstrip().startswith("{") or not text.strip():
        return []
    rows = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    return rows["reqId"].tolist() if "reqId" in rows.columns else []


def json_request_ids(text: str) -> list[str]:
    try:
        body = json.loads(text)
    except ValueError:
        return []
    items = next((value for value in body.values() if isinstance(value, list)), []) if isinstance(body, dict) else []
    return [str(item.get("reqId")) for item in items if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="output folder (default tmp_data/agol_history_probe/<timestamp>)")
    parser.add_argument("--days", type=int, default=7, help="how many past days to fetch one by one (default 7)")
    parser.add_argument("--old-days", default="90,180,365,730",
                        help="days ago to check, to see how far back history goes (default 90,180,365,730)")
    args = parser.parse_args()

    out_dir = args.out or REPO_ROOT / "tmp_data" / "agol_history_probe" / datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    username = os.environ.get("AGOL_USERNAME") or input("AGOL username: ")
    password = os.environ.get("AGOL_PASSWORD") or getpass.getpass("AGOL password: ")

    client = ArcGISReportClient()
    token_reply = requests.post(f"{client.api_base}/generateToken",
                                data={"username": username, "password": password, "client": "requestip", "f": "json"})
    token_body = token_reply.json()
    summary: dict = {"probed_at": datetime.now(EASTERN).isoformat(), "token": {
        "status": token_reply.status_code, "keys": sorted(token_body),
        "error": token_body.get("error"),
        "expires_in_minutes": (round((token_body["expires"] - time.time() * 1000) / 60000)
                               if isinstance(token_body.get("expires"), (int, float)) else None),
    }}
    if "token" not in token_body:
        print("No token:", token_body.get("error"), file=sys.stderr)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return 1
    client.token = token_body["token"]

    today = get_datetime(datetime.now(EASTERN).date())
    days = [today - timedelta(days=back) for back in range(args.days, 0, -1)]

    # 1. each day as the client fetches it, and today so far
    summary["days"] = []
    texts = {}
    for day in days + [today]:
        label = f"day_{day.date()}"
        request, texts[label] = fetch(client, label, *history_window(day), raw_dir)
        summary["days"].append({**request, **summarize_csv(texts[label], *history_window(day))})
        print(f"{label}: HTTP {request['status']}, {summary['days'][-1]['rows']} rows")

    # 1b. days that reached the per-request limit, fetched with the client's paging
    summary["paged_days"] = []
    for day in days:
        if next(d for d in summary["days"] if d["label"] == f"day_{day.date()}")["rows"] < HISTORY_ROW_LIMIT:
            continue
        requests_made = []
        paging_client = ArcGISReportClient()
        paging_client.token = client.token
        original_request = paging_client.request_history

        def counted_request(*request_args, **request_kwargs):
            requests_made.append(request_args[0].isoformat())
            return original_request(*request_args, **request_kwargs)

        paging_client.request_history = counted_request
        history = paging_client.get_single_day_agol_logins(day)
        history.to_csv(raw_dir / f"paged_day_{day.date()}.csv", index=False)
        created = pd.to_numeric(history["created"])
        summary["paged_days"].append({
            "label": f"paged_day_{day.date()}", "rows": len(history), "requests": len(requests_made),
            "request_starts": requests_made, "unique_reqIds": int(history["reqId"].nunique()),
            "last_hours_after_start": round((float(created.max()) - day.timestamp() * 1000) / 3_600_000, 2),
            "validation": validate_agol_history(history, *history_window(day)).as_dict()})

    # 2. yesterday as JSON
    yesterday = days[-1]
    request, text = fetch(client, "yesterday_json", *history_window(yesterday), raw_dir, response_format="json")
    summary["yesterday_json"] = {**request, **summarize_json(text),
                                 "same_reqIds_as_csv": set(json_request_ids(text)) == set(request_ids(texts[f"day_{yesterday.date()}"]))}

    # 3. is num honoured? all the days in one request
    total_by_day = sum(day["rows"] for day in summary["days"][:-1])
    summary["all_days_in_one_request"] = {"rows_fetched_day_by_day": total_by_day, "requests": []}
    for num in (10000, 20000):
        request, text = fetch(client, f"all_days_num_{num}", days[0], today, raw_dir, num=num)
        summary["all_days_in_one_request"]["requests"].append({**request, **summarize_csv(text, days[0], today)})

    # 4. paging: small pages from yesterday, CSV and JSON
    summary["paging"] = []
    for response_format in ("csv", "json"):
        pages = {}
        for start in (1, 6):
            label = f"page_{response_format}_start_{start}"
            request, text = fetch(client, label, *history_window(yesterday), raw_dir,
                                  num=5, start=start, response_format=response_format)
            ids = request_ids(text) if response_format == "csv" else json_request_ids(text)
            pages[start] = ids
            summary["paging"].append({**request, "rows": len(ids),
                                      **({"json": summarize_json(text)} if response_format == "json" else {})})
        summary["paging"].append({"format": response_format,
                                  "pages_overlap": bool(set(pages[1]) & set(pages[6])),
                                  "second_page_follows_first": pages[6][:1] != pages[1][:1] and bool(pages[6])})

    # 5. no logins (the future) and long ago
    summary["empty_window"] = []
    future = today + timedelta(days=2)
    for response_format in ("csv", "json"):
        request, text = fetch(client, f"future_{response_format}", *history_window(future), raw_dir,
                              response_format=response_format)
        summary["empty_window"].append({**request, "body_start": body_preview(text)})
    summary["old_days"] = []
    for back in (int(part) for part in args.old_days.split(",") if part.strip()):
        day = today - timedelta(days=back)
        request, text = fetch(client, f"old_day_{back}", *history_window(day), raw_dir)
        csv_summary = summarize_csv(text, *history_window(day))
        summary["old_days"].append({**request, "days_ago": back, "rows": csv_summary["rows"],
                                    "validation": csv_summary.get("validation"),
                                    "body_start": csv_summary.get("body_start")})

    # 6. an invalid token, and none
    summary["bad_token"] = []
    for label, token in (("invalid_token", "EXAMPLE-not-a-token"), ("no_token", None)):
        bad_client = ArcGISReportClient()
        bad_client.token = token
        for response_format in ("csv", "json"):
            request, text = fetch(bad_client, f"{label}_{response_format}", *history_window(yesterday), raw_dir,
                                  response_format=response_format)
            try:
                client_reaction = f"returned {len(read_history_csv(text))} rows"
            except AgolDataError as rejected:
                client_reaction = f"raised AgolDataError: {rejected}"
            summary["bad_token"].append({**request, "body_start": body_preview(text),
                                         "read_history_csv": client_reaction})

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "summary.txt").write_text("\n".join(summary_lines(summary)) + "\n", encoding="utf-8")
    print("\n".join(summary_lines(summary)))
    print(f"\nWrote {out_dir}. Share summary.json and summary.txt; keep raw/ private.")
    return 0


def summary_lines(summary: dict) -> list[str]:
    lines = [f"Probed {summary['probed_at']}",
             f"token: HTTP {summary['token']['status']}, keys {summary['token']['keys']}, "
             f"expires in {summary['token']['expires_in_minutes']} min", "", "Days, as the client fetches them:"]
    for day in summary.get("days", []):
        created = day.get("created", {})
        validation = day.get("validation", {})
        lines.append(f"  {day['label']}: HTTP {day['status']} {day['content_type']}, {day['rows']} rows, "
                     f"{day.get('users', 0)} users ({day.get('users_without_suffix', 0)} without the suffix), "
                     f"{created.get('before_window', 0)} before / {created.get('after_window', 0)} after the window, "
                     f"hours {created.get('first_hours_after_start')}-{created.get('last_hours_after_start')}, "
                     f"errors {len(validation.get('errors', []))}, warnings {len(validation.get('warnings', []))}")
    if summary.get("paged_days"):
        lines += ["", "Days over the per-request limit, with the client's paging:"]
    for day in summary.get("paged_days", []):
        lines.append(f"  {day['label']}: {day['rows']} rows ({day['unique_reqIds']} unique) in {day['requests']} "
                     f"requests, last login {day['last_hours_after_start']} h after midnight, "
                     f"errors {day['validation']['errors']}")
    lines += ["", f"Yesterday as JSON: {summary.get('yesterday_json', {}).get('fields')}",
              f"  same reqIds as CSV: {summary.get('yesterday_json', {}).get('same_reqIds_as_csv')}", "",
              f"All days in one request (day by day: {summary['all_days_in_one_request']['rows_fetched_day_by_day']} rows):"]
    for request in summary["all_days_in_one_request"]["requests"]:
        lines.append(f"  num {request['params'].get('num')}: HTTP {request['status']}, {request['rows']} rows")
    lines += ["", "Paging (num 5):"]
    lines += [f"  {entry}" for entry in summary.get("paging", [])]
    lines += ["", "Window with no logins:"]
    lines += [f"  {entry['format']}: HTTP {entry['status']} {entry['content_type']}, {entry['bytes']} bytes: "
              f"{entry['body_start']!r}" for entry in summary.get("empty_window", [])]
    lines += ["", "Old days:"]
    lines += [f"  {entry['days_ago']} days ago: HTTP {entry['status']}, {entry['rows']} rows"
              for entry in summary.get("old_days", [])]
    lines += ["", "Bad tokens:"]
    lines += [f"  {entry['label']}: HTTP {entry['status']} {entry['content_type']}: {entry['body_start']!r}; "
              f"read_history_csv {entry['read_history_csv']}" for entry in summary.get("bad_token", [])]
    return lines


if __name__ == "__main__":
    sys.exit(main())
