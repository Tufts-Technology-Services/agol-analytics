from os import environ
from arcgis.gis import GIS
from datetime import date
from datetime import datetime
from datetime import timedelta
from pytz import timezone
import pandas as pd


def get_tufts_agol_connection():
    return GIS(url='https://tuftsgis.maps.arcgis.com',
               username=environ['ARCGIS_API_USERNAME'],
               password=environ['ARCGIS_API_PASSWORD'])


def get_single_day_agol_logins(gis, date):
    assert type(date) is datetime
    to_date = date + timedelta(days=1) - timedelta(milliseconds=1)
    return gis.admin.history(start_date=date,
                             to_date=to_date,
                             num=-1,
                             all_events=True,
                             actions='login',
                             data_format='df')


def get_datetime(input):
    datetime_fmt_str = '%Y-%m-%d'
    if type(input) is date:
        return datetime(year=input.year,
                        month=input.month,
                        day=input.day,
                        tzinfo=timezone('EST'))
    return (datetime.strptime(input, datetime_fmt_str)
                    .replace(tzinfo=timezone('EST')))


def get_agol_logins(gis, start_date, end_date):
    start_date = get_datetime(start_date)
    end_date = get_datetime(end_date)
    assert start_date <= end_date
    dates = [start_date + timedelta(days=x) for x
             in range((end_date - start_date).days + 1)]
    print(dates)
    data = [get_single_day_agol_logins(gis, date) for date in dates]
    return pd.concat(data)
