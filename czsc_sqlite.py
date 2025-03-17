# coding: utf-8
import os
import sys
import sqlite3
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
    sql_connect = sqlite3.connect(current_dir+'/sqlite3.db')
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
    else:
        print("表 ETF_DAILY 已存在。")

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

def main():
    global sql_connect,sql_connect_cursor
    # 连接数据库
    sqlite3_connect()

    # 查询已有数据，避免重复添加
    sql_connect_cursor.execute("SELECT dt,code FROM ETF_DAILY")
    rows = sql_connect_cursor.fetchall()
    for row in rows:
        all_rows_data.append(row[0]+row[1])

    # 本地数据
    etf_dir = get_data_dir()+'/etf/'
    for root, dirs, files in os.walk(etf_dir):
        for file in files:
            file_path = os.path.join(root, file)
            if file_path.endswith('.json') and not file_path.endswith('eft.json'):
                sync_db(file_path)

"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()