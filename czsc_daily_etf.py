# coding: utf-8
import os
import sys
import json
import shutil
import baostock as bs
import akshare as ak
from czsc_daily_util import *
from czsc.analyze import *
import sqlite3

START_TRADE_DATE = "2020-01-01"

def output_chart(symbol, df, cachedir):
    if is_rz_rq_symobl(symbol):
        cachedir = cachedir+"/rzrq"
        if not os.path.isdir(cachedir):
            os.makedirs(cachedir)

    bars = get_stock_bars(symbol=symbol,df=df)
    c = CZSC(bars, get_signals=None)
    kline = [x.__dict__ for x in c.bars_raw]
    bi = [{'dt': x.fx_a.dt, "bi": x.fx_a.fx} for x in c.bi_list] + \
         [{'dt': c.bi_list[-1].fx_b.dt, "bi": c.bi_list[-1].fx_b.fx}]

    chart = kline_pro(kline, bi=bi, title="{} - {}".format(c.symbol, c.freq))
    file_html = "{}.html".format(symbol)
    chart.render(os.path.join(cachedir, file_html))

def mline_chart_dir():
    return get_data_dir()+"/html/月线反转"

def clear_cache(cachedir):
    if os.path.isdir(cachedir):
        shutil.rmtree(cachedir)
    os.makedirs(cachedir)

def save_symbols(data, filename):
    data_dir = get_data_dir()
    write_json(data, os.path.join(data_dir, filename))

def read_symbols(filename):
    data_dir = get_data_dir()
    data = read_json(os.path.join(data_dir, filename))
    if data:
        return data
    return []

def sql_conn():
    conn = sqlite3.connect('sqlite3.db')
    cursor = conn.cursor()

    # 创建一个表
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ETF (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        symbol_name TEXT NOT NULL,
        fund_share FLOAT
    )
    ''')
    print("表创建成功！")


def main():
    sql_conn()
    # 获取 ETF 实时行情数据
 #    "fund_etf_category_sina"  # 基金实时行情-新浪
 # "fund_etf_hist_sina"  # 基金行情-新浪
 # "fund_etf_dividend_sina"  # 新浪财经-基金-ETF 基金-累计分红
 # "fund_etf_hist_em"  # 基金历史行情-东财
 # "fund_etf_hist_min_em"  # 基金分时行情-东财
 # "fund_etf_spot_em"  # 基金实时行情-东财
 # "fund_etf_spot_ths"  # 基金实时行情-同花顺
    # fund_name_em = ak.fund_scale_open_sina()
    # print(fund_name_em)
    # fund_etf_fund_daily_em = ak.fund_etf_fund_daily_em()
    # fund_etf_hist_em_df = ak.fund_etf_hist_em(symbol="159915", period="daily", start_date="20240101", end_date="20240801", adjust="")

    # print(fund_etf_hist_em_df)

    # lg = bs.login()
    # # 登录baostock
    # czsc_logger().info('login respond error_code:' + lg.error_code)
    # czsc_logger().info('login respond  error_msg:' + lg.error_msg)
    
    # # 获取行业分类数据
    # rs = bs.query_all_stock(day="2024-12-30")
    # print('query_stock_industry respond error_code:' + rs.error_code)
    # print('query_stock_industry respond error_msg:' + rs.error_msg)

    # # 将数据转换为 DataFrame
    # data_list = []
    # while (rs.error_code == '0') & rs.next():
    #     # 获取一条记录，将记录合并在一起
    #     data_list.append(rs.get_row_data())
    # result = pd.DataFrame(data_list, columns=rs.fields)

    # # code_name = []
    # # for x in range(0,len(result)):
    # #     code_name.append(result['code_name'].iloc(x))

    # # 输出结果
    # print(','.join(result['code_name']))

    
    # # 登出系统
    # bs.logout()

"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()
    # test_case()