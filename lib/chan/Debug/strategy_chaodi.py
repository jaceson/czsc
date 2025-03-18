import os,sys,getopt,json
parentdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
sys.path.insert(0,parentdir)

import talib
from MyTT import *
import baostock as bs
import pandas as pd
from Chan import CChan
from ChanConfig import CChanConfig
from datetime import datetime, timedelta
from Common.CEnum import AUTYPE, BSP_TYPE, DATA_SRC, FX_TYPE, KL_TYPE

def usage():
    print ("-t: 周期级别，如1：日，2：60分钟，3：30分钟")
    print ("-n: 上一个状态持续个数")
    pass

opts,args = getopt.getopt(sys.argv[1:], "ht:n:")
KLINE_TYPE = 1 
PERIOD_VAL = 9 #趋势天数
DAYS_NUM = 90  #股票数据时间跨度
COST_VAL = 0.01 #每笔交易固定扣除
TRADING_DATE = "" #最后一个交易日
for op, value in opts:
    if op == "-t":
        KLINE_TYPE = int(value)
    elif op == "-n":
        PERIOD_VAL = int(value)
    elif op == "-h":    
        usage()
        sys.exit()

def read_json(path):
    with open(path, 'r') as file:
        data = json.load(file)
        return data

def write_json(data, path):
    with open(path, 'w') as file:
        json.dump(data, file, indent=4)

# 是否相邻的两个交易日
def isNextDay(df,beforeDay,afterDay):
    target_index_before = df.index.get_loc(beforeDay)
    target_index_after = df.index.get_loc(afterDay)
    return target_index_after<=(target_index_before+1)

# baostock查询结果转换成数组
def querydata_to_list(rs):
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)
    return result

def get_buy_point(df,code,isToday=False):
    # 筛选符合买入条件的股票
    buy_con1 = (
        (df['KD0'] > 0) & (df['K1'] < 20) &
        (df['KD1'] < 0) & (df['KD1'] > -0.5) &
        (df['KD2'] < 0) & (df['KD3'] < 0) &
        (df['KD4'] < 0) & (df['KD5'] < 0) &
        (df['KD6'] < 0) & (df['KD7'] < 0) &
        (df['KD8'] < 0) & (df['KD9'] < 0)
    )
    buy_con2 = (
        (df['K0'] < 20) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
    buy_con3 = (
        (df['K0'] < 30) &
        (df['KDR'] >= -0.03) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) &
        (df['low'] <= REF(df['low'], 1)) &
        (df['high'] <= REF(df['high'], 1)) &
        (REF(df['low'], 1) <= REF(df['low'], 2)) &
        (REF(df['high'], 1) <= REF(df['high'], 2)) 
    )
    # 最后一天交易日
    last_trading_day = df.index[-1]

    # 获取符合条件的日期
    buy_points = []
    # if not df[buy_con1].empty:
    #     selected_dates = df[buy_con1].index
    #     selected_dates = selected_dates.values
    #     if isToday:
    #         if selected_dates[-1] == last_trading_day:
    #             buy_points.append(last_trading_day)
    #             print("%s符合条件的日期：%s"%(code, last_trading_day))
    #     else:
    #         for selected_date in selected_dates:
    #             if selected_date == last_trading_day:
    #                 buy_points.append(last_trading_day)
    #             else:
    #                 target_index = df.index.get_loc(selected_date)
    #                 if len(buy_points)>0:
    #                     if not isNextDay(df,buy_points[-1],selected_date):
    #                         buy_points.append(selected_date)
    #                 else:
    #                     buy_points.append(selected_date)
    if not df[buy_con3].empty:
        selected_dates = df[buy_con3].index
        selected_dates = selected_dates.values
        if isToday:
            if selected_dates[-1] == last_trading_day:
                buy_points.append(last_trading_day)
                print("%s符合条件的日期：%s"%(code, last_trading_day))
        else:
            for selected_date in selected_dates:
                if selected_date == last_trading_day:
                    buy_points.append(last_trading_day)
                else:
                    target_index = df.index.get_loc(selected_date)
                    if len(buy_points)>0:
                        if not isNextDay(df,buy_points[-1],selected_date):
                            if target_index+1 < len(df):
                                buy_points.append(df.index[target_index+1])
                    else:
                        if target_index+1 < len(df):
                            buy_points.append(df.index[target_index+1])
    return buy_points

def get_sell_point(df,buy_point_date):
    if not buy_point_date in df.index:
        return None
    is_buy = False
    target_index = df.index.get_loc(buy_point_date)
    buy_target_data = df.iloc[target_index]
    for i in range(1,len(df)-target_index):
        target_data = df.iloc[target_index + i]
        # 筛选符合卖出条件的股票
        sell_con1 = (
            (target_data['KD0'] < 2) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con2 = (
            (target_data['K0'] > 60) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con3 = (target_data['close']/buy_target_data['open']>1.05)
        if sell_con3:
            if target_data['KD0']>3:
                if is_buy:
                    last_target_data = df.iloc[target_index + i - 1]
                    if last_target_data['close']>target_data['close']:
                        continue
                else:
                    is_buy = True
                    continue
            return df.index[target_index+i]
        else:
            if is_buy:
                return df.index[target_index+i]
        sell_con4 = (target_data['close']/buy_target_data['open']<0.95)
        if sell_con4:
            return df.index[target_index+i]
        # if sell_con1 == 1 or sell_con2 == 1:
        #     return df.index[target_index+i]
    return None
    return df.index[len(df)-1]

def get_trade_info(df, buy_point_date, sell_point_date):
    buy_date_index = df.index.get_loc(buy_point_date)
    sell_date_index = df.index.get_loc(sell_point_date)
    
    buy_result = df.loc[buy_point_date]
    sell_result = df.loc[sell_point_date]
    return {'buy_date':buy_point_date,
            'sell_date':sell_point_date,
            'hold_days':sell_date_index-buy_date_index,
            'buy_price':buy_result['open'],
            'sell_price':sell_result['close']}

def can_stock_chaodi(code):
    # 获取最后一个交易日期
    current_date_str = get_latest_trade_date()
    # 计算90天之前的日期
    date_90_days_ago = datetime.strptime(current_date_str, "%Y-%m-%d") - timedelta(days=DAYS_NUM)
    date_90_days_ago_str = date_90_days_ago.strftime('%Y-%m-%d')
    
    rs = bs.query_history_k_data_plus(
            code=code,
            fields="date,open,high,low,close,volume,amount,turn",
            start_date=date_90_days_ago_str,
            end_date=current_date_str,
            frequency="d",
            adjustflag="2",
        )
    # print('query_history_k_data_plus respond error_code:' + rs.error_code)
    # print('query_history_k_data_plus respond  error_msg:' + rs.error_msg)
    result = querydata_to_list(rs)
    # 数据转换pd
    df = pd.DataFrame(result)
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df.set_index('date', inplace=True)

    # 计算VAR1
    df['LLV_low_10'] = LLV(df['low'], 10)
    df['HHV_high_10'] = HHV(df['high'], 10)
    df['VAR1'] = (df['close'] - df['LLV_low_10']) / (df['HHV_high_10'] - df['LLV_low_10']) * 100
    df['K0'] = SMA(df['VAR1'], 10, 1)
    df['D0'] = REF(df['K0'], 1)
    df['KD0'] = df['K0']-df['D0']
    df['KDR'] = (df['K0']-df['D0'])/df['D0']

    df['K1'] = REF(df['K0'], 1)
    df['D1'] = REF(df['K0'], 2)
    df['KD1'] = df['K1']-df['D1']
    
    df['K2'] = REF(df['K0'], 2)
    df['D2'] = REF(df['K0'], 3)
    df['KD2'] = df['K2']-df['D2']
    
    df['K3'] = REF(df['K0'], 3)
    df['D3'] = REF(df['K0'], 4)
    df['KD3'] = df['K3']-df['D3']
    
    df['K4'] = REF(df['K0'], 4)
    df['D4'] = REF(df['K0'], 5)
    df['KD4'] = df['K4']-df['D4']
    
    df['K5'] = REF(df['K0'], 5)
    df['D5'] = REF(df['K0'], 6)
    df['KD5'] = df['K5']-df['D5']
    
    df['K6'] = REF(df['K0'], 6)
    df['D6'] = REF(df['K0'], 7)
    df['KD6'] = df['K6']-df['D6']
    
    df['K7'] = REF(df['K0'], 7)
    df['D7'] = REF(df['K0'], 8)
    df['KD7'] = df['K7']-df['D7']
    
    df['K8'] = REF(df['K0'], 8)
    df['D8'] = REF(df['K0'], 9)
    df['KD8'] = df['K8']-df['D8']
    
    df['K9'] = REF(df['K0'], 9)
    df['D9'] = REF(df['K0'], 10)
    df['KD9'] = df['K9']-df['D9']

    # 计算MAV
    # df['MAV'] = (df['close']+df['close']+df['high']+df['low'])/4
    # df['VAR5'] = LLV(df['low'], 34)
    # df['VAR6'] = HHV(df['high'], 34)
    # df['SK1'] = EMA((df['MAV']-df['VAR5'])/(df['VAR6']-df['VAR5'])*100, 13)
    # df['SD1'] = EMA(0.667*REF(df['SK1'], 1)+0.333*df['SK1'], 2)

    buy_points = get_buy_point(df,code,KLINE_TYPE==4)
    trade_points = []
    if len(buy_points) > 0:
        print(code)
    for buy_point_date in buy_points:
        sell_point_date = get_sell_point(df, buy_point_date)
        if sell_point_date:
            trade_info = get_trade_info(df,buy_point_date,sell_point_date)
            if len(trade_points)>0:
                last_trade_info = trade_points[-1]
                if last_trade_info['sell_date'] == trade_info['sell_date']:
                    continue
            trade_points.append(trade_info)
            print(trade_info)
        
    return trade_points

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

    all_codes = get_all_stock()

    # 回测策略
    trade_total_num = 0
    trade_total_val = 0

    trade_hold_max = 0
    trade_hold_min = 1000    

    trade_cost_num = 0
    trade_cost_val = 0
    
    trade_plus_num = 0
    trade_plus_val = 0

    trade_cost_max_val = 0
    trade_plus_max_val = 0

    trade_cost_val_stat = []
    trade_plus_val_stat = []
    trade_cost_days_stat = []
    trade_plus_days_stat = []
    
    for stock_code in all_codes:
        # if stock_code != "sh.600728":
        #     continue
        trade_points = can_stock_chaodi(stock_code)
        if len(trade_points) > 0:
            trade_total_num += len(trade_points) #交易次数
            for trade_info in trade_points:
                price_ratio = (float(trade_info['sell_price'])-float(trade_info['buy_price']))/float(trade_info['buy_price'])
                price_ratio -= COST_VAL #该笔交易收益
                trade_hold_max = MAX(trade_info['hold_days'], trade_hold_max)
                trade_hold_min = MIN(trade_info['hold_days'], trade_hold_min)

                trade_total_val += price_ratio #账户总收益
                if price_ratio < 0:
                    trade_cost_num += 1 #负收益
                    trade_cost_val += price_ratio #总的负收益
                    trade_cost_max_val = MIN(trade_cost_max_val, price_ratio) #最大负收益
                    trade_cost_val_stat.append(price_ratio)
                    trade_cost_days_stat.append(trade_info['hold_days'])
                else:
                    trade_plus_num += 1 #正收益
                    trade_plus_val += price_ratio #总的正收益
                    trade_plus_max_val = MAX(trade_plus_max_val, price_ratio) #最大正收益
                    trade_plus_val_stat.append(price_ratio)
                    trade_plus_days_stat.append(trade_info['hold_days'])

    print("策略收益汇总如下：")
    print("总的抄底交易次数：", trade_total_num)
    print("总的抄底交易收益：", trade_total_val)

    print("最大持有交易日：", trade_hold_max)
    print("最小持有交易日：", trade_hold_min)
    
    print("正收益交易次数占比：", trade_plus_num*100/trade_total_num)
    print("负收益交易次数占比：", trade_cost_num*100/trade_total_num)

    print("正收益总和：", trade_plus_val)
    print("负收益总和：", trade_cost_val)
    
    print("最大正收益：", trade_plus_max_val)
    print("最大负收益：", trade_cost_max_val)
    
    # 创建一个示例数据集
    data = pd.DataFrame({
        'cost': trade_cost_val_stat
    })
    # 查看数据的统计信息
    print(data.describe())
    data = pd.DataFrame({
        'plus':trade_plus_val_stat
    })
    # 查看数据的统计信息
    print(data.describe())
    data = pd.DataFrame({
        'cost_days':trade_cost_days_stat
    })
    # 查看数据的统计信息
    print(data.describe())
    data = pd.DataFrame({
        'plus_days':trade_plus_days_stat
    })
    # 查看数据的统计信息
    print(data.describe())
    # 登出系统
    bs.logout()

"""
case 1
参数：
DAYS_NUM = 90  #股票数据时间跨度
buy_con2 = (
        (df['K0'] < 30) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
sell_con1 = (
            (target_data['KD0'] < 2) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con2 = (
            (target_data['K0'] > 60) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )

策略收益汇总如下：
总的抄底交易次数： 981
总的抄底交易收益： -5.327604868519708
最大持有交易日： 29
最小持有交易日： 2
正收益交易次数占比： 41.99796126401631
负收益交易次数占比： 58.00203873598369
正收益总和： 20.671202881917047
负收益总和： -25.998807750436796
最大正收益： 0.7152566735112934
最大负收益： -0.22840193704600478
"""

"""
case 2
参数：
DAYS_NUM = 90  #股票数据时间跨度
buy_con2 = (
        (df['K0'] < 20) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
sell_con1 = (
            (target_data['KD0'] < 2) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con2 = (
            (target_data['K0'] > 60) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )

策略收益汇总如下：
总的抄底交易次数： 292
总的抄底交易收益： 1.427933259039835
最大持有交易日： 22
最小持有交易日： 2
正收益交易次数占比： 52.73972602739726
负收益交易次数占比： 47.26027397260274
正收益总和： 5.986864962951823
负收益总和： -4.558931703911993
最大正收益： 0.2860954446854662
最大负收益： -0.1436032388663968
             cost
count  174.000000
mean    -0.034370
std      0.038008
min     -0.209462
25%     -0.044395
50%     -0.022142
75%     -0.008023
max     -0.000326
             plus
count  148.000000
mean     0.047610
std      0.061342
min      0.000169
25%      0.010826
50%      0.026135
75%      0.052105
max      0.287114
        cost_days
count  174.000000
mean     8.965517
std      4.488774
min      2.000000
25%      5.000000
50%      9.000000
75%     11.000000
max     22.000000
       plus_days
count  148.00000
mean    10.02027
std      3.35125
min      3.00000
25%      8.00000
50%     10.00000
75%     12.00000
max     20.00000
"""

"""
case 4
参数：
DAYS_NUM = 90  #股票数据时间跨度
buy_con2 = (
        (df['K0'] < 20) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
sell_con1 = (
            (target_data['KD0'] < 2) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con2 = (
            (target_data['K0'] > 65) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
策略收益汇总如下：
总的抄底交易次数： 278
总的抄底交易收益： 1.2465869372234677
最大持有交易日： 20
最小持有交易日： 2
正收益交易次数占比： 51.07913669064748
负收益交易次数占比： 48.92086330935252
正收益总和： 5.508183897686501
负收益总和： -4.261596960463037
最大正收益： 0.27308026030368754
最大负收益： -0.1436032388663968
"""

"""
case 3
参数：
DAYS_NUM = 90  #股票数据时间跨度
buy_con2 = (
        (df['K0'] < 15) &
        (df['KD0'] < 0) & (df['KD0'] > -0.5) &
        (df['KD1'] < 0) & (df['KD2'] < 0) & 
        (df['KD3'] < 0) & (df['KD4'] < 0) & 
        (df['KD5'] < 0) & (df['KD6'] < 0) & 
        (df['KD7'] < 0) & (df['KD8'] < 0) 
    )
sell_con1 = (
            (target_data['KD0'] < 2) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
        sell_con2 = (
            (target_data['K0'] > 60) & 
            (target_data['KD1'] > 2) & 
            (target_data['KD2'] > 0) 
        )
策略收益汇总如下：
总的抄底交易次数： 50
总的抄底交易收益： 0.2971514572241137
最大持有交易日： 20
最小持有交易日： 3
正收益交易次数占比： 54.0
负收益交易次数占比： 46.0
正收益总和： 0.9710658108592238
负收益总和： -0.6739143536351102
最大正收益： 0.2176887871853547
"""
