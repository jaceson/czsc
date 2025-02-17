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

def chaodi_chart_dir():
    return get_data_dir()+"/html/KD线抄底"

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
    # arr = ["600060","600081","600126","600398","600422","600588","600595","600633","600699","600812","600845","600988","601100","601231","603108","603171","603197","603300","603305","603758","603786","603915","605020","000032","000042","000818","000837","001282","002044","002153","002212","002250","002284","002664","002841","002913","002929","002965","300133","300226","300244","300251","300253","300258","300451","300454","300496","300676"]
    arr = ["600120","600126","600255","600363","600580","600602","600633","600797","600986","601689","603005","603039","603119","603236","603296","603319","603583","603636","603662","603667","603728","603803","603881","603893","000034","000681","000785","000977","002031","002036","002112","002117","002123","002131","002195","002261","002354","002369","002379","002530","002630","002681","002765","002851","002881","003021","300007","300017"]
    print(len(arr))
    arr2 = read_json(os.path.join(get_data_dir(),"小黄人三线红.json"))
    print(len(arr2))
    arr3 = []
    for symbol in arr2:
        arr3.append(symbol.split(".")[1])

    arr4 = []
    for symbol in arr3:
        if symbol not in arr:
            arr4.append(symbol)
    print(arr4)
    print(intersection_list([arr3,arr]))
    return
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
    if df['date'].iloc[-1] != last_trade_date:
        print("{}日 BaoStock 交易数据还未更新!!!".format(last_trade_date))
        sys.exit(0)

    # 清除缓存图标
    clear_cache(mline_chart_dir())
    clear_cache(minion_chart_dir())
    clear_cache(golden_chart_dir())
    clear_cache(chaodi_chart_dir())
    clear_cache(buypoint_chart_dir(1))
    clear_cache(buypoint_chart_dir(3))
    
    # 选择月线反转股票
    mline_symbols = []
    minion_symbols = []
    golden_symbols = []
    chaodi_symbols = []
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

        # # 小黄人三线红
        minion_dates = get_minion_trend(df)
        if symbol_last_trade_date in minion_dates:
            print(symbol+"出现小黄人三线红")
            minion_symbols.append(symbol)
            output_chart(symbol, df, minion_chart_dir())

        # kd线抄底位置
        if is_kd_buy_point(symbol,df):
            chaodi_symbols.append(symbol)
            output_chart(symbol, df, chaodi_chart_dir())

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

    save_symbols(chaodi_symbols,"KD线抄底.json")
    print("KD线抄底列表：")
    print('     '+', '.join(chaodi_symbols))

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