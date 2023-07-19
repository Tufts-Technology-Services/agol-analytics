from os import path
import requests
from datetime import datetime, timedelta
import pandas as pd
import io

class ArcGISReportClient:
    token = None

    def __init__(self, baseurl='https://tuftsgis.maps.arcgis.com'):
        self.api_base = path.join(baseurl, 'sharing/rest')

    def get_token(self, username, passwd, client='requestip'):
        request_body = {
            'username': username,
            'password': passwd,
            'client': client,
            'f': 'json'
        }
        r = requests.post(path.join(self.api_base, 'generateToken'), data=request_body)
        r.raise_for_status()
        resp = r.json()
        self.token = resp['token']

    def get_single_day_agol_logins(self, single_date: datetime):
        assert type(single_date) is datetime

        endpoint = path.join(self.api_base, 'portals/self/history')
        params = {
            'all': True,
            'sortOrder': 'asc',
            'actions': 'login',
            'token': self.token,
            'fromDate': ArcGISReportClient.get_timestamp(single_date),
            'toDate': ArcGISReportClient.get_timestamp(single_date + timedelta(days=1)),
            'num': 100,
            'f': 'csv'
        }
        r = requests.get(endpoint, params=params)
        r.raise_for_status()

        return pd.read_csv(io.StringIO(r.text))

    @staticmethod
    def get_timestamp(single_datetime):
        return int(single_datetime.timestamp() * 1e3)


