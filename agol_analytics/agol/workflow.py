import pandas as pd
from pytz import timezone
from datetime import datetime, timedelta, date


def process_logins(df_list, pr_df):
    df  = pd.concat(df_list).drop_duplicates(subset=['reqId'])
    df = clean_agol_logins(df)
    return join_and_organize_logins(login_df=df, pr_df=pr_df)


def clean_agol_logins(df):
    df = (df.drop(columns=['idType', 'orgId', 'action', 'ip'])
            .rename(columns={'request': 'request_slug',
                             'reqId': 'request_id',
                             'clientId': 'application_id',
                             'created': 'request_time'}))
    df['request_date'] = (pd.to_datetime(df.request_time, unit='ms', utc=True)
                            .dt.tz_convert(tz='EST')
                            .dt.strftime('%Y-%m-%d'))
    df['id'] = df.id.str.rstrip('_TuftsGIS')
    return df


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

def get_datetime(query_date: any):
    datetime_fmt_str = '%Y-%m-%d'
    if type(query_date) is date:
        return datetime(year=query_date.year,
                        month=query_date.month,
                        day=query_date.day,
                        tzinfo=timezone('EST'))
    return (datetime.strptime(query_date, datetime_fmt_str)
            .replace(tzinfo=timezone('EST')))


def generate_date_range(start_date, end_date):
    start_date = get_datetime(start_date)
    end_date = get_datetime(end_date)
    assert start_date <= end_date
    return [start_date + timedelta(days=x) for x
             in range((end_date - start_date).days + 1)]



