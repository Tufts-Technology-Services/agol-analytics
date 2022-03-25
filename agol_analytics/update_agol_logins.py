from .agol.workflow import generate_agol_logins
from .utils.database import get_rt_database_connection
from datetime import date
from datetime import timedelta
import sys


def main():
    pr_table = 'pr_fis'
    agol_table = 'agol_logins'
    max_query = 'SELECT MAX({field}) FROM {table};'
    date_query = max_query.format(field='request_date', table=agol_table)
    con = get_rt_database_connection()
    start_date = con.execute(date_query).scalar_one() + timedelta(days=1)
    end_date = date.today() - timedelta(days=1)
    if start_date <= end_date:
        df = generate_agol_logins(con, pr_table, start_date, end_date)
        df.to_sql(name=agol_table,
                  con=con,
                  if_exists='append',
                  index=False)
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
