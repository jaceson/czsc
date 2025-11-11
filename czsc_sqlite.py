# coding: utf-8
import os
import sys
import sqlite3
import baostock as bs
from czsc_daily_util import *
from dateutil.relativedelta import relativedelta

sql_connect = None
sql_connect_cursor = None
all_rows_data = []

def sqlite3_connect():
    global sql_connect,sql_connect_cursor
    if sql_connect:
        return
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sql_connect = sqlite3.connect(current_dir+'/data/sqlite3.db')
    sql_connect_cursor = sql_connect.cursor()

    sql_connect_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ETF_DAILY'")
    table_exists = sql_connect_cursor.fetchone()

    if not table_exists:
        sql_connect_cursor.execute('''
        CREATE TABLE ETF_DAILY (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            share REAL
        )
        ''')
        print("表 ETF_DAILY 创建成功！")

    sql_connect_cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='STOCK_DAILY'")
    table_exists = sql_connect_cursor.fetchone()

    if not table_exists:
        sql_connect_cursor.execute('''
        CREATE TABLE STOCK_DAILY (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            code TEXT NOT NULL,
            open REAL,
            close REAL,
            high REAL,
            low REAL,
            volume REAL,
            amount REAL,
            turn REAL,
            frequency TEXT
        )
        ''')
        print("表 STOCK_DAILY 创建成功！")
    

def get_etf_share(dt=""):
    # 获取当前日期
    current_date = datetime.now()

    # 获取一年前的日期（考虑闰年）
    one_year_ago = current_date - relativedelta(years=1)

    # 将日期格式化为字符串
    one_year_ago_str = one_year_ago.strftime("%Y-%m-%d")

    # 连接数据库
    sqlite3_connect()
    # 查询已有数据，避免重复添加
    if len(dt)>0:
        sql_connect_cursor.execute("SELECT dt,code,name,share FROM ETF_DAILY WHERE dt > ? AND code in (SELECT DISTINCT code FROM ETF_DAILY WHERE dt < ?) order by dt asc",(dt,one_year_ago_str))
    else:
        sql_connect_cursor.execute("SELECT dt,code,name,share FROM ETF_DAILY WHERE code in (SELECT DISTINCT code FROM ETF_DAILY WHERE dt < ?) order by dt asc")
    
    res_list = {}
    rows = sql_connect_cursor.fetchall()
    for row in rows:
        code = row[1]
        if not code in res_list.keys():
            res_list[code] = {'name':row[2],'share':{'dt':[],'share':[]}}
        res_list[code]['share']['dt'].append(row[0])
        res_list[code]['share']['share'].append(row[3])
    return res_list

def get_etf_list():
    # 连接数据库
    sqlite3_connect()
    # etf code列表
    sql_connect_cursor.execute("SELECT code FROM ETF_DAILY GROUP BY code")
    res_list = []
    rows = sql_connect_cursor.fetchall()
    for row in rows:
        res_list.append(row[0])
    return res_list

def sync_db(file_path):
    global all_rows_data
    print(file_path)
    is_has_update = False
    data_arr = read_json(file_path)
    for item in data_arr:
        dt = item['dt']
        code = item['code']
        name = item['name']
        share = item['share']
        share = share.replace(',','')

        key = dt+code
        if key in all_rows_data:
            continue

        is_has_update = True
        sql_connect_cursor.execute("INSERT INTO ETF_DAILY (dt, name, code, share) VALUES (?, ?, ?, ?)", (dt, name, code, share))
        all_rows_data.append(key)

    # 提交事务
    if is_has_update:
        sql_connect.commit()

def get_local_stock_data(symbol,start_date='2001-01-01',frequency='d'):
    # 连接数据库
    sqlite3_connect()
    # stock data
    sql_connect_cursor.execute("SELECT DISTINCT date,open,high,low,close,volume,amount,turn FROM STOCK_DAILY WHERE code = ? AND frequency = ? AND date >= ? ORDER BY date ASC",(symbol,frequency,start_date))
    res_list = []
    rows = sql_connect_cursor.fetchall()
    # 转换成pandas
    df = pd.DataFrame(rows, columns=['date','open','high','low','close','volume','amount','turn'])
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['amount'] = df['amount'].astype(float)
    df['turn'] = df['turn'].astype(float)
    df['date'] = df['date'].astype(str)
    df['datetime'] = pd.to_datetime(df['date'])
    return df

"""
    本地股票数据转换为NewBar
"""
def get_local_stock_bars(symbol, start_date=None, frequency='d', df=None):
    if df is None:
        df = get_local_stock_data(symbol, start_date, frequency)
    if frequency.lower() == 'w':
        freq = Freq.W
    elif frequency.lower() == 'm':
        freq = Freq.M
    elif frequency.lower() == '5':
        freq = Freq.F5
    elif frequency.lower() == '15':
        freq = Freq.F15
    elif frequency.lower() == '30':
        freq = Freq.F30
    elif frequency.lower() == '60':
        freq = Freq.F60
    else:
        freq = Freq.D
    return [RawBar(symbol=symbol, id=i, freq=Freq.D, open=row['open'], dt=row['date'],
                    close=row['close'], high=row['high'], low=row['low'], vol=row['volume'], amount=row['amount'])
                for i, row in df.iterrows()]

def fetch_all_symbols_kline():
    lg = bs.login()
    frequency = '30'
    start_date = '2020-01-01'
    end_date = '2025-01-01'
    all_symbols = get_daily_symbols()
    for symbol in all_symbols:
        fields="date,open,high,low,close,volume,amount,time"
        if frequency == 'd':
            start_date = '2000-01-01'
            fields="date,open,high,low,close,volume,amount,turn",
        # if all_symbols.index(symbol) < 1140:
        #     continue
        print("进度：{} / {}".format(all_symbols.index(symbol),len(all_symbols)))
        rs = bs.query_history_k_data_plus(
            code=symbol,
            fields=fields,
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag="2",
        )
        while (rs.error_code == '0') & rs.next():
            row_data = rs.get_row_data()
            try:
                stock_date = row_data[0]
                stock_open = float(row_data[1])
                stock_high = float(row_data[2])
                stock_low = float(row_data[3])
                stock_close = float(row_data[4])
                stock_volume = float(row_data[5])
                stock_amount = float(row_data[6])
                if len(stock_date) <= 0 or stock_open<=0 or stock_close<=0 or stock_high<=0 or stock_low<=0 or stock_volume<=0 or stock_amount<=0:
                    continue
                if frequency == 'd':
                    stock_turn = float(row_data[7])
                    sql_connect_cursor.execute("INSERT INTO STOCK_DAILY (date, code, open, close, high, low, volume, amount, turn, frequency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (stock_date, symbol, stock_open, stock_close, stock_high, stock_low, stock_volume, stock_amount, stock_turn, frequency))
                else:
                    stock_time = row_data[7]
                    if len(stock_time)<0:
                        continue
                    sql_connect_cursor.execute("INSERT INTO STOCK_DAILY (date, code, open, close, high, low, volume, amount, time, frequency) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (stock_date, symbol, stock_open, stock_close, stock_high, stock_low, stock_volume, stock_amount, stock_time, frequency))    
            except Exception as e:
                print(e)
                continue
        # 提交数据
        sql_connect.commit()

    bs.logout()

def main():
    global sql_connect,sql_connect_cursor
    # 连接数据库
    sqlite3_connect()

    # fetch_all_symbols_kline()
    # return

    # 查询已有数据，避免重复添加
    sql_connect_cursor.execute("SELECT dt,code FROM ETF_DAILY")
    rows = sql_connect_cursor.fetchall()
    for row in rows:
        all_rows_data.append(row[0]+row[1])

    # 本地数据
    sh_file = get_data_dir()+'/etf/sh/sh_etf_stock.json'
    sh_dict = read_json(sh_file)
    if sh_dict is None:
        sh_dict = {}
    etf_dir = get_data_dir()+'/etf/'
    for root, dirs, files in os.walk(etf_dir):
        for file in files:
            if file in sh_dict.keys():
                continue
            file_path = os.path.join(root, file)
            if file_path.endswith('.json') and not file_path.endswith('eft.json'):
                try:
                    sync_db(file_path)
                except Exception as e:
                    write_json(sh_dict,sh_file)
                    print(e)
                    sys.exit(-1)
                if '/sh/' in file_path:
                    sh_dict[file] = True
    write_json(sh_dict,sh_file)

"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()