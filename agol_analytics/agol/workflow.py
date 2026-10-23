import pandas as pd
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# Tufts local time, with daylight saving (a fixed 'EST' zone is an hour off in summer)
EASTERN = ZoneInfo('America/New_York')


# the agol_logins table's columns, in its order
LOGIN_COLUMNS = ['request_id',
                 'request_date',
                 'request_time',
                 'request_slug',
                 'application_id',
                 'pr_identity_prid',
                 'user_primary_affiliation',
                 'user_pr_status',
                 'user_faculty',
                 'user_faculty_division',
                 'user_faculty_dept',
                 'user_primary_division',
                 'user_primary_dept_prog',
                 'user_primary_campus',
                 'pr_sis_primmajor1',
                 'pr_sis_derived_major',
                 'pr_sis_derived_degree']


def process_logins(df_list, pr_df):
    """clean one or more days of AGOL login history and add each user's PR details"""
    df = clean_agol_logins(pd.concat(df_list))
    return join_and_organize_logins(login_df=df, pr_df=pr_df)


def clean_agol_logins(df):
    """
    rename the AGOL history columns, date each login in Eastern time, strip the _TuftsGIS
    suffix from the username in ``id``, and keep one row per request
    """
    # errors='ignore': these aren't used, and validation warns if they go missing
    df = (df.drop(columns=['idType', 'orgId', 'action', 'ip'], errors='ignore')
            .rename(columns={'request': 'request_slug',
                             'reqId': 'request_id',
                             'clientId': 'application_id',
                             'created': 'request_time'}))
    df['request_date'] = (pd.to_datetime(df.request_time, unit='ms', utc=True)
                            .dt.tz_convert(EASTERN)
                            .dt.strftime('%Y-%m-%d'))
    # removesuffix, not rstrip: rstrip('_TuftsGIS') also strips trailing letters of the username
    df['id'] = df.id.str.removesuffix('_TuftsGIS')
    return df.drop_duplicates(subset=['request_id'], keep='last')


def join_and_organize_logins(login_df, pr_df):
    """
    add PR details from pr_df (keyed by pr_identity_utln) to cleaned logins. Logins by people
    who aren't in pr_df are kept, with empty PR fields.
    """
    join = login_df.merge(right=pr_df,
                          how='left',
                          left_on='id',
                          right_on='pr_identity_utln')
    return join[LOGIN_COLUMNS]

def get_datetime(query_date: any):
    """midnight Eastern time on the given date (a date, datetime or 'YYYY-MM-DD' string)"""
    datetime_fmt_str = '%Y-%m-%d'
    if not isinstance(query_date, date):  # datetime is a date too
        query_date = datetime.strptime(query_date, datetime_fmt_str)
    # zoneinfo, unlike pytz, gives the right offset when passed as tzinfo
    return datetime(year=query_date.year,
                    month=query_date.month,
                    day=query_date.day,
                    tzinfo=EASTERN)


def generate_date_range(start_date, end_date):
    start_date = get_datetime(start_date)
    end_date = get_datetime(end_date)
    assert start_date <= end_date
    return [start_date + timedelta(days=x) for x
             in range((end_date - start_date).days + 1)]



