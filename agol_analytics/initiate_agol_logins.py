from .agol.workflow import generate_agol_logins
from .utils.database import get_rt_database_connection
from sqlalchemy.types import NVARCHAR
from sqlalchemy.types import CHAR
from sqlalchemy import DateTime
from sqlalchemy import Date
import sys


def main():
    start_date = '2021-07-01'
    end_date = '2021-12-31'
    pr_table = 'pr_fis_2021spring'
    agol_table = 'agol_logins'
    con = get_rt_database_connection()
    df = generate_agol_logins(con, pr_table, start_date, end_date)
    df.to_sql(name=agol_table,
              con=con,
              if_exists='fail',
              index=False,
              dtype={'request_id': CHAR(32),
                     'request_date': Date(),
                     'request_time': DateTime(),
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
                     'pr_sis_derived_degree': NVARCHAR(25)})
    command = 'ALTER TABLE {table} ADD PRIMARY KEY ({key})'
    con.execute(command.format(table=agol_table, key='request_id'))
    con.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
