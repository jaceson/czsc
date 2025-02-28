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

def minion_chart_dir():
    return get_data_dir()+"/html/小黄人三线红"

def golden_chart_dir():
    return get_data_dir()+"/html/黄金分割线抄底"

def chaodi_chart_dir():
    return get_data_dir()+"/html/KD线抄底"

def strong_chart_dir():
    return get_data_dir()+"/html/强势上涨"

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

def read_symbols(filename):
    data_dir = get_data_dir()
    data = read_json(os.path.join(data_dir, filename))
    if data:
        return data
    return []

def rz_rq_symbols(symbols):
    arr = []
    for symbol in symbols:
        if is_rz_rq_symobl(symbol):
            arr.append(symbol)
    return arr

def print_console(mline_symbols,minion_symbols,golden_symbols,chaodi_symbols,strong_symbols,one_buypoint_symbols,third_buypoint_symbols):
    # 打印股票池数据
    czsc_logger().info("月线反转股票列表：")
    czsc_logger().info('     '+', '.join(mline_symbols))

    czsc_logger().info("小黄人三线红股票列表：")
    czsc_logger().info('     '+', '.join(minion_symbols))

    czsc_logger().info("黄金分割线抄底列表：")
    czsc_logger().info('     '+', '.join(golden_symbols))

    czsc_logger().info("KD线抄底列表：")
    czsc_logger().info('     '+', '.join(chaodi_symbols))

    czsc_logger().info("强势上涨列表：")
    czsc_logger().info('     '+', '.join(strong_symbols))

    czsc_logger().info("中枢一买点位置：")
    czsc_logger().info('     '+', '.join(one_buypoint_symbols))

    czsc_logger().info("中枢三买点位置：")
    czsc_logger().info('     '+', '.join(third_buypoint_symbols))

    # 满足两个条件
    if True:
        czsc_logger().info("满足月线反转、小黄人三线红的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([mline_symbols,minion_symbols])))

        czsc_logger().info("满足月线反转、中枢一买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([mline_symbols,one_buypoint_symbols])))

        czsc_logger().info("满足月线反转、中枢三买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([mline_symbols,third_buypoint_symbols])))

        czsc_logger().info("满足小黄人三线红、黄金分割线的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,golden_symbols])))

        czsc_logger().info("满足小黄人三线红、KD线抄底的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,chaodi_symbols])))

        czsc_logger().info("满足小黄人三线红、中枢三买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,third_buypoint_symbols])))

        czsc_logger().info("满足小黄人三线红、强势上涨的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,strong_symbols])))

        czsc_logger().info("满足中枢三买、强势上涨的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([third_buypoint_symbols,strong_symbols])))

    # 中枢三买
    if True:
        czsc_logger().info("满足小黄人三线红、强势上涨、中枢三买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,strong_symbols,third_buypoint_symbols])))

        czsc_logger().info("满足小黄人三线红、黄金分割线、中枢三买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,golden_symbols,third_buypoint_symbols])))

        czsc_logger().info("满足小黄人三线红、KD线抄底、中枢三买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,chaodi_symbols,third_buypoint_symbols])))

    # 中枢一买
    if True:
        czsc_logger().info("满足小黄人三线红、黄金分割线、中枢一买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,golden_symbols,one_buypoint_symbols])))

        czsc_logger().info("满足小黄人三线红、KD线抄底、中枢一买的股票列表：")
        czsc_logger().info('     '+', '.join(intersection_list([minion_symbols,chaodi_symbols,one_buypoint_symbols])))

def test_case():
    option = 1
    if option == 1:
        # arr = ["600060","600081","600126","600398","600422","600588","600595","600633","600699","600812","600845","600988","601100","601231","603108","603171","603197","603300","603305","603758","603786","603915","605020","000032","000042","000818","000837","001282","002044","002153","002212","002250","002284","002664","002841","002913","002929","002965","300133","300226","300244","300251","300253","300258","300451","300454","300496","300676"]
        arr = ["600120","600126","600255","600363","600580","600602","600633","600797","600986","601689","603005","603039","603119","603236","603296","603319","603583","603636","603662","603667","603728","603803","603881","603893","000034","000681","000785","000977","002031","002036","002112","002117","002123","002131","002195","002261","002354","002369","002379","002530","002630","002681","002765","002851","002881","003021","300007","300017"]
        czsc_logger().info(len(arr))
        arr2 = read_json(os.path.join(get_data_dir(),"小黄人三线红.json"))
        czsc_logger().info(len(arr2))
        arr3 = []
        for symbol in arr2:
            arr3.append(symbol.split(".")[1])

        arr4 = []
        for symbol in arr3:
            if symbol not in arr:
                arr4.append(symbol)
        czsc_logger().info(arr4)
        czsc_logger().info(intersection_list([arr3,arr]))
    elif option == 2:
        lg = bs.login()
        # 登录baostock
        czsc_logger().info('login respond error_code:' + lg.error_code)
        czsc_logger().info('login respond  error_msg:' + lg.error_msg)
    
        symbol = "sh.000001"
        df = get_stcok_pd(symbol, "2006-01-01", "2006-12-31", 'd')
        output_chart(symbol,df,get_data_dir())
        # 登出系统
        bs.logout()

    sys.exit(0)

def main():
    lg = bs.login()
    # 登录baostock
    czsc_logger().info('login respond error_code:' + lg.error_code)
    czsc_logger().info('login respond  error_msg:' + lg.error_msg)
    
    # 所有股票
    all_symbols  = get_daily_symbols()
    # 股票池
    mline_symbols = []
    minion_symbols = []
    golden_symbols = []
    chaodi_symbols = []
    strong_symbols = []
    one_buypoint_symbols = []
    third_buypoint_symbols = []
    # 最后一天交易日
    last_trade_date = get_latest_trade_date()
    df = get_stcok_pd("sh.000001", START_TRADE_DATE, last_trade_date, 'd')
    is_stock_updated = (df['date'].iloc[-1] == last_trade_date)
    if !is_stock_updated:
        czsc_logger().info("{}日 BaoStock 交易数据还未更新!!!".format(last_trade_date))
        mline_symbols = read_symbols("月线反转.json")
        minion_symbols = read_symbols("小黄人三线红.json")
        golden_symbols = read_symbols("黄金分割线抄底.json")
        chaodi_symbols = read_symbols("KD线抄底.json")
        strong_symbols = read_symbols("强势上涨.json")
        one_buypoint_symbols = read_symbols("中枢一买点.json")
        third_buypoint_symbols = read_symbols("中枢三买点.json")
    else:
        # 清除缓存图标
        clear_cache(mline_chart_dir())
        clear_cache(minion_chart_dir())
        clear_cache(golden_chart_dir())
        clear_cache(chaodi_chart_dir())
        clear_cache(strong_chart_dir())
        clear_cache(buypoint_chart_dir(1))
        clear_cache(buypoint_chart_dir(3))
        # 选择月线反转股票
        for symbol in all_symbols:
            # 股票数据
            df = get_stcok_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')
            while len(df) <= 0:
                lg = bs.login()
                # 登录baostock
                czsc_logger().info('login respond error_code:' + lg.error_code)
                czsc_logger().info('login respond  error_msg:' + lg.error_msg)
                # 重新获取
                df = get_stcok_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')
            # 当前股票最后一个交易日
            symbol_last_trade_date = df['date'].iloc[-1]
            # 获取满足月线反转日期
            mline_dates = get_mline_turn(df)
            if symbol_last_trade_date in mline_dates:
                czsc_logger().info(symbol+"出现月线反转")
                mline_symbols.append(symbol)
                output_chart(symbol, df, mline_chart_dir())

            # 小黄人三线红
            minion_dates = get_minion_trend(df)
            if symbol_last_trade_date in minion_dates:
                czsc_logger().info(symbol+"出现小黄人三线红")
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

            # 最近5天涨停且，今日未涨停，今日下探到5日线附近的强势上涨股票
            if has_symbol_up_limit(df,N=5) and not has_symbol_up_limit(df,N=1):
                if has_cross_ma(df) or has_close_ma(df):
                    strong_symbols.append(symbol)
                    output_chart(symbol, df, strong_chart_dir())

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
        save_symbols(minion_symbols,"小黄人三线红.json")
        save_symbols(golden_symbols,"黄金分割线抄底.json")
        save_symbols(chaodi_symbols,"KD线抄底.json")
        save_symbols(strong_symbols,"强势上涨.json")
        save_symbols(one_buypoint_symbols,"中枢一买点.json")
        save_symbols(third_buypoint_symbols,"中枢三买点.json")
    
    #打印筛选结果
    print_console(mline_symbols,minion_symbols,golden_symbols,chaodi_symbols,strong_symbols,one_buypoint_symbols,third_buypoint_symbols)

    #打印可融资融券筛选结果
    czsc_logger().info("\n\n")
    czsc_logger().info("========================以下是可融资融券的结果========================")
    czsc_logger().info("\n\n")
    print_console(rz_rq_symbols(mline_symbols),rz_rq_symbols(minion_symbols),rz_rq_symbols(golden_symbols),rz_rq_symbols(chaodi_symbols),rz_rq_symbols(strong_symbols),rz_rq_symbols(one_buypoint_symbols),rz_rq_symbols(third_buypoint_symbols))

    # 登出系统
    bs.logout()

    # 结束日志
    if is_stock_updated:
        czsc_logger().info('Stock Finished!')

"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
    python czsc_daily_stock.py | tee -a ./data/log.json
"""
if __name__ == '__main__':
    main()
    # test_case()