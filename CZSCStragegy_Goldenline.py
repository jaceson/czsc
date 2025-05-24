# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs
import numpy as np

plus_list = []
minus_list = []
total_ratio = []
total_hold_days = []
hold_days = 5
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

def print_console(title, arr):
    # 计算平均值
    average = np.mean(arr)

    # 计算最大值
    max_value = np.max(arr)

    # 计算最小值
    min_value = np.min(arr)

    # 计算 5% 和 95% 的百分位数
    lower_bound = np.percentile(arr, 50)
    upper_bound = np.percentile(arr, 95)

    # 输出结果
    print(title)
    print(f"    平均值：{average}")
    print(f"    最大值：{max_value}")
    print(f"    最小值：{min_value}")
    print(f"    50% 的百分位数：{lower_bound}")
    print(f"    95% 的百分位数：{upper_bound}")

def get_buy_point(df,fx_a,fx_b,next_up_bi,threshold=1.7,klines=10,min_angle=20):
    sdt = fx_a.dt.strftime("%Y-%m-%d")
    edt = fx_b.dt.strftime("%Y-%m-%d")
    if fx_a.fx*threshold < fx_b.fx:
        # 上一波涨幅必须超过10个交易
        up_kline_num = days_trade_delta(df,fx_a.dt.strftime("%Y-%m-%d"),fx_b.dt.strftime("%Y-%m-%d"))
        if up_kline_num<klines:
            return False
        # 笔的角度
        if bi_angle(df,fx_a,fx_b)<min_angle:
            return False
        # 是否在抄底区间内
        sqr_val = sqrt_val(fx_a.fx, fx_b.fx)
        gold_low_val = gold_val_low(fx_a.fx, fx_b.fx)
        min_val = min(sqr_val,gold_low_val)
        start_index = df.iloc[df['date'].values == fx_b.dt.strftime("%Y-%m-%d")].index[0]
        end_index = len(df['date'])
        if next_up_bi:
            end_index = df.iloc[df['date'].values == next_up_bi.fx_a.dt.strftime("%Y-%m-%d")].index[0]+1
        for idx in range(start_index,end_index):
            stock_open = df['open'].iloc[idx]
            stock_close = df['close'].iloc[idx]
            stock_high = df['high'].iloc[idx]
            stock_low = df['low'].iloc[idx]

            # 三天内上涨
            if stock_low <= min_val and (idx+hold_days)<len(df['date']):
                if next_up_bi:
                    days_num = days_trade_delta(df,df['date'].iloc[idx],next_up_bi.fx_b.dt.strftime("%Y-%m-%d"))
                    ratio = round(100*(next_up_bi.fx_b.fx-stock_close)/stock_close,2)
                    total_ratio.append(ratio)
                    total_hold_days.append(days_num)
                    print("{} {}到{}笔：{}到黄金分割点,持有时间：{}，总收益：{}".format(symbol,sdt,edt,df['date'].iloc[idx],days_num,ratio))
                else:
                    print("{} {}到{}笔：{}到黄金分割点".format(symbol,sdt,edt,df['date'].iloc[idx]))
                # 调整到黄金点位时间太长
                # down_kline_num = days_trade_delta(df,last_bi.edt.strftime("%Y-%m-%d"),df['date'].iloc[idx])
                # if down_kline_num>=up_kline_num:
                #     break

                max_val = -1000
                # min_val = 1000
                for x in range(1,hold_days+1):
                    stock_high = df['high'].iloc[idx+x]
                    ratio = round(100*(stock_high-min_val)/min_val,2)
                    ratio_map[x].append(ratio)
                    max_val = max(max_val,ratio)
                    # min_val = min(min_val,ratio)
                    if ratio>0:
                        print("第 {} 天{}：正收益，{}".format(x, df['date'].iloc[idx+x],ratio))
                    else:
                        print("第 {} 天{}：负收益，{}".format(x, df['date'].iloc[idx+x],ratio))

                if max_val>0:
                    plus_list.append(max_val)
                else:
                    minus_list.append(max_val)
                break

if __name__ == '__main__':
    lg = bs.login()

    start_date = "2020-01-01"
    end_date = get_latest_trade_date()
    
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        df = get_stock_pd(symbol,start_date,end_date,"d")
        while len(df) <= 0:
            lg = bs.login()
            print('login respond error_code:' + lg.error_code)
            print('login respond  error_msg:' + lg.error_msg)
            # 重新获取
            df = get_stock_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')

        bars = get_stock_bars(symbol=symbol,df=df)
        c = CZSC(bars, get_signals=None)
        idx = 0
        for last_bi in c.bi_list:
            fx_a = last_bi.fx_a
            fx_b = last_bi.fx_b
            if fx_a.fx > fx_b.fx:
                idx += 1
                continue

            threshold = 1.7
            if fx_a.fx*threshold > fx_b.fx:
                if idx>1:
                    pre_up_bi = c.bi_list[idx-2]
                    if pre_up_bi.fx_a.fx < fx_a.fx and pre_up_bi.fx_b.fx < fx_b.fx:
                        fx_a = pre_up_bi.fx_a
            next_up_bi = None
            if (idx+2)<len(c.bi_list):
                next_up_bi = c.bi_list[idx+2]
            get_buy_point(df,fx_a,fx_b,next_up_bi,threshold)
            idx += 1

    # 初始化计数器
    greater_than_zero = 0
    less_than_zero = 0

    # 遍历数组并统计
    for num in total_ratio:
        if num > 0:
            greater_than_zero += 1
        else:
            less_than_zero += 1
    print("正收益次数："+str(greater_than_zero))
    print("正收益占比："+str(round(100*greater_than_zero/len(total_ratio),2))+"%")    

    print("正收益次数："+str(len(plus_list)))
    print("正收益占比："+str(round(100*len(plus_list)/(len(minus_list)+len(plus_list)),2))+"%")
    total = 0
    for x in range(0,len(plus_list)):
        total += plus_list[x]
    print("总的正收益："+str(total))

    total = 0
    for x in range(0,len(minus_list)):
        total += minus_list[x]
    print("总的负收益："+str(total))
    
    # 每天
    for x in range(1,hold_days+1):
        print("第 {} 天：".format(x))
        res_list = ratio_map[x]
        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for idx in range(0,len(res_list)):
            ratio = res_list[idx]
            if ratio>0:
                plus_num += 1
                plus_val += ratio
            else:
                minus_num += 1
                minus_val += ratio
        print("     正收益次数："+str(plus_num))
        print("     正收益占比："+str(round(100*plus_num/(plus_num+minus_num),2))+"%")
        print("     总的正收益："+str(plus_val))
        print("     总的负收益："+str(minus_val))
        
    # 打印总体统计
    print_console('总收益：', total_ratio)
    print_console('总持有天数：', total_hold_days)
    print_console('正收益：', plus_list)
    print_console('负收益：', minus_list)
    for x in range(1,hold_days+1):
        print_console("第 {} 天：".format(x), ratio_map[x])
        
    bs.logout()

