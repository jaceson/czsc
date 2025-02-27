# coding: utf-8
import os
import sys
import json
import math
import logging
import time
import requests
import baostock as bs
from lib.MyTT import *
from datetime import datetime, timedelta
from czsc.utils.sig import get_zs_seq
from czsc.analyze import *
from czsc.enum import *
from collections import *

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 设置日志级别为 DEBUG

# 日志格式
log_format = "%(asctime)s - %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"  # 自定义日期格式，去掉微秒部分

# 创建 Formatter 并设置日期格式
formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

# 创建文件处理器，将日志写入文件
file_handler = logging.FileHandler("./data/log.json", mode="a")  # 追加模式
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# 创建控制台处理器，将日志输出到控制台
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# 将处理器添加到日志器
logger.addHandler(file_handler)
logger.addHandler(console_handler)
def czsc_logger():
    return logger

"""
    月线反转
"""
def get_mline_turn(df):
    ndf = get_rps_data(df)
    pos = (
        (ndf['RPS50']>85) &
        (ndf['close']>MA(ndf['close'],250)) &
        (COUNT(IF(ndf['high']>=HHV(ndf['high'],50),1,0), 30)>0) &
        (COUNT(IF(ndf['close']>MA(ndf['close'],250),1,0), 30)>2) &
        (COUNT(IF(ndf['close']>MA(ndf['close'],250),1,0), 30)<30) &
        (ndf['high']/HHV(ndf['high'],120)>0.9)
    )
    if not ndf[pos].empty:
        selected_indexs = ndf[pos].index
        selected_dates = []
        for idx in selected_indexs:
            selected_dates.append(ndf['date'][idx])
        return selected_dates
    return []

"""
    小黄人三线红【上涨趋势】
    满足条件：
        RPS50 > 90 
        RPS120 > 90
        RPS250 > 90
"""
def get_minion_trend(df):
    ndf = get_rps_data(df)
    pos = (
        (ndf['RPS50'] > 90) &
        (ndf['RPS120'] > 90) &
        (ndf['RPS250'] > 90)
    )
    if not ndf[pos].empty:
        selected_indexs = ndf[pos].index
        selected_dates = []
        for idx in selected_indexs:
            selected_dates.append(ndf['date'][idx])
        return selected_dates
    return []

"""
    是否到达下跌黄金分割线抄底点
"""
def is_golden_point(symbol,df,threshold=1.7,klines=10,max_ratio=1.1):
    # 股票czsc结构
    bars = get_stock_bars(symbol=symbol,df=df)
    c = CZSC(bars, get_signals=None)
    bi_list = c.bi_list
    if len(bi_list) <= 0:
        return False
    if len(bi_list) > 1:
        last_bi = bi_list[-1]
        # 当前一笔从最低点到最高点，涨幅已经超过50%
        if last_bi.fx_a.fx*threshold < last_bi.fx_b.fx:
            # 当前收盘价格
            stock_open = df['open'].iloc[-1]
            stock_close = df['close'].iloc[-1]
            stock_high = df['high'].iloc[-1]
            stock_low = df['low'].iloc[-1]
            min_price = np.min(np.array([stock_open, stock_close, stock_high, stock_low]))
            # 是否在抄底区间内
            sqr_val = sqrt_val(last_bi.fx_a.fx, last_bi.fx_b.fx)
            gold_low_val = gold_val_low(last_bi.fx_a.fx, last_bi.fx_b.fx)
            max_val = max(sqr_val,gold_low_val)
            # 距离黄金分割点还差5%以下
            if max_val*max_ratio<min_price:
                czsc_logger().info("【"+symbol+"]"+"距离黄金点较远, 黄金点位："+str(max_val)+", 当前价位："+str(min_price))
                return False
            # 上一波涨幅必须超过10个交易
            kline_num = days_trade_delta(df,last_bi.sdt.strftime("%Y-%m-%d"),last_bi.edt.strftime("%Y-%m-%d"))
            if kline_num<klines:
                czsc_logger().info("【"+symbol+"】"+" kline number is "+str(kline_num))
                return False
            # 今天收盘价是这波调整依赖最低收盘价
            min_close = get_min_close(df, last_bi.edt.strftime("%Y-%m-%d"))
            czsc_logger().info("【"+symbol+"】"+" current close is "+str(stock_close)+","+last_bi.edt.strftime("%Y-%m-%d")+" min close is "+str(min_close))
            if stock_close <= min_close:
                czsc_logger().info("【"+symbol+"】"+"股票当前价："+str(stock_close)+"，最低价："+str(last_bi.fx_a.fx)+"，最高价："+str(last_bi.fx_b.fx))
                czsc_logger().info("     1）平   方  根："+str(round(sqr_val,2)))
                czsc_logger().info("     2）黄金分割低点："+str(round(gold_low_val,2)))
                if stock_close<max_val:
                    czsc_logger().info("     3）可以考虑直接买入！！！")
                else:
                    czsc_logger().info("     3）最少还需跌："+str(round(100*(stock_close-max_val)/stock_close,2))+"%")
                czsc_logger().info("     4）笔的角度："+str(round(bi_angle(last_bi),2)))
                czsc_logger().info("     5）总的涨幅："+str(round(bi_ratio(last_bi)*100,2))+"%")
                czsc_logger().info("     6）笔的K线数量："+str(last_bi.length))
                czsc_logger().info("     7）平均每天涨幅："+str(round(100*bi_day_ratio(last_bi),2))+"%")
                return True
            else:
                czsc_logger().info("【"+symbol+"】"+" 当前收盘价："+str(stock_close)+", 最小收盘价："+str(min_close))
    return False

"""
    自定义比的角度
    每天涨10%默认角度为45
"""
def bi_angle(bi):
    max_ratio = 10*(bi.fx_b.fx-bi.fx_a.fx)/bi.fx_a.fx
    days_num = bi.length
    return 45*max_ratio/days_num

"""
    笔的涨幅
"""
def bi_ratio(bi):
    return (bi.fx_b.fx-bi.fx_a.fx)/bi.fx_a.fx

"""
    笔平均每天的涨幅
"""
def bi_day_ratio(bi):
    max_ratio = (bi.fx_b.fx-bi.fx_a.fx)/bi.fx_a.fx
    days_num = bi.length
    return max_ratio/days_num

"""
    根据KD线确认抄底点
"""
def is_kd_buy_point(symbol,df):
    ndf = get_kd_data(df)
    buy_con = (
        (df['K0'] < 30) &
        ((df['K0']-REF(df['K0'],1))/REF(df['K0'],1) >= -0.03) & 
        (REF(df['K0'],1)<REF(df['K0'],2)) & 
        (REF(df['K0'],2)<REF(df['K0'],3)) & 
        (REF(df['K0'],3)<REF(df['K0'],4)) & 
        (REF(df['K0'],4)<REF(df['K0'],5)) & 
        (REF(df['K0'],5)<REF(df['K0'],6)) & 
        (REF(df['K0'],6)<REF(df['K0'],7)) & 
        (REF(df['K0'],7)<REF(df['K0'],8)) &
        (df['low'] <= REF(df['low'], 1)) &
        (df['high'] <= REF(df['high'], 1)) &
        (REF(df['low'], 1) <= REF(df['low'], 2)) &
        (REF(df['high'], 1) <= REF(df['high'], 2)) 
    )

    if not df[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        selected_dates = []
        for idx in selected_indexs:
            selected_dates.append(ndf['date'][idx])
        stock_k0 = df['K0'].iloc[-1]

        last_trading_day = df['date'].iloc[-1]
        if last_trading_day in selected_dates:
            stock_k1 = df['K0'].iloc[-2]
            czsc_logger().info("【"+symbol+"】"+" 当前K0："+str(stock_k0)+", 当前D0："+str(stock_k1))
            czsc_logger().info("策略结算结果：当前KD0="+str(stock_k0-stock_k1)+", 当前KR0="+str((stock_k0-stock_k1)/stock_k1))
            return True
        else:
            last_selected_date = selected_dates[-1]
            days_delta = days_trade_delta(df, last_selected_date, last_trading_day)
            if days_delta<5:
                czsc_logger().info(symbol+","+last_selected_date)
            is_valid = True
            for delta in range(1,days_delta):
                if stock_k0>df['K0'].iloc[-(delta+1)]:
                    is_valid = False
                    break
                stock_k0 = df['K0'].iloc[-(delta+1)]
            if not is_valid:
                is_valid = True
                stock_low = df['low'].iloc[-1]
                stock_high = df['high'].iloc[-1]
                for delta in range(1,days_delta):
                    if stock_low>df['low'].iloc[-(delta+1)] and stock_high>df['high'].iloc[-(delta+1)]:
                        is_valid = False
                        break
                    stock_low = df['low'].iloc[-(delta+1)]
                    stock_high = df['high'].iloc[-(delta+1)]
            return is_valid
    return False

"""
    N日前是否有涨停；
    N表示第几日前；0表示最后一个交易是否涨停
"""
def is_symbol_up_limit(df,N=0):
    today_close = df['close'].iloc[-1-N]
    lastday_close = df['close'].iloc[-1-N-1]
    return today_close>lastday_close*1.09

"""
    N日内是否有涨停
    N表示前几日，1表示今日，2表示昨天到今天
"""
def has_symbol_up_limit(df,N=5):
    for idx in range(0,N):
        if is_symbol_up_limit(df,idx):
            return True
    return False

"""
    今日股价是否上穿N日线
    N表示几日线，5表示5日线，10表示10日线
"""
def has_cross_ma(df,N=5):
    ma = MA(df['close'],N)
    if df['low'].iloc[-1]<=ma[-1] and df['high'].iloc[-1]>=ma[-1]:
        return True
    return False

"""
    今日收盘价是否接近N日线
    N表示几日线，5表示5日线
"""
def has_close_ma(df,N=5,diff=0.02):
    ma = MA(df['close'],N)
    if df['close'].iloc[-1]<ma[-1]*(1+diff):
        return True
    return False

"""
    是否是买点，即中枢离开段回撤到中枢附近
    返回买点类型：
        0，表示不是买点
        1，表示一买点
        2，表示二买点
        3，表示三买点
"""
def get_buy_point_type(symbol,df):
    # 股票czsc结构
    bars = get_stock_bars(symbol=symbol,df=df)
    c = CZSC(bars, get_signals=None)
    bi_list = c.bi_list
    if len(bi_list) <= 0:
        return 0
    last_zs = None
    prev_zs = None
    last_bi = bi_list[-1]
    zs_list = get_zs_seq(bi_list)
    for zs in reversed(zs_list):
        # 最后一个中枢
        if zs.is_valid:
            if last_zs is None:
                last_zs = zs
            else:
                prev_zs = zs
                break
    if last_zs is None or prev_zs is None:
        czsc_logger().info("【"+symbol+"】"+"最后一个中枢区间："+zs.sdt.strftime("%Y-%m-%d")+"到"+zs.edt.strftime("%Y-%m-%d"))
        czsc_logger().info("策略结算结果：只有一个中枢！！！")
        return 0

    # 收盘价在中枢内
    stock_close = df['close'].iloc[-1]
    if stock_close>last_zs.zd and stock_close < last_zs.zg:
        czsc_logger().info("【"+symbol+"】"+"最后一个中枢区间："+zs.sdt.strftime("%Y-%m-%d")+"到"+zs.edt.strftime("%Y-%m-%d"))
        czsc_logger().info("策略结算结果：当前收盘价在中枢内"+str(stock_close))
        return 0

    # 最后一笔向上
    # if last_bi in last_zs.bis:
    #     czsc_logger().info("【"+symbol+"】"+"最后一个中枢区间："+zs.sdt.strftime("%Y-%m-%d")+"到"+zs.edt.strftime("%Y-%m-%d"))
    #     czsc_logger().info("策略结算结果：最后一笔还在中枢内"+str(stock_close))
    #     return False

    # 判断两个中枢方法
    if last_zs.edir == prev_zs.edir: #两个同向中枢形成趋势，寻找一买点
        if last_zs.edir == Direction.Down:
            if stock_close < last_zs.zd:
                return 1
    else:
        # 新向上的趋势第一个中枢；寻找三买点
        if last_zs.edir == Direction.Up:
            if stock_close > last_zs.zg:
                return 3
    return 0

"""
    生成扩展数据extrs和rps数据
"""
def get_rps_data(df):
    if not 'EXTRS10' in df.columns:
        df['EXTRS10'] = (df['close']-REF(df['close'], 10))/REF(df['close'], 10)
        df['RPS10'] = df['EXTRS10'].rank(pct=True) * 100
    if not 'EXTRS20' in df.columns:
        df['EXTRS20'] = (df['close']-REF(df['close'], 20))/REF(df['close'], 20)
        df['RPS20'] = df['EXTRS20'].rank(pct=True) * 100
    if not 'EXTRS50' in df.columns:
        df['EXTRS50'] = (df['close']-REF(df['close'], 50))/REF(df['close'], 50)
        df['RPS50'] = df['EXTRS50'].rank(pct=True) * 100
    if not 'EXTRS120' in df.columns:
        df['EXTRS120'] = (df['close']-REF(df['close'], 120))/REF(df['close'], 120)
        df['RPS120'] = df['EXTRS120'].rank(pct=True) * 100
    if not 'EXTRS250' in df.columns:
        df['EXTRS250'] = (df['close']-REF(df['close'], 250))/REF(df['close'], 250)
        df['RPS250'] = df['EXTRS250'].rank(pct=True) * 100
    return df

"""
    生成KD线数据
"""
def get_kd_data(df):
    if not 'VAR' in df.columns:
        df['VAR'] = (df['close'] - LLV(df['low'], 10)) / (HHV(df['high'], 10) - LLV(df['low'], 10)) * 100
        df['K0'] = SMA(df['VAR'], 10, 1)
        # df['D0'] = REF(df['K0'], 1)
        # df['KD0'] = df['K0']-df['D0']
        # df['KDR'] = (df['K0']-df['D0'])/df['K0']
    return df

"""
    获取股票数据
    参数：
        symbol：股票代码
        start_date：开始日期
        end_date：结束日期
        
"""
def get_stcok_pd(symbol, start_date, end_date, frequency):
    """
        code：股票代码，sh或sz.+6位数字代码，或者指数代码，如：sh.601398。sh：上海；sz：深圳。此参数不可为空；
        fields：指示简称，支持多指标输入，以半角逗号分隔，填写内容作为返回类型的列。详细指标列表见历史行情指标参数章节，日线与分钟线参数不同。此参数不可为空；
        start：开始日期（包含），格式“YYYY-MM-DD”，为空时取2015-01-01；
        end：结束日期（包含），格式“YYYY-MM-DD”，为空时取最近一个交易日；
        frequency：数据类型，默认为d，日k线；d=日k线、w=周、m=月、5=5分钟、15=15分钟、30=30分钟、60=60分钟k线数据，不区分大小写；指数没有分钟线数据；周线每周最后一个交易日才可以获取，月线每月最后一个交易日才可以获取。
        adjustflag：复权类型，默认不复权：3；1：后复权；2：前复权。已支持分钟线、日线、周线、月线前后复权。 BaoStock提供的是涨跌幅复权算法复权因子，具体介绍见：复权因子简介或者BaoStock复权因子简介。
    """
    rs = bs.query_history_k_data_plus(
            code=symbol,
            fields="date,open,high,low,close,volume,amount",
            start_date=start_date,
            end_date=end_date,
            frequency=frequency,
            adjustflag="3",
        )
    if int(rs.error_code) > 0:
        czsc_logger().info('query_history_k_data_plus respond error_code:' + rs.error_code)
        czsc_logger().info('query_history_k_data_plus respond  error_msg:' + rs.error_msg)
        return []
    data_list = []
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
            data_list.append(row_data)
            # data_list.append([stock_date, stock_open, stock_high, stock_low, stock_close, stock_volume, stock_amount])
        except Exception as e:
            # czsc_logger().info(e)
            continue
        
    df = pd.DataFrame(data_list, columns=rs.fields)
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['amount'] = df['amount'].astype(float)
    df['datetime'] = pd.to_datetime(df['date'])
    # df.set_index('date', inplace=True)
    return df

"""
    股票数据转换为NewBar
"""
def get_stock_bars(symbol, start_date=None, end_date=None, frequency='d', df=None):
    if df is None or len(df.columns.tolist()) <= 0:
        if start_date and end_date and frequency:
            df = get_stcok_pd(symbol, start_date, end_date, frequency)
        else:
            return []

    if not 'dt' in df.columns:
        df.loc[:, "dt"] = pd.to_datetime(df['date'])
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
    return [RawBar(symbol=symbol, id=i, freq=Freq.D, open=row['open'], dt=row['dt'],
                    close=row['close'], high=row['high'], low=row['low'], vol=row['volume'], amount=row['amount'])
                for i, row in df.iterrows()]

"""
    获取最后一天交易日日期
"""
TRADING_DATE = ""
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
    result = query_trade_data_to_pd(rs)

    # 筛选出交易日
    trading_days = result[result["is_trading_day"] == '1']['calendar_date']
    # 获取最后一个交易日
    last_trading_day = trading_days.iloc[-1]
    czsc_logger().info(f"距今最后一个交易日是：{last_trading_day}")
    TRADING_DATE = last_trading_day
    return last_trading_day

"""
    获取A股所有股票
"""
def get_daily_symbols():
    symbol_file = os.path.join(get_data_dir(), 'sh_sz_stock.json')
    return read_json(symbol_file)

"""
    股票是否是融资融券
"""
def is_rz_rq_symobl(symbol):
    symbols = get_rz_rq_symbols()
    return symbol in symbols

"""
    获取所有可融资融券
"""
RZ_RQ_STOCKS = []
def get_rz_rq_symbols():
    if len(RZ_RQ_STOCKS)>0:
        return RZ_RQ_STOCKS
    result = []
    try:
        response = requests.get("http://api.mairui.club/hsrq/list/LICENCE-66D8-9F96-0C7F0FBCD073")
        if response.status_code == 200:
            result = json.loads(response.content)
    except Exception as e:
        czsc_logger().info(e)
    if len(result) <= 0:
        result = read_json(os.path.join(get_data_dir(), 'rz_rq_stock.json'))
    for item in result:
        RZ_RQ_STOCKS.append("{}.{}".format(item["jys"],item["dm"]))
    return RZ_RQ_STOCKS

"""
    月线反转板块数据
"""
def get_mline_area_stocks():
    mline_file = get_mline_area_path()
    return read_json(mline_file)

"""
    小黄人三线红板块数据
"""
def get_minion_area_stocks():
    minion_file = get_minion_area_path()
    return read_json(minion_file)

"""
    月线反转板块文件
"""
def get_mline_area_path():
    data_path = get_data_dir()
    return os.path.join('mline_area.json')

"""
    小黄人三线红板块文件
"""
def get_minion_area_path():
    data_path = get_data_dir()
    return os.path.join('minion_area.json')

"""
    读取json文件
"""
def read_json(json_path):
    if os.path.exists(json_path):
        with open(json_path, 'r') as file:
            data = json.load(file)
            file.close()
            return data
    return None

"""
    json数据写入文件
"""
def write_json(data, json_path):
    if os.path.exists(json_path):
        os.remove(json_path)
    with open(json_path, 'w') as file:
        json.dump(data, file, indent=4)
        file.close()

"""
    两个数的平方根
"""
def sqrt_val(a,b):
    return round(math.sqrt(a*b),3)

"""
    数组内list的并集
"""
def union_list(list_arr):
    union_list = []
    for list_ in list_arr:
        union_list = set(list_).union(union_list)
        union_list = list(union_list)
    return union_list

"""
    数组内list的交集
"""
def intersection_list(list_arr):
    is_first = True
    intersection_list = []
    for list_ in list_arr:
        if is_first:
            is_first = False
            intersection_list = list_
        else:
            intersection_list = set(list_).intersection(intersection_list)
            intersection_list = list(intersection_list)
    return intersection_list

"""
    黄金分割线的低点
"""
def gold_val_low(a,b):
    # 0.382、 0.618
    val = max(a,b)-min(a,b)
    return val*0.382 + min(a,b)
   
"""
    获取项目data目录
"""
def get_data_dir():
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(cur_dir, 'data')

"""
    从start_date到end_date总的有几个交易
"""
def days_trade_delta(df, start_date, end_date):
    start_index = df.index[df['date'] == start_date].tolist()
    assert len(start_index)>0
    end_index = df.index[df['date'] == end_date].tolist()
    assert len(end_index)>0
    return int(end_index[0])-int(start_index[0])+1

"""
    从start_date开始到最后，最小收盘价
"""
def get_min_close(df, start_date):
    is_first = True
    min_close = 1000000
    start_index = df.index[df['date'] == start_date].tolist()
    assert len(start_index)>0
    start_index = start_index[0]
    for x in range(start_index,len(df['close'])):
        if is_first:
            is_first = False
            min_close = df['close'].iloc[x]
        else:
            min_close = MIN(min_close,df['close'].iloc[x])
    return min_close

# baostock查询结果转换成数组
def query_trade_data_to_pd(rs):
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)
    return result
