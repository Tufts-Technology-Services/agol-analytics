"""Sanitized sample data (copied from the rt-analytics-airflow test fixtures) and fakes."""
from pathlib import Path

import pandas as pd
import requests

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# 68 logins on 2026-10-21 by 6 users: u780c49f and uf98345f end in letters of '_TuftsGIS';
# u379c89f isn't in pr_fis and its id has no _TuftsGIS suffix.
# Edited to match what the live portal sent in October 2026 (scripts/probe_agol_history.py): CRLF
# line endings; actor holds the (pseudonymized) username; rows 10 and 40 have API-key `data` JSON;
# row 20 has no ip; rows 30 and 31 share a millisecond; and a few of the rarer request types and
# clientIds, including an ip.<address> one.
SAME_MILLISECOND_ROWS = (30, 31)
USERS_ENDING_IN_SUFFIX_LETTERS = {"u780c49f": 15, "uf98345f": 10}
USER_NOT_IN_PR_FIS = "u379c89f"


def load_login_history() -> pd.DataFrame:
    """One day of AGOL login history, as ArcGISReportClient.get_single_day_agol_logins returns it."""
    return pd.read_csv(FIXTURES_DIR / "agol_history_sample.csv")


def load_pr_fis() -> pd.DataFrame:
    """The pr_fis_vw fields update_agol_logins reads, for the users in the sample."""
    return pd.read_csv(FIXTURES_DIR / "pr_fis_sample.csv", dtype=str)


class FakeHttpResponse:
    def __init__(self, status_code=200, text="", json_body=None):
        self.status_code = status_code
        self.text = text
        self._json_body = json_body

    def json(self):
        return self._json_body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)
