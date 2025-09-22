# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs
import numpy as np
from czsc_sqlite import get_local_stock_data

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

'''
    黄金分割买点
'''
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

# 上涨线段，从start_index开始一笔，上涨线段
def find_up_seg(bi_list, start_index):
    start_bi = None
    last_bi = None
    for index in range(start_index,len(bi_list)):
        cur_bi = bi_list[index]
        # 过滤下降笔
        if cur_bi.fx_a.fx > cur_bi.fx_b.fx:
            continue
        # 开始一笔
        if not start_bi:
            start_bi = cur_bi
            continue
        if last_bi:
            if cur_bi.fx_a.fx > last_bi.fx_a.fx and cur_bi.fx_b.fx > last_bi.fx_b.fx:
                last_bi = cur_bi
            else:
                break
        elif cur_bi.fx_a.fx > start_bi.fx_a.fx and cur_bi.fx_b.fx > start_bi.fx_b.fx:
            last_bi = cur_bi
            continue
        else:
            break
    if start_bi:
        if last_bi:
            return start_bi.fx_a,last_bi.fx_b,last_bi
        else:
            return start_bi.fx_a,start_bi.fx_b,None
    else:
        return None,None,None

# 进一步进化版黄金分割点策略
# 统计变量
total_cases = 0
fx_b_greater_equal_count = 0  # last_down_bi的fx_b.fx大于等于down_bi.fx_b.fx的次数
closer_to_ma60_count = 0      # last_down_bi的fx_b.fx更接近MA60的次数
closer_to_ma120_count = 0     # last_down_bi的fx_b.fx更接近MA120的次数
    
# 收益统计变量
ma60_buy_ratios = []          # MA60买入策略的收益
ma120_buy_ratios = []         # MA120买入策略的收益

def more_evolution_goldenline(df, c):
    global total_cases, fx_b_greater_equal_count, closer_to_ma60_count, closer_to_ma120_count
    global ma60_buy_ratios, ma120_buy_ratios
    
    klines = 10
    min_angle = 20
    threshold = 1.7
    start_index = 0
    
    # 预计算MA指标
    df['MA60'] = MA(df['close'], 60)
    df['MA120'] = MA(df['close'], 120)
    
    # 创建日期到索引的映射，避免重复查找
    date_to_index = {date: idx for idx, date in enumerate(df['date'])}
    
    # 预计算所有需要的日期字符串，避免重复strftime调用
    bi_dates_cache = {}
    for bi in c.bi_list:
        bi_dates_cache[id(bi.fx_a)] = bi.fx_a.dt.strftime("%Y-%m-%d")
        bi_dates_cache[id(bi.fx_b)] = bi.fx_b.dt.strftime("%Y-%m-%d")
    
    while start_index < len(c.bi_list):
        fx_a, fx_b, last_bi = find_up_seg(c.bi_list, start_index)
        end_index = start_index
        if last_bi:
            end_index = c.bi_list.index(last_bi)
        
        if fx_a and fx_b:
            if fx_a.fx * threshold < fx_b.fx:
                # 上一波涨幅必须超过10个交易
                fx_a_date = bi_dates_cache[id(fx_a)]
                fx_b_date = bi_dates_cache[id(fx_b)]
                up_kline_num = days_trade_delta(df, fx_a_date, fx_b_date)
                if up_kline_num < klines:
                    start_index = end_index + 1 if last_bi else start_index + 1
                    continue
                    
                # 笔的角度
                if bi_angle(df, fx_a, fx_b) < min_angle:
                    start_index = end_index + 1 if last_bi else start_index + 1
                    continue
                    
                # 下降到黄金点以下
                sqr_val = sqrt_val(fx_a.fx, fx_b.fx)
                gold_low_val = gold_val_low(fx_a.fx, fx_b.fx)
                
                if (end_index + 1) < len(c.bi_list):
                    down_bi = c.bi_list[end_index + 1]
                    # 满足下跌到黄金买点
                    if down_bi.fx_b.fx < max(sqr_val, gold_low_val):
                        # 看黄金买点之后再次下跌
                        if (end_index + 3) < len(c.bi_list):
                            # 黄金买点后上涨一笔
                            last_up_bi = c.bi_list[end_index + 2]
                            # 黄金买点后再次下跌一笔
                            last_down_bi = c.bi_list[end_index + 3]
                            if (end_index + 4) < len(c.bi_list):
                                buy_up_bi = c.bi_list[end_index + 4]
                                
                                total_cases += 1
                                
                                # 1. 统计last_down_bi的fx_b.fx大于等于down_bi.fx_b.fx的占比
                                if last_down_bi.fx_b.fx >= down_bi.fx_b.fx:
                                    fx_b_greater_equal_count += 1
                                
                                # 2. 统计last_down_bi的fx_b.fx更接近MA60和MA120的占比
                                last_down_bi_date = bi_dates_cache[id(last_down_bi.fx_b)]
                                if last_down_bi_date in date_to_index:
                                    idx = date_to_index[last_down_bi_date]
                                    if idx < len(df):
                                        ma60_val = df['MA60'].iloc[idx]
                                        ma120_val = df['MA120'].iloc[idx]
                                        last_down_bi_fx_b = last_down_bi.fx_b.fx
                                        
                                        # 计算距离
                                        dist_to_ma60 = abs(last_down_bi_fx_b - ma60_val)
                                        dist_to_ma120 = abs(last_down_bi_fx_b - ma120_val)
                                        
                                        if dist_to_ma60 < dist_to_ma120:
                                            closer_to_ma60_count += 1
                                        else:
                                            closer_to_ma120_count += 1
                                
                                # 3. 当last_up_bi的fx_a.fx更接近MA60时的买入策略
                                last_up_bi_date = bi_dates_cache[id(last_up_bi.fx_a)]
                                if last_up_bi_date in date_to_index:
                                    idx = date_to_index[last_up_bi_date]
                                    if idx < len(df):
                                        ma60_val = df['MA60'].iloc[idx]
                                        ma120_val = df['MA120'].iloc[idx]
                                        last_up_bi_fx_a = last_up_bi.fx_a.fx
                                        
                                        # 判断last_up_bi的fx_a.fx更接近MA60
                                        dist_to_ma60 = abs(last_up_bi_fx_a - ma60_val)
                                        dist_to_ma120 = abs(last_up_bi_fx_a - ma120_val)
                                        
                                        if dist_to_ma60 < dist_to_ma120:
                                            # 查找从last_down_bi.fx_a开始到last_down_bi.fx_b结束时间段内，哪天收盘价close小于MA60
                                            start_date = bi_dates_cache[id(last_down_bi.fx_a)]
                                            end_date = bi_dates_cache[id(last_down_bi.fx_b)]
                                            
                                            if start_date in date_to_index and end_date in date_to_index:
                                                start_idx = date_to_index[start_date]
                                                end_idx = date_to_index[end_date]
                                                
                                                # 使用向量化操作查找买入点
                                                if start_idx < len(df) and end_idx < len(df):
                                                    # 获取该时间段的收盘价和MA60
                                                    close_prices = df['close'].iloc[start_idx:end_idx+1].values
                                                    ma60_values = df['MA60'].iloc[start_idx:end_idx+1].values
                                                    
                                                    # 找到第一个收盘价小于MA60的位置
                                                    buy_mask = close_prices < ma60_values
                                                    if np.any(buy_mask):
                                                        buy_idx = start_idx + np.argmax(buy_mask)
                                                        if buy_idx < len(df):
                                                            # 计算到buy_up_bi.fx_b的收益
                                                            buy_price = df['close'].iloc[buy_idx]
                                                            buy_date = df['date'].iloc[buy_idx]
                                                            sell_date = bi_dates_cache[id(buy_up_bi.fx_b)]
                                                            
                                                            if sell_date in date_to_index:
                                                                sell_idx = date_to_index[sell_date]
                                                                if sell_idx > buy_idx and sell_idx < len(df):
                                                                    sell_price = df['close'].iloc[sell_idx]
                                                                    ratio = round(100 * (sell_price - buy_price) / buy_price, 2)
                                                                    ma60_buy_ratios.append(ratio)
                                                                    print(f"{symbol} - MA60买入策略 - 购买日期: {buy_date}, 购买价格: {buy_price:.2f}, 卖出日期: {sell_date}, 卖出价格: {sell_price:.2f}, 收益率: {ratio}%")
                                        
                                        # 4. 当last_up_bi的fx_a.fx更接近MA60时的MA120买入策略
                                        if dist_to_ma60 < dist_to_ma120:
                                            # 查找从last_down_bi.fx_a开始到last_down_bi.fx_b结束时间段内，哪天收盘价close小于MA120
                                            start_date = bi_dates_cache[id(last_down_bi.fx_a)]
                                            end_date = bi_dates_cache[id(last_down_bi.fx_b)]
                                            
                                            if start_date in date_to_index and end_date in date_to_index:
                                                start_idx = date_to_index[start_date]
                                                end_idx = date_to_index[end_date]
                                                
                                                # 使用向量化操作查找买入点
                                                if start_idx < len(df) and end_idx < len(df):
                                                    # 获取该时间段的收盘价和MA120
                                                    close_prices = df['close'].iloc[start_idx:end_idx+1].values
                                                    ma120_values = df['MA120'].iloc[start_idx:end_idx+1].values
                                                    
                                                    # 找到第一个收盘价小于MA120的位置
                                                    buy_mask = close_prices < ma120_values
                                                    if np.any(buy_mask):
                                                        buy_idx = start_idx + np.argmax(buy_mask)
                                                        if buy_idx < len(df):
                                                            # 计算到buy_up_bi.fx_b的收益
                                                            buy_price = df['close'].iloc[buy_idx]
                                                            buy_date = df['date'].iloc[buy_idx]
                                                            sell_date = bi_dates_cache[id(buy_up_bi.fx_b)]
                                                            
                                                            if sell_date in date_to_index:
                                                                sell_idx = date_to_index[sell_date]
                                                                if sell_idx > buy_idx and sell_idx < len(df):
                                                                    sell_price = df['close'].iloc[sell_idx]
                                                                    ratio = round(100 * (sell_price - buy_price) / buy_price, 2)
                                                                    ma120_buy_ratios.append(ratio)
                                                                    print(f"{symbol} - MA120买入策略 - 购买日期: {buy_date}, 购买价格: {buy_price:.2f}, 卖出日期: {sell_date}, 卖出价格: {sell_price:.2f}, 收益率: {ratio}%")
                            
            start_index = end_index + 1 if last_bi else start_index + 1
        else:
            break

# 进化版黄金分割点策略
threshold = 1.7
def evolution_goldenline(df,c):
    start_index = 0
    while start_index<len(c.bi_list):
        fx_a,fx_b,last_bi = find_up_seg(c.bi_list,start_index)
        if fx_a and fx_b:
            min_angle = 20
            end_index = start_index
            if last_bi:
                end_index = c.bi_list.index(last_bi)
                min_angle = max(10, min_angle-2*(end_index-start_index)%2)
            start_index += 1
            get_buy_point(df,fx_a,fx_b,None,threshold,10,min_angle)
        else:
            break

# 初始黄金分割点策略
def normal_goldenline(df,c):
    idx = 0
    for last_bi in c.bi_list:
        fx_a = last_bi.fx_a
        fx_b = last_bi.fx_b
        if fx_a.fx > fx_b.fx:
            idx += 1
            continue

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

if __name__ == '__main__':
    type_goldenline = 0
    if len(sys.argv)>1:
        type_goldenline = int(sys.argv[1])
    start_date = "2020-01-01"
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        print("[{}] 进度：{} / {}".format(pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), all_symbols.index(symbol), len(all_symbols)))
        df = get_local_stock_data(symbol,start_date)
        bars = get_stock_bars(symbol=symbol,df=df)
        c = CZSC(bars, get_signals=None)
        if type_goldenline == 0:
            # 初始黄金分割点策略
            normal_goldenline(df,c)
        elif type_goldenline == 1:
            # 进化版黄金分割点策略
            evolution_goldenline(df,c)
        elif type_goldenline == 2:
            # 进一步进化版黄金分割点策略
            more_evolution_goldenline(df,c)

    # 输出统计结果
    if type_goldenline == 2:
        print("\n=== 进一步进化版黄金分割点策略统计结果 ===")
        print(f"总案例数: {total_cases}")
    
        if total_cases > 0:
            # 1. last_down_bi的fx_b.fx大于等于down_bi.fx_b.fx的占比
            fx_b_ratio = round(100 * fx_b_greater_equal_count / total_cases, 2)
            print(f"1. last_down_bi的fx_b.fx大于等于down_bi.fx_b.fx的占比: {fx_b_ratio}% ({fx_b_greater_equal_count}/{total_cases})")
        
            # 2. last_down_bi的fx_b.fx更接近MA60和MA120的占比
            closer_to_ma60_ratio = round(100 * closer_to_ma60_count / total_cases, 2)
            closer_to_ma120_ratio = round(100 * closer_to_ma120_count / total_cases, 2)
            print(f"2. last_down_bi的fx_b.fx更接近MA60的占比: {closer_to_ma60_ratio}% ({closer_to_ma60_count}/{total_cases})")
            print(f"   last_down_bi的fx_b.fx更接近MA120的占比: {closer_to_ma120_ratio}% ({closer_to_ma120_count}/{total_cases})")
        
            # 3. MA60买入策略收益统计
            if ma60_buy_ratios:
                positive_ma60 = [r for r in ma60_buy_ratios if r > 0]
                negative_ma60 = [r for r in ma60_buy_ratios if r <= 0]
                positive_ratio_ma60 = round(100 * len(positive_ma60) / len(ma60_buy_ratios), 2)
                positive_sum_ma60 = round(sum(positive_ma60), 2)
                negative_sum_ma60 = round(sum(negative_ma60), 2)
            
                print(f"3. MA60买入策略收益统计:")
                print(f"   正收益次数占比: {positive_ratio_ma60}% ({len(positive_ma60)}/{len(ma60_buy_ratios)})")
                print(f"   正收益总和: {positive_sum_ma60}")
                print(f"   负收益总和: {negative_sum_ma60}")
            else:
                print("3. MA60买入策略: 无符合条件的交易")
        
            # 4. MA120买入策略收益统计
            if ma120_buy_ratios:
                positive_ma120 = [r for r in ma120_buy_ratios if r > 0]
                negative_ma120 = [r for r in ma120_buy_ratios if r <= 0]
                positive_ratio_ma120 = round(100 * len(positive_ma120) / len(ma120_buy_ratios), 2)
                positive_sum_ma120 = round(sum(positive_ma120), 2)
                negative_sum_ma120 = round(sum(negative_ma120), 2)
            
                print(f"4. MA120买入策略收益统计:")
                print(f"   正收益次数占比: {positive_ratio_ma120}% ({len(positive_ma120)}/{len(ma120_buy_ratios)})")
                print(f"   正收益总和: {positive_sum_ma120}")
                print(f"   负收益总和: {negative_sum_ma120}")
                sys.exit(0)
            else:
                print("4. MA120买入策略: 无符合条件的交易")
                sys.exit(0)
        else:
            print("没有找到符合条件的案例")
            sys.exit(0)

    # 遍历数组并统计
    if len(total_ratio)>0:
        # 初始化计数器
        greater_than_zero = 0
        less_than_zero = 0
        for num in total_ratio:
            if num > 0:
                greater_than_zero += 1
            else:
                less_than_zero += 1
        print("正收益次数："+str(greater_than_zero))
        print("正收益占比："+str(round(100*greater_than_zero/len(total_ratio),2))+"%")    

    print("正收益次数："+str(len(plus_list)))
    if len(plus_list)>0:
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
        if plus_num>0 or minus_num>0:
            print("     正收益占比："+str(round(100*plus_num/(plus_num+minus_num),2))+"%")
        print("     总的正收益："+str(plus_val))
        print("     总的负收益："+str(minus_val))
        
    # 打印总体统计
    if len(total_ratio)>0:
        print_console('总收益：', total_ratio)
    if len(total_hold_days)>0:
        print_console('总持有天数：', total_hold_days)
    if len(plus_list):
        print_console('正收益：', plus_list)
    if len(minus_list)>0:
        print_console('负收益：', minus_list)
    for x in range(1,hold_days+1):
        if len(ratio_map[x])>0:
            print_console("第 {} 天：".format(x), ratio_map[x])
'''
初始黄金分割点策略:
正收益次数：488
正收益占比：81.06%
正收益次数：566
正收益占比：87.21%
总的正收益：5082.0900000000065
总的负收益：-206.79999999999998
第 1 天：
     正收益次数：489
     正收益占比：75.35%
     总的正收益：2282.0699999999993
     总的负收益：-390.41999999999996
第 2 天：
     正收益次数：431
     正收益占比：66.41%
     总的正收益：2765.099999999999
     总的负收益：-719.1300000000001
第 3 天：
     正收益次数：417
     正收益占比：64.25%
     总的正收益：3015.2699999999986
     总的负收益：-901.0400000000003
第 4 天：
     正收益次数：390
     正收益占比：60.09%
     总的正收益：3054.3700000000013
     总的负收益：-1216.9799999999993
第 5 天：
     正收益次数：382
     正收益占比：58.86%
     总的正收益：3348.880000000001
     总的负收益：-1493.13
总收益：
    平均值：18.522707641196014
    最大值：243.93
    最小值：-31.43
    50% 的百分位数：15.625
    95% 的百分位数：57.678999999999995
总持有天数：
    平均值：20.09468438538206
    最大值：116
    最小值：4
    50% 的百分位数：15.0
    95% 的百分位数：47.0
正收益：
    平均值：8.978957597173146
    最大值：80.18
    最小值：0.02
    50% 的百分位数：6.55
    95% 的百分位数：25.83
负收益：
    平均值：-2.4915662650602406
    最大值：-0.04
    最小值：-15.68
    50% 的百分位数：-1.79
    95% 的百分位数：-0.1310000000000001
第 1 天：
    平均值：2.9147149460708786
    最大值：26.88
    最小值：-15.68
    50% 的百分位数：2.32
    95% 的百分位数：11.006
第 2 天：
    平均值：3.152496147919877
    最大值：37.56
    最小值：-24.11
    50% 的百分位数：2.44
    95% 的百分位数：15.190000000000003
第 3 天：
    平均值：3.257673343605547
    最大值：50.33
    最小值：-25.73
    50% 的百分位数：2.15
    95% 的百分位数：17.556000000000008
第 4 天：
    平均值：2.8311093990755007
    最大值：64.17
    最小值：-30.96
    50% 的百分位数：1.43
    95% 的百分位数：19.414000000000012
第 5 天：
    平均值：2.8593990755007703
    最大值：80.18
    最小值：-34.12
    50% 的百分位数：1.44
    95% 的百分位数：21.140000000000008
'''

'''
正收益次数：1005
正收益占比：89.81%
总的正收益：8013.330000000004
总的负收益：-233.38
第 1 天：
     正收益次数：875
     正收益占比：78.19%
     总的正收益：3868.539999999995
     总的负收益：-519.7199999999999
第 2 天：
     正收益次数：790
     正收益占比：70.6%
     总的正收益：4711.909999999998
     总的负收益：-892.0500000000008
第 3 天：
     正收益次数：769
     正收益占比：68.72%
     总的正收益：4983.819999999994
     总的负收益：-1147.9400000000007
第 4 天：
     正收益次数：725
     正收益占比：64.79%
     总的正收益：4709.940000000003
     总的负收益：-1619.809999999998
第 5 天：
     正收益次数：720
     正收益占比：64.34%
     总的正收益：5236.66
     总的负收益：-1945.3100000000004
正收益：
    平均值：7.9734626865671645
    最大值：50.65
    最小值：0.07
    50% 的百分位数：6.11
    95% 的百分位数：20.65
负收益：
    平均值：-2.04719298245614
    最大值：-0.05
    最小值：-7.96
    50% 的百分位数：-1.41
    95% 的百分位数：-0.1430000000000001
第 1 天：
    平均值：2.9926899016979442
    最大值：22.46
    最小值：-9.51
    50% 的百分位数：2.45
    95% 的百分位数：10.68
第 2 天：
    平均值：3.413637176050045
    最大值：31.13
    最小值：-13.2
    50% 的百分位数：2.92
    95% 的百分位数：14.25
第 3 天：
    平均值：3.427953529937444
    最大值：42.92
    最小值：-22.96
    50% 的百分位数：2.71
    95% 的百分位数：16.014
第 4 天：
    平均值：2.7615102770330653
    最大值：48.46
    最小值：-24.95
    50% 的百分位数：1.92
    95% 的百分位数：17.38
第 5 天：
    平均值：2.9413315460232354
    最大值：50.65
    最小值：-27.04
    50% 的百分位数：2.19
    95% 的百分位数：18.11399999999999
'''

'''
=== 进一步进化版黄金分割点策略统计结果 ===
总案例数: 369
1. last_down_bi的fx_b.fx大于等于down_bi.fx_b.fx的占比: 55.56% (205/369)
2. last_down_bi的fx_b.fx更接近MA60的占比: 53.12% (196/369)
   last_down_bi的fx_b.fx更接近MA120的占比: 46.88% (173/369)
3. MA60买入策略收益统计:
   正收益次数占比: 52.11% (99/190)
   正收益总和: 2070.77
   负收益总和: -758.08
4. MA120买入策略收益统计:
   正收益次数占比: 50.28% (90/179)
   正收益总和: 1979.08
   负收益总和: -817.87
'''

'''
正收益次数：2005
正收益占比：88.48%
总的正收益：16433.66
总的负收益：-590.94
第 1 天：
     正收益次数：1741
     正收益占比：76.83%
     总的正收益：7784.920000000026
     总的负收益：-1135.05
第 2 天：
     正收益次数：1540
     正收益占比：67.96%
     总的正收益：9294.969999999981
     总的负收益：-2139.039999999996
第 3 天：
     正收益次数：1488
     正收益占比：65.67%
     总的正收益：9880.120000000024
     总的负收益：-2832.399999999997
第 4 天：
     正收益次数：1412
     正收益占比：62.31%
     总的正收益：9866.18000000003
     总的负收益：-3785.7499999999955
第 5 天：
     正收益次数：1353
     正收益占比：59.71%
     总的正收益：10688.36999999997
     总的负收益：-4547.100000000007
正收益：
    平均值：8.1963391521197
    最大值：60.79
    最小值：0.01
    50% 的百分位数：6.0
    95% 的百分位数：23.32
负收益：
    平均值：-2.2641379310344827
    最大值：0.0
    最小值：-15.68
    50% 的百分位数：-1.62
    95% 的百分位数：-0.13
第 1 天：
    平均值：2.934629302736099
    最大值：26.88
    最小值：-15.68
    50% 的百分位数：2.22
    95% 的百分位数：11.08
第 2 天：
    平均值：3.157956751985878
    最大值：37.56
    最小值：-24.11
    50% 的百分位数：2.41
    95% 的百分位数：14.25
第 3 天：
    平均值：3.1102030008826125
    最大值：42.92
    最小值：-25.73
    50% 的百分位数：2.145
    95% 的百分位数：15.76
第 4 天：
    平均值：2.683331862312445
    最大值：48.46
    最小值：-30.96
    50% 的百分位数：1.65
    95% 的百分位数：17.9775
第 5 天：
    平均值：2.7101809355692854
    最大值：60.79
    最小值：-34.12
    50% 的百分位数：1.44
    95% 的百分位数：18.59
'''
