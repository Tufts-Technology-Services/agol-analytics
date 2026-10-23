"""process_logins on the sanitized sample."""
import pandas as pd

from agol_analytics.agol.workflow import clean_agol_logins, process_logins
from sample_data import USER_NOT_IN_PR_FIS, USERS_ENDING_IN_SUFFIX_LETTERS, load_login_history, load_pr_fis

OUTPUT_COLUMNS = ["request_id", "request_date", "request_time", "request_slug", "application_id",
                  "pr_identity_prid", "user_primary_affiliation", "user_pr_status", "user_faculty",
                  "user_faculty_division", "user_faculty_dept", "user_primary_division", "user_primary_dept_prog",
                  "user_primary_campus", "pr_sis_primmajor1", "pr_sis_derived_major", "pr_sis_derived_degree"]


def test_output_columns():
    assert process_logins([load_login_history()], load_pr_fis()).columns.tolist() == OUTPUT_COLUMNS


def test_requests_repeated_across_days_are_kept_once():
    history = load_login_history()
    logins = process_logins([history, history.head(10)], load_pr_fis())
    assert logins.request_id.is_unique


def test_only_the_tuftsgis_suffix_is_removed():
    history = pd.DataFrame({"id": ["u780c49f_TuftsGIS", "uf98345f_TuftsGIS", "u379c89f"],
                            "idType": "u", "orgId": "o", "action": "login", "ip": "10.0.0.1",
                            "request": "/sharing", "reqId": ["a", "b", "c"], "clientId": "arcgisonline",
                            "created": 1792628144007})
    assert clean_agol_logins(history).id.tolist() == ["u780c49f", "uf98345f", "u379c89f"]


def test_users_ending_in_suffix_letters_get_their_pr_details():
    pr_fis = load_pr_fis()
    logins = process_logins([load_login_history()], pr_fis)

    for utln, login_count in USERS_ENDING_IN_SUFFIX_LETTERS.items():
        prid = pr_fis.loc[pr_fis.pr_identity_utln == utln, "pr_identity_prid"].item()
        assert (logins.pr_identity_prid == prid).sum() == login_count


def test_logins_by_users_not_in_pr_fis_are_kept_without_pr_details():
    history = load_login_history()
    logins = process_logins([history], load_pr_fis())

    assert len(logins) == len(history) == 68
    unmatched = logins[logins.pr_identity_prid.isna()]
    unmatched_history = history[history.id.str.removesuffix("_TuftsGIS") == USER_NOT_IN_PR_FIS]
    assert sorted(unmatched.request_id) == sorted(unmatched_history.reqId) and len(unmatched) == 5
    assert unmatched.user_primary_affiliation.isna().all()


def test_cleaning_keeps_one_row_per_request():
    history = load_login_history()
    cleaned = clean_agol_logins(pd.concat([history, history.head(10)]))
    assert cleaned.request_id.is_unique
    assert len(cleaned) == 68


def test_logins_are_dated_on_the_eastern_day():
    # the sample's logins run from 00:15 EDT on 2026-10-21, which is 2026-10-22 in UTC for some
    logins = process_logins([load_login_history()], load_pr_fis())
    assert set(logins.request_date) == {"2026-10-21"}
