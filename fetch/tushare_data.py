import configparser
from datetime import datetime

import tushare as ts


def get_token():
    config = configparser.ConfigParser()
    config.read('config.ini')  # 读取配置文件
    return config['API']['tushare_token']


def fetch_fund_data(ts_code, start_date='20230101', end_date=None):
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')
    token = get_token()
    ts.set_token(token)
    pro = ts.pro_api()

    df = pro.fund_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)

    filename = ts_code.split('.')[0]

    # 保存为CSV文件
    df.to_csv(f'data/{filename}.csv', index=False)
