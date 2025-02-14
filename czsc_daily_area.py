# coding: utf-8
import os
import sys
import json
import shutil
import baostock as bs
from czsc_daily_util import *
from czsc.analyze import *

START_TRADE_DATE = "2020-01-01"

def output_chart(symbol, df, cachedir):
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

def minion_chart_dir():
    return get_data_dir()+"/html/小黄人三线红"

def golden_chart_dir():
    return get_data_dir()+"/html/黄金分割线抄底"

def buypoint_chart_dir(buypoint_type):
    if buypoint_type == 1:
        return get_data_dir()+"/html/中枢一买点"
    elif buypoint_type == 2:
        return get_data_dir()+"/html/中枢二买点"
    elif buypoint_type == 3:
        return get_data_dir()+"/html/中枢三买点"
    else:
        return get_data_dir()+"/html/中枢买点"

def clear_cache(cachedir):
    if os.path.isdir(cachedir):
        shutil.rmtree(cachedir)
    os.makedirs(cachedir)

def save_symbols(data, filename):
    data_dir = get_data_dir()
    write_json(data, os.path.join(data_dir, filename))

def test_case():
    lg = bs.login()
    # 登录baostock
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
    
    symbol = "sz.300124"
    df = get_stcok_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')
    res = is_buy_point(symbol,df)
    print(res)

    # 登出系统
    bs.logout()

    sys.exit(0)

def main():
    lg = bs.login()
    # 登录baostock
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
    
    # 所有股票
    all_symbols  = get_daily_symbols()
    # 最后一天交易日
    last_trade_date = get_latest_trade_date()
    df = get_stcok_pd("sh.000001", START_TRADE_DATE, last_trade_date, 'd')
    assert df['date'].iloc[-1] == last_trade_date,"BaoStock最后一个交易日数据还未更新"

    # 清除缓存图标
    clear_cache(mline_chart_dir())
    clear_cache(minion_chart_dir())
    clear_cache(golden_chart_dir())
    clear_cache(buypoint_chart_dir(1))
    clear_cache(buypoint_chart_dir(3))
    
    # 选择月线反转股票
    mline_symbols = []
    minion_symbols = []
    golden_symbols = []
    one_buypoint_symbols = []
    third_buypoint_symbols = []
    for symbol in all_symbols:
        # 股票数据
        df = get_stcok_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')
        # 当前股票最后一个交易日
        symbol_last_trade_date = df['date'].iloc[-1]
        # 获取满足月线反转日期
        mline_dates = get_mline_turn(df)
        if symbol_last_trade_date in mline_dates:
            print(symbol+"出现月线反转")
            mline_symbols.append(symbol)
            output_chart(symbol, df, mline_chart_dir())

        # 小黄人三线红
        minion_dates = get_minion_trend(df)
        if symbol_last_trade_date in minion_dates:
            print(symbol+"出现小黄人三线红")
            minion_symbols.append(symbol)
            output_chart(symbol, df, minion_chart_dir())

        # 黄金分割抄底位置
        if is_golden_point(symbol,df):
            golden_symbols.append(symbol)
            output_chart(symbol, df, golden_chart_dir())

        # 是否是买卖点
        buypoint_type = get_buy_point_type(symbol,df)
        if buypoint_type>0:
            output_chart(symbol, df, buypoint_chart_dir(buypoint_type))
            if buypoint_type == 1:
                one_buypoint_symbols.append(symbol)
            elif buypoint_type == 3:
                third_buypoint_symbols.append(symbol)

    # 保存缓存缓存数据
    save_symbols(mline_symbols,"月线反转.json")
    print("月线反转股票列表：")
    print('     '+', '.join(mline_symbols))

    save_symbols(minion_symbols,"小黄人三线红.json")
    print("小黄人三线红股票列表：")
    print('     '+', '.join(minion_symbols))

    save_symbols(golden_symbols,"黄金分割线抄底.json")
    print("黄金分割线抄底列表：")
    print('     '+', '.join(golden_symbols))

    save_symbols(one_buypoint_symbols,"中枢一买点.json")
    print("中枢一买点位置：")
    print('     '+', '.join(one_buypoint_symbols))

    save_symbols(third_buypoint_symbols,"中枢三买点.json")
    print("中枢三买点位置：")
    print('     '+', '.join(third_buypoint_symbols))

    print("三个条件都满足的股票列表：")
    print('     '+', '.join(intersection_list([mline_symbols,minion_symbols,golden_symbols])))
    print("三个条件满足其一的股票列表：")
    print('     '+', '.join(union_list([mline_symbols,minion_symbols,golden_symbols])))
    # 登出系统
    bs.logout()

if __name__ == '__main__':
    main()
    # test_case()