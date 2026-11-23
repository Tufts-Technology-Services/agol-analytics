from database_interface import DatabaseInterface
from datetime import date, timedelta
import os

from .agol.workflow import generate_date_range, process_logins

import logging

from .utils import ArcGISReportClient
from .utils.agol import history_window
from .validation import check_agol_history

LOG = logging.getLogger(__name__)


def ensure_table(db_interface: DatabaseInterface) -> None:
    sql = os.path.join(os.path.abspath(os.path.dirname(__file__)), './sql/create_agol_logins.sql')
    LOG.info(f'ensuring table from {sql}')
    db_interface.execute_sql_file(sql)



def get_login_data(agol_user:str, agol_pass:str, dates: list) -> list:
    """each day's login history, checked; raises AgolDataError on the first day that can't be processed"""
    cl = ArcGISReportClient()
    cl.get_token(username=agol_user, passwd=agol_pass)
    login_data = []
    for d in dates:
        history = cl.get_single_day_agol_logins(d)
        check_agol_history(history, *history_window(d))
        login_data.append(history)
    return login_data


def update_agol_logins(db_interface: DatabaseInterface, agol_user: str, agol_pass: str,
                       first_day: date | None = None) -> None:
    """
    Load every day from the one after the last stored request_date up to yesterday.

    :param first_day: where to start when agol_logins is empty; ignored once it has rows. Required
        on an empty table.
    """
    ensure_table(db_interface)

    pr_table = 'pr_fis_vw'
    agol_table = 'agol_logins'
    date_field = 'request_date'

    today = date.today()
    last_stored_date = db_interface.check_last_date(date_field, agol_table)
    if last_stored_date is not None:
        start_date = last_stored_date + timedelta(days=1)
    elif first_day is not None:
        start_date = first_day
    else:
        raise ValueError(f'{agol_table} is empty: pass first_day, the first day to load')

    end_date = today - timedelta(days=1)

    if start_date <= end_date:
        fields = ['pr_identity_utln',
                  'pr_identity_prid',
                  'user_primary_affiliation',
                  'user_pr_status',
                  'user_primary_division',
                  'user_primary_dept_prog',
                  'user_primary_campus',
                  'user_faculty',
                  'user_faculty_division',
                  'user_faculty_dept',
                  'pr_sis_primmajor1',
                  'pr_sis_derived_major',
                  'pr_sis_derived_degree']
        pr_df = db_interface.read_df(pr_table, cols=fields)



        dates = generate_date_range(start_date, end_date)
        login_data = get_login_data(agol_user, agol_pass, dates)
        login_df = process_logins(login_data, pr_df)

        LOG.info(f'appending agol login data from {start_date} to {end_date}')
        db_interface.append_df(login_df, agol_table)
