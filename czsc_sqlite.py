# coding: utf-8
import os
import sys
import sqlite3
from czsc_daily_util import *

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


def sync_db(file_path):
    global all_rows_data
    data_arr = read_json(file_path)
    for item in data_arr:
        dt = item['dt']
        code = item['code']
        name = item['name']
        share = item['share']

        key = dt+code
        if key in all_rows_data:
            continue

        sql_connect_cursor.execute("INSERT INTO ETF_DAILY (dt, name, code, share) VALUES (?, ?, ?, ?)", (dt, name, code, share))
        all_rows_data.append(key)

    # 提交事务
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
    etf_dir = get_data_dir()+'/etf'
    for root, dirs, files in os.walk(etf_dir):
        for file in files:
            file_path = os.path.join(root, file)
            sync_db(file_path)

"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()