from .agol.workflow import generate_agol_logins
from .utils.database import get_rt_database_engine, has_table
from analytics_utils import get_semester_start
from sqlalchemy.types import NVARCHAR
from sqlalchemy.types import BIGINT
from sqlalchemy.types import CHAR
from sqlalchemy import Date
from sqlalchemy import text
from datetime import date, timedelta
import sys


def update_agol_logins():
    pr_table = 'pr_fis_vw'
    agol_table = 'agol_logins'
    date_field = 'request_date'
    date_query = f'SELECT MAX({date_field}) FROM {agol_table};'
    with get_rt_database_engine().connect() as con:
        today = date.today()
        start_date = get_semester_start(today)

        if has_table(agol_table):
            last_stored_date = con.execute(text(date_query)).scalar_one_or_none()
            if last_stored_date is not None:
                start_date = last_stored_date + timedelta(days=1)
        end_date = today - timedelta(days=1)
        if start_date <= end_date:
            df = generate_agol_logins(con, pr_table, start_date, end_date)
            df.to_sql(name=agol_table,
                      con=con,
                      if_exists='append',
                      index=False,
                      dtype={'request_id': CHAR(32),
                             'request_date': Date(),
                             'request_time': BIGINT(),
                             'request_slug': NVARCHAR(255),
                             'application_id': NVARCHAR(255),
                             'pr_identity_prid': CHAR(9),
                             'user_primary_affiliation': NVARCHAR(25),
                             'user_primary_division': NVARCHAR(255),
                             'user_primary_dept_prog': NVARCHAR(255),
                             'user_primary_campus': NVARCHAR(25),
                             'user_faculty': CHAR(1),
                             'user_faculty_division': NVARCHAR(255),
                             'user_faculty_dept': NVARCHAR(255),
                             'pr_sis_primmajor1': NVARCHAR(255),
                             'pr_sis_derived_major': NVARCHAR(255),
                             'pr_sis_derived_degree': NVARCHAR(25)}
                      )
    return 0


if __name__ == '__main__':
    sys.exit(update_agol_logins())
