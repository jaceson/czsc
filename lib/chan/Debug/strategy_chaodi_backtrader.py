import os,sys,getopt,json
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
sys.path.insert(0,parentdir)

import talib
from MyTT import *
import baostock as bs
import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta

class ChaoDIStrategy(bt.Strategy):
    """docstring for ChaoDIStrategy"""
    def __init__(self):
        self.order = None
        

def read_json(path):
    with open(path, 'r') as file:
        data = json.load(file)
        return data

def write_json(data, path):
    with open(path, 'w') as file:
        json.dump(data, file, indent=4)

# baostock查询结果转换成数组
def querydata_to_list(rs):
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)
    return result

def can_stock_chaodi(code):
    # 获取当前日期
    current_date = datetime.now()
    # 计算90天之前的日期
    date_90_days_ago = current_date - timedelta(days=DAYS_NUM)
    # 最后一天交易日
    last_trading_day = get_latest_trade_date()

    # 获取当前日期
    current_date_str = current_date.strftime('%Y-%m-%d')
    date_90_days_ago_str = date_90_days_ago.strftime('%Y-%m-%d')
    
    rs = bs.query_history_k_data_plus(
            code=code,
            fields="date,open,high,low,close,volume,amount,turn",
            start_date=date_90_days_ago_str,
            end_date=current_date_str,
            frequency="d",
            adjustflag="2",
        )
    # print('query_history_k_data_plus respond error_code:' + rs.error_code)
    # print('query_history_k_data_plus respond  error_msg:' + rs.error_msg)
    result = querydata_to_list(rs)

    # 数据转换pd
    df = pd.DataFrame(result)
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df.set_index('date', inplace=True)

    # 计算VAR1
    df['LLV_low_10'] = LLV(df['low'], 10)
    df['HHV_high_10'] = HHV(df['high'], 10)
    df['VAR1'] = (df['close'] - df['LLV_low_10']) / (df['HHV_high_10'] - df['LLV_low_10']) * 100
    df['K0'] = SMA(df['VAR1'], 10, 1)
    df['D0'] = REF(df['K0'], 1)
    df['KD0'] = df['K0']-df['D0']
    
    df['K1'] = REF(df['K0'], 1)
    df['D1'] = REF(df['K0'], 2)
    df['KD1'] = df['K1']-df['D1']
    
    df['K2'] = REF(df['K0'], 2)
    df['D2'] = REF(df['K0'], 3)
    df['KD2'] = df['K2']-df['D2']
    
    df['K3'] = REF(df['K0'], 3)
    df['D3'] = REF(df['K0'], 4)
    df['KD3'] = df['K3']-df['D3']
    
    df['K4'] = REF(df['K0'], 4)
    df['D4'] = REF(df['K0'], 5)
    df['KD4'] = df['K4']-df['D4']
    
    df['K5'] = REF(df['K0'], 5)
    df['D5'] = REF(df['K0'], 6)
    df['KD5'] = df['K5']-df['D5']
    
    df['K6'] = REF(df['K0'], 6)
    df['D6'] = REF(df['K0'], 7)
    df['KD6'] = df['K6']-df['D6']
    
    df['K7'] = REF(df['K0'], 7)
    df['D7'] = REF(df['K0'], 8)
    df['KD7'] = df['K7']-df['D7']
    
    df['K8'] = REF(df['K0'], 8)
    df['D8'] = REF(df['K0'], 9)
    df['KD8'] = df['K8']-df['D8']
    
    df['K9'] = REF(df['K0'], 9)
    df['D9'] = REF(df['K0'], 10)
    df['KD9'] = df['K9']-df['D9']
    
    # 筛选符合条件的股票
    conditions1 = (
        (df['KD0'] > 0) & (df['K1'] < 30) &
        (df['KD1'] < 0) & (df['KD1'] > -0.5) &
        (df['KD2'] < 0) & (df['KD3'] < 0) &
        (df['KD4'] < 0) & (df['KD5'] < 0) &
        (df['KD6'] < 0) & (df['KD7'] < 0) &
        (df['KD8'] < 0) & (df['KD9'] < 0)
    )
    conditions2 = (
        (df['K0'] < 30) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
    # 获取符合条件的日期
    if not df[conditions1].empty:
        selected_dates = df[conditions1].index
        selected_dates = selected_dates.values
        if selected_dates[0] == last_trading_day:
            print(code)
            print("符合条件的日期：", selected_dates[0])
    elif not df[conditions2].empty:
        selected_dates = df[conditions2].index
        selected_dates = selected_dates.values
        if selected_dates[0] == last_trading_day:
            print(code)
            print("符合条件的日期：", selected_dates[0])

def stock_market(code):
    if '.' in code:
        arr = code.split('.')
        code = arr[-1]
    if code.startswith('688'):
        return "科创板"
    elif code.startswith('300'):
        return "创业板"
    elif code.startswith("8"):
        return "北交所"
    elif code.startswith("60"):
        return "上证"
    elif code.startswith("00"):
        return "深证"
    elif code.startswith("30"):
        return "深证"
    elif code.startswith("000"):
        return "上证指数"
    elif code.startswith("399"):
        return "深证指数"
    else:
        return "其他"

# 查询股票基本信息
def is_stock_and_oneYear(code):
    if not stock_market(code) in ["创业板", "上证", "深证"]:
        return

    rs = bs.query_stock_basic(code=code)
    result = querydata_to_list(rs)
    if result.empty:
        return False #"未知"
    elif result['type'][0] == '1':
        # 股票名称
        stock_name = result['code_name'][0]
        if "ST" in stock_name or "*ST" in stock_name or "S" in stock_name:
            return False

        # 提取上市日期
        ipo_date = result['ipoDate'][0]
        ipo_date = datetime.strptime(ipo_date, '%Y-%m-%d')
    
        # 计算与当前日期的差值
        current_date = datetime.now()
        time_diff = current_date - ipo_date
    
        # 判断是否超过1年
        if time_diff.days > 365:
            print(result)
            return True
        else:
            return False
        #return "股票"
    elif result['type'][0] == '2':
        return False #"指数"
    else:
        return False #"其他"

def get_latest_trade_date():
    global TRADING_DATE
    if len(TRADING_DATE) > 0:
        return TRADING_DATE

    # 获取当前日期
    current_date = datetime.now()
    # 计算30天之前的日期
    date_30_days_ago = current_date - timedelta(days=30)

    # 获取当前日期
    current_date_str = current_date.strftime('%Y-%m-%d')
    date_30_days_ago_str = date_30_days_ago.strftime('%Y-%m-%d')
    # 查询交易日历
    rs = bs.query_trade_dates(start_date=date_30_days_ago_str, end_date=current_date_str) 
    print('query_trade_dates respond error_code:' + rs.error_code)
    print('query_trade_dates respond  error_msg:' + rs.error_msg)
    result = querydata_to_list(rs)

    # 筛选出交易日
    trading_days = result[result["is_trading_day"] == '1']['calendar_date']
    # 获取最后一个交易日
    last_trading_day = trading_days.iloc[-1]
    print(f"距今最后一个交易日是：{last_trading_day}")
    TRADING_DATE = last_trading_day
    return last_trading_day

def get_all_stock():
    stock_cache_path = parentdir+'/Script/all_stock.json'
    if os.path.exists(stock_cache_path):
        return read_json(stock_cache_path)

    # 获取最后一个交易日
    last_trading_day = get_latest_trade_date()
    # 获取所有股票的基本信息
    rs = bs.query_all_stock(day=last_trading_day)
    result = querydata_to_list(rs)
    # 筛选出所有code
    all_codes = result[result['tradeStatus'] == '1']['code']
    # 筛选出所有股票code
    stock_codes = []
    for code in all_codes:
        if is_stock_and_oneYear(code):
            stock_codes.append(code)
    # 保存到缓存文件中 
    write_json(stock_codes, stock_cache_path)

if __name__ == "__main__":
    # 登录baostock
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)

    all_codes = get_all_stock()
    for stock_code in all_codes:
        can_stock_chaodi(stock_code)

    # 登出系统
    bs.logout()
