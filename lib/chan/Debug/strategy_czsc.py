import os,sys,getopt,json
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
sys.path.insert(0,parentdir)

import talib
from MyTT import *
import logging
import baostock as bs
import pandas as pd
import backtrader as bt
from datetime import datetime, timedelta
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, BSP_TYPE, DATA_SRC, FX_TYPE, KL_TYPE
# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # 设置日志级别为 DEBUG

# 日志格式
log_format = "%(asctime)s - %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"  # 自定义日期格式，去掉微秒部分

# 创建 Formatter 并设置日期格式
formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

# 创建文件处理器，将日志写入文件
file_handler = logging.FileHandler("log.json", mode="a")  # 追加模式
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(formatter)

# 创建控制台处理器，将日志输出到控制台
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(formatter)

# 将处理器添加到日志器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

DAYS_NUM = 360
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

def is_before_days(dateStr,days=5):
    now_date_str = get_latest_trade_date()
    now_date = datetime.strptime(now_date_str, "%Y-%m-%d")
    pre_date = datetime.strptime(dateStr, "%Y-%m-%d")
    return (now_date-pre_date).days<=days

def can_stock_chaodi(code):
    # 获取当前日期
    # current_date = datetime.now()
    # # 计算90天之前的日期
    # date_90_days_ago = current_date - timedelta(days=DAYS_NUM)
    # # 最后一天交易日
    # last_trading_day = get_latest_trade_date()

    # # 获取当前日期
    # current_date_str = current_date.strftime('%Y-%m-%d')
    # date_90_days_ago_str = date_90_days_ago.strftime('%Y-%m-%d')
    
    # rs = bs.query_history_k_data_plus(
    #         code=code,
    #         fields="date,open,high,low,close,volume,amount,turn",
    #         start_date=date_90_days_ago_str,
    #         end_date=current_date_str,
    #         frequency="d",
    #         adjustflag="2",
    #     )
    # print('query_history_k_data_plus respond error_code:' + rs.error_code)
    # print('query_history_k_data_plus respond  error_msg:' + rs.error_msg)
    # result = querydata_to_list(rs)

    # # 数据转换pd
    # df = pd.DataFrame(result)
    # df['low'] = df['low'].astype(float)
    # df['high'] = df['high'].astype(float)
    # df['open'] = df['open'].astype(float)
    # df['close'] = df['close'].astype(float)
    # df.set_index('date', inplace=True)

    """
    一个极其弱智的策略，只交易一类买卖点，底分型形成后就开仓，直到一类卖点顶分型形成后平仓
    只用做展示如何自己实现策略，做回测用~
    """
    begin_time = "2024-01-01"
    end_time = "2025-03-18"
    data_src = DATA_SRC.BAO_STOCK
    lv_list = [KL_TYPE.K_DAY]

    config = CChanConfig({
        "trigger_step": True,  # 打开开关！
        "divergence_rate": 0.8,
        "min_zs_cnt": 1,
    })

    chan = CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=data_src,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    is_hold = False
    last_buy_price = None
    for chan_snapshot in chan.step_load():  # 每增加一根K线，返回当前静态精算结果
        bsp_list = chan_snapshot.get_bsp()  # 获取买卖点列表
        if not bsp_list:  # 为空
            continue
        last_bsp = bsp_list[-1]  # 最后一个买卖点
        if not last_bsp.is_buy:
            continue
        if is_before_days(last_bsp.klu.time.toDateStr("-")):
            logger.info(f'{code} {last_bsp.klu.time} {last_bsp.type}')
            return True
        # if BSP_TYPE.T1 not in last_bsp.type and BSP_TYPE.T1P not in last_bsp.type:  # 假如只做1类买卖点
        # if BSP_TYPE.T2 not in last_bsp.type:  # 假如只做1类买卖点
        # if BSP_TYPE.T3A not in last_bsp.type and BSP_TYPE.T3B not in last_bsp.type:  # 假如只做1类买卖点
        #     continue
        # cur_lv_chan = chan_snapshot[0]
        # if last_bsp.klu.klc.idx != cur_lv_chan[-2].idx:
        #     continue
        # if cur_lv_chan[-2].fx == FX_TYPE.BOTTOM and last_bsp.is_buy and not is_hold:  # 底分型形成后开仓
        #     last_buy_price = cur_lv_chan[-1][-1].close  # 开仓价格为最后一根K线close
        #     print(f'{code} {cur_lv_chan[-1][-1].time}:buy price = {last_buy_price}')
        #     is_hold = True
        # elif cur_lv_chan[-2].fx == FX_TYPE.TOP and not last_bsp.is_buy and is_hold:  # 顶分型形成后平仓
        #     sell_price = cur_lv_chan[-1][-1].close
        #     print(f'{code} {cur_lv_chan[-1][-1].time}:sell price = {sell_price}, profit rate = {(sell_price-last_buy_price)/last_buy_price*100:.2f}%')
        #     is_hold = False
    return False

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
    last_trading_day = get_latest_trade_date()
    # 登出系统
    bs.logout()

    all_codes = get_all_stock()
    res_list = []
    for stock_code in all_codes:
        if can_stock_chaodi(stock_code):
            res_list.append(stock_code)
    logger.info(f'{res_list}')

