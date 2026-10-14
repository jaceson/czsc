# coding: utf-8
import os
import sys
import sqlite3
import time
import argparse
import baostock as bs
from czsc_daily_util import *
from dateutil.relativedelta import relativedelta
from datetime import datetime

sql_connect = None
sql_connect_cursor = None
all_rows_data = []

def sqlite3_connect():
    global sql_connect,sql_connect_cursor
    if sql_connect:
        return
    current_dir = os.path.dirname(os.path.abspath(__file__))
    sql_connect = sqlite3.connect(current_dir+'/data/sqlite3.db', timeout=30)
    sql_connect_cursor = sql_connect.cursor()
    # These settings reduce fsync overhead for the bulk upsert below. Do not
    # switch journal mode here: that needs an exclusive lock and can block
    # another process reading the same large database.
    sql_connect_cursor.execute("PRAGMA busy_timeout=30000")
    sql_connect_cursor.execute("PRAGMA synchronous=NORMAL")
    sql_connect_cursor.execute("PRAGMA temp_store=MEMORY")
    schema_changed = False

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
        schema_changed = True

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
        schema_changed = True

    # Older databases may have been created without this constraint.  It is
    # required for the upsert below to be idempotent and avoids duplicate rows
    # on every refresh.
    sql_connect_cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='idx_stock_daily_code_freq_date'"
    )
    if sql_connect_cursor.fetchone() is None:
        sql_connect_cursor.execute(
            "CREATE UNIQUE INDEX idx_stock_daily_code_freq_date "
            "ON STOCK_DAILY(code, frequency, date)"
        )
        schema_changed = True
    if schema_changed:
        sql_connect.commit()
    

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

# 获取本地股票数据；时间范围2001-01-02~2024-12-31
def get_local_stock_data(symbol,start_date='2001-01-01',end_date=None, frequency='d'):
    # 连接数据库
    sqlite3_connect()
    # stock data
    if end_date is not None:
        sql_connect_cursor.execute(
            "SELECT DISTINCT date,open,high,low,close,volume,amount,turn FROM STOCK_DAILY WHERE code = ? AND frequency = ? AND date >= ? AND date <= ? ORDER BY date ASC",
            (symbol, frequency, start_date, end_date)
        )
    else:
        sql_connect_cursor.execute(
            "SELECT DISTINCT date,open,high,low,close,volume,amount,turn FROM STOCK_DAILY WHERE code = ? AND frequency = ? AND date >= ? ORDER BY date ASC",
            (symbol, frequency, start_date)
        )
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

def fetch_all_symbols_kline(
    frequency='d',
    start_date=None,
    end_date=None,
    full_sync=False,
    commit_every=20,
):
    """同步所有股票 K 线。

    默认按每只股票本地已有的最大交易日增量下载。相比原实现，这会避开
    多年历史数据的重复网络传输；返回的数据使用 ``executemany`` 批量写入，
    并按股票批量提交事务。

    :param frequency: BaoStock 周期，默认日线 ``d``。
    :param start_date: 强制同步起始日期；未指定时使用本地最大日期。
    :param end_date: 结束日期；未指定时使用今天。
    :param full_sync: 是否忽略本地数据，从 ``start_date`` 或 2000-01-01 全量同步。
    :param commit_every: 每同步多少只股票提交一次事务。
    :return: 成功写入的行数。
    """
    sqlite3_connect()
    frequency = frequency.lower()
    if frequency != 'd':
        raise ValueError("当前 STOCK_DAILY 表仅支持日线字段，请使用 frequency='d'")
    if commit_every <= 0:
        raise ValueError("commit_every 必须大于 0")

    initial_start = start_date or '2000-01-01'
    end_date = end_date or datetime.now().strftime('%Y-%m-%d')
    all_symbols = list(get_daily_symbols())
    if not all_symbols:
        return 0

    # 一次查询拿到所有股票的本地最新日期，避免循环中逐只查询 SQLite。
    latest_by_symbol = {}
    if not full_sync and start_date is None:
        sql_connect_cursor.execute(
            "SELECT code, MAX(date) FROM STOCK_DAILY WHERE frequency=? GROUP BY code",
            (frequency,),
        )
        latest_by_symbol = dict(sql_connect_cursor.fetchall())

    fields = "date,open,high,low,close,volume,amount,turn"
    insert_sql = (
        "INSERT INTO STOCK_DAILY "
        "(date, code, open, close, high, low, volume, amount, turn, frequency) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(code, frequency, date) DO UPDATE SET "
        "open=excluded.open, close=excluded.close, high=excluded.high, "
        "low=excluded.low, volume=excluded.volume, amount=excluded.amount, "
        "turn=excluded.turn"
    )
    written = 0
    pending_symbols = 0
    started_at = time.time()
    login_result = bs.login()
    if getattr(login_result, 'error_code', '0') != '0':
        raise RuntimeError(
            "BaoStock 登录失败：{} {}".format(
                getattr(login_result, 'error_code', ''),
                getattr(login_result, 'error_msg', ''),
            )
        )
    try:
        for index, symbol in enumerate(all_symbols, 1):
            query_start = initial_start
            if not full_sync and start_date is None:
                # 从最后一天开始重新拉取，既能补当天数据，也能覆盖复权后修订。
                query_start = latest_by_symbol.get(symbol, initial_start)
            print("进度：{} / {} {}~{}".format(index, len(all_symbols), symbol, query_start))

            rs = bs.query_history_k_data_plus(
                code=symbol,
                fields=fields,
                start_date=query_start,
                end_date=end_date,
                frequency=frequency,
                adjustflag="2",
            )
            if rs.error_code != '0':
                print("BaoStock 查询失败：{} {} {}".format(symbol, rs.error_code, rs.error_msg))
                continue

            rows = []
            while rs.next():
                row_data = rs.get_row_data()
                if len(row_data) < 8 or not row_data[0]:
                    continue
                try:
                    values = [float(value) for value in row_data[1:8]]
                except (TypeError, ValueError):
                    continue
                # BaoStock can legitimately return a zero turnover for a
                # suspended/security edge case; the original importer only
                # required turnover to be numeric.  Keep that behavior while
                # rejecting invalid OHLCV/amount values.
                if any(value <= 0 for value in values[:6]) or values[6] < 0:
                    continue
                stock_open, stock_high, stock_low, stock_close = values[:4]
                stock_volume, stock_amount, stock_turn = values[4:]
                rows.append(
                    (row_data[0], symbol, stock_open, stock_close, stock_high,
                     stock_low, stock_volume, stock_amount, stock_turn, frequency)
                )

            if rows:
                sql_connect_cursor.executemany(insert_sql, rows)
                written += len(rows)
            pending_symbols += 1
            if pending_symbols >= commit_every:
                sql_connect.commit()
                pending_symbols = 0
        sql_connect.commit()
    except Exception:
        sql_connect.rollback()
        raise
    finally:
        try:
            bs.logout()
        except Exception:
            pass
    print("K线同步完成：{} 行，耗时 {:.1f} 秒".format(written, time.time() - started_at))
    return written

def main():
    global sql_connect,sql_connect_cursor
    parser = argparse.ArgumentParser(description='同步 BaoStock 日线到 SQLite')
    parser.add_argument('--full-sync', action='store_true', help='忽略本地最大日期，从 2000-01-01 全量同步')
    parser.add_argument('--start-date', default=None, help='强制同步起始日期，例如 2026-01-01')
    parser.add_argument('--end-date', default=None, help='同步结束日期，默认今天')
    parser.add_argument('--commit-every', type=int, default=20, help='每多少只股票提交一次事务')
    args = parser.parse_args()
    # 连接数据库；放在 argparse 后，--help 不会触碰数据库。
    sqlite3_connect()
    # fetch_all_symbols_kline(
    #     start_date=args.start_date,
    #     end_date=args.end_date,
    #     full_sync=args.full_sync,
    #     commit_every=args.commit_every,
    # )
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
