from .agol.workflow import generate_agol_logins
from .utils.database import get_rt_database_connection
from analytics_utils import get_semester_start
from datetime import date, timedelta
import sys


def update_agol_logins():
    pr_table = 'pr_fis'
    agol_table = 'agol_logins'
    date_field = 'request_date'
    date_query = f'SELECT MAX({date_field}) FROM {agol_table};'
    with get_rt_database_connection() as con:
        today = date.today()
        last_stored_date = con.execute(date_query).scalar_one_or_none()
        if last_stored_date is None:
            start_date = get_semester_start(today)
        else:
            start_date = last_stored_date + timedelta(days=1)
        end_date = today - timedelta(days=1)
        if start_date <= end_date:
            df = generate_agol_logins(con, pr_table, start_date, end_date)
            df.to_sql(name=agol_table,
                      con=con,
                      if_exists='append',
                      index=False)
    return 0


if __name__ == '__main__':
    sys.exit(update_agol_logins())
