import os
from os import environ
from pandas import read_sql
from sqlalchemy import create_engine


def get_database_connection(driver, host, port, slug, username, password):
    conn_str = '{driver}://{username}:{password}@{host}:{port}/{slug}'
    engine = create_engine(conn_str.format(driver=driver, username=username,
                                           password=password, host=host,
                                           port=port, slug=slug))
    connection = engine.connect()
    return connection


def get_rt_database_connection():
    db_name = os.getenv('RT_DB_DATABASE', 'rt_analytics')
    host = os.getenv('RT_DB_HOST', 'localhost')
    return get_database_connection(driver='mysql+pymysql',
                                   host=host,
                                   port=3306,
                                   slug=db_name,
                                   username=environ['RT_DB_USERNAME'],
                                   password=environ['RT_DB_PASSWORD'])


def extract_sql_as_df(con, table, fields):
    if type(fields) is list:
        fields = ', '.join(fields)
    query_str = f'SELECT {fields} FROM {table}'

    return read_sql(sql=query_str, con=con)
