from os import environ
from arcgis.gis import GIS
from datetime import date
from datetime import datetime
from datetime import timedelta
from pytz import timezone
import pandas as pd
from pathlib import Path
import shutil


def get_tufts_agol_connection():
    return GIS(url='https://tuftsgis.maps.arcgis.com',
               username=environ['ARCGIS_API_USERNAME'],
               password=environ['ARCGIS_API_PASSWORD'])


def get_single_day_agol_logins(gis, date):
    assert type(date) is datetime
    to_date = date + timedelta(days=1) - timedelta(minutes=1)
    save_path = Path(environ['DATADIR'], 'agol', date.strftime('agol_%Y_%m_%d'))
    save_path.mkdir(parents=True, exist_ok=True)
    return gis.admin.history(start_date=date,
                             to_date=to_date,
                             num=-1,
                             all_events=True,
                             actions='login',
                             save_folder=str(save_path),
                             data_format='csv')


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
    data = [pd.read_csv(get_single_day_agol_logins(gis, date)) for date in dates]
    shutil.rmtree(Path(environ['DATADIR'], 'agol'))
    return pd.concat(data)
