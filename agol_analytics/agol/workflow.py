from .utils.agol import get_tufts_agol_connection
from .utils.agol import get_agol_logins
from .utils.database import extract_sql_as_df
import pandas as pd


def clean_agol_logins(df):
    df = (df.drop(columns=['idType', 'orgId', 'action', 'ip'])
            .rename(columns={'request': 'request_slug',
                             'reqId': 'request_id',
                             'appId': 'application_id'}))
    df['request_time'] = (pd.to_datetime(df.created, unit='ms', utc=True)
                            .dt.tz_convert(tz='EST'))
    df['request_date'] = df.request_time.dt.date
    df['id'] = df.id.str.rstrip('_TuftsGIS')
    return df


def get_pr_table(con, pr_table):
    fields = ['pr_identity_utln',
             'pr_identity_prid',
             'user_primary_affiliation',
             'user_primary_division',
             'user_primary_dept_prog',
             'user_primary_campus',
             'user_faculty',
             'user_faculty_division',
             'user_faculty_dept',
             'pr_sis_primmajor1',
             'pr_sis_derived_major',
             'pr_sis_derived_degree']
    return extract_sql_as_df(con=con, table=pr_table, fields=fields)


def join_and_organize_logins(login_df, pr_df):
    join = login_df.merge(right=pr_df,
                          how='inner',
                          left_on='id',
                          right_on='pr_identity_utln')
    columns = ['request_id',
               'request_date',
               'request_time',
               'request_slug',
               'application_id',
               'pr_identity_prid',
               'user_primary_affiliation',
               'user_primary_division',
               'user_primary_dept_prog',
               'user_primary_campus',
               'user_faculty',
               'user_faculty_division',
               'user_faculty_dept',
               'pr_sis_primmajor1',
               'pr_sis_derived_major',
               'pr_sis_derived_degree']
    return join[columns]


def generate_agol_logins(con, pr_table, start_date, end_date):
    gis = get_tufts_agol_connection()
    df = clean_agol_logins(get_agol_logins(gis, start_date, end_date))
    return join_and_organize_logins(df, get_pr_table(con, pr_table))
