# coding: utf-8
"""
MACD + KDJ 组合策略 - 简化版回测
参考 CZSCStragegy_Goldenline.py 实现

策略核心：
买入条件：
1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0
2. KDJ 超卖金叉：K < 30 且 K 上穿 D

卖出条件：
1. MACD 趋势向下：DIF < DEA（死叉状态）
2. KDJ 超买死叉：K > 80 且 K 下穿 D
满足任一条件即可卖出
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data


# 统计变量
plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []


def calculate_macd_kdj(df):
    """
    计算 MACD 和 KDJ 指标
    
    参数:
        df: 包含 close, high, low 的 DataFrame
    
    返回:
        添加了 MACD 和 KDJ 指标的 DataFrame
    """
    if df is None or len(df) < 50:
        return None
    
    ndf = df.copy()
    close = ndf['close'].values.astype(float)
    high = ndf['high'].values.astype(float)
    low = ndf['low'].values.astype(float)
    
    # 计算 MACD
    dif, dea, macd_bar = MACD(close)
    ndf['DIF'] = dif
    ndf['DEA'] = dea
    ndf['MACD'] = macd_bar
    
    # 计算 KDJ
    k, d, j = KDJ(high, low, close, N=9)
    ndf['K'] = k
    ndf['D_kdj'] = d  # 避免与 MACD 的 DEA 混淆
    ndf['J'] = j
    
    return ndf


def check_buy_signal(df, idx):
    """
    检查买入信号
    
    买入条件：
    1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0
    2. KDJ 超卖金叉：K < 30 且 K 上穿 D
    
    参数:
        df: DataFrame
        idx: 当前索引位置
    
    返回:
        bool: 是否出现买入信号
    """
    if idx < 1 or idx >= len(df):
        return False
    
    try:
        # 获取当前和前一根 K 线的数据
        dif_curr = df['DIF'].iloc[idx]
        dea_curr = df['DEA'].iloc[idx]
        k_curr = df['K'].iloc[idx]
        d_curr = df['D_kdj'].iloc[idx]
        
        dif_prev = df['DIF'].iloc[idx-1]
        dea_prev = df['DEA'].iloc[idx-1]
        k_prev = df['K'].iloc[idx-1]
        d_prev = df['D_kdj'].iloc[idx-1]
        
        # 1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0
        trend_up = (dif_curr > dea_curr) or (dif_curr > 0)
        
        # 2. KDJ 超卖金叉：K < 30 且 K 上穿 D（当前 K>D，前一天 K<=D）
        kdj_oversold = (k_curr < 30) and (k_curr > d_curr) and (k_prev <= d_prev)
        
        # 双条件同时满足
        buy_signal = trend_up and kdj_oversold
        
        return buy_signal
        
    except (IndexError, TypeError, KeyError):
        return False


def check_sell_signal(df, idx):
    """
    检查卖出信号
    
    卖出条件：
    1. MACD 趋势向下：DIF < DEA（死叉状态）
    2. KDJ 超买死叉：K > 80 且 K 下穿 D
    满足任一条件即可卖出
    
    参数:
        df: DataFrame
        idx: 当前索引位置
    
    返回:
        bool: 是否出现卖出信号
    """
    if idx < 1 or idx >= len(df):
        return False
    
    try:
        # 获取当前和前一根 K 线的数据
        dif_curr = df['DIF'].iloc[idx]
        dea_curr = df['DEA'].iloc[idx]
        k_curr = df['K'].iloc[idx]
        d_curr = df['D_kdj'].iloc[idx]
        
        dif_prev = df['DIF'].iloc[idx-1]
        dea_prev = df['DEA'].iloc[idx-1]
        k_prev = df['K'].iloc[idx-1]
        d_prev = df['D_kdj'].iloc[idx-1]
        
        # 1. MACD 趋势向下：DIF < DEA（死叉状态）
        trend_down = dif_curr < dea_curr
        
        # 2. KDJ 超买死叉：K > 80 且 K 下穿 D（当前 K<D，前一天 K>=D）
        kdj_overbought = (k_curr > 80) and (k_curr < d_curr) and (k_prev >= d_prev)
        
        # 满足任一条件即可卖出
        sell_signal = trend_down or kdj_overbought
        
        return sell_signal
        
    except (IndexError, TypeError, KeyError):
        return False


def get_macd_kdj_buy_point(symbol, df):
    """
    获取 MACD+KDJ 策略买入点并统计收益
    
    参数:
        symbol: 股票代码
        df: 股票数据 DataFrame
    """
    global plus_list, minus_list, ratio_map
    
    if df is None or len(df) < 70:
        return
    
    # 计算指标
    ndf = calculate_macd_kdj(df)
    if ndf is None:
        return
    
    # 记录上一次买入的索引位置（冷却机制）
    last_buy_idx = -float('inf')
    
    # 遍历所有 K 线，寻找买入信号
    for idx in range(len(ndf)):
        # 检查是否在冷却期内
        if idx - last_buy_idx <= hold_days:
            continue
        
        # 检查买入信号
        if check_buy_signal(ndf, idx):
            buy_date = df['date'].iloc[idx]
            buy_idx = idx + 1  # 次日买入
            
            if buy_idx >= len(df):
                continue
            
            buy_price = float(df['open'].iloc[buy_idx])
            buy_date_next = df['date'].iloc[buy_idx]
            
            # 持有股票，寻找卖出信号
            max_val = -1000
            actual_hold_days = 0
            sell_found = False
            
            for day_offset in range(1, len(df) - buy_idx):
                sell_idx = buy_idx + day_offset
                if sell_idx >= len(df):
                    break
                
                # 最少持有 hold_days 天
                if day_offset >= hold_days:
                    # 检查卖出信号
                    if check_sell_signal(ndf, sell_idx):
                        sell_close = float(df['close'].iloc[sell_idx])
                        ratio = round(100 * (sell_close - buy_price) / (buy_price + 1e-10), 2)
                        max_val = ratio
                        actual_hold_days = day_offset
                        sell_found = True
                        
                        print("{} 买入日期：{} 买入价：{:.2f} 持有{}天 卖出收益：{:.2f}%".format(
                            symbol, buy_date_next, buy_price, actual_hold_days, max_val))
                        break
            
            # 如果直到最后都没找到卖出信号，则按最后一天计算
            if not sell_found:
                sell_idx = min(buy_idx + hold_days + 10, len(df) - 1)
                sell_close = float(df['close'].iloc[sell_idx])
                ratio = round(100 * (sell_close - buy_price) / (buy_price + 1e-10), 2)
                max_val = ratio
                actual_hold_days = sell_idx - buy_idx
                
                print("{} 买入日期：{} 买入价：{:.2f} 未出现卖点 持有{}日收益：{:.2f}%".format(
                    symbol, buy_date_next, buy_price, actual_hold_days, max_val))
            
            # 统计收益
            if max_val > -1000:
                stat_day = min(actual_hold_days, hold_days)
                if stat_day in ratio_map:
                    ratio_map[stat_day].append(max_val)
                
                if max_val > 0:
                    plus_list.append(max_val)
                else:
                    minus_list.append(max_val)
            
            # 更新最后一次买入的位置
            last_buy_idx = buy_idx


def print_console(title, arr):
    """打印统计信息"""
    if arr is None or len(arr) == 0:
        print("{}: 无数据".format(title))
        return
    
    arr = np.asarray(arr)
    print(title)
    print("    平均值：{:.2f}".format(np.mean(arr)))
    print("    最大值：{:.2f}".format(np.max(arr)))
    print("    最小值：{:.2f}".format(np.min(arr)))
    print("    50% 的百分位数：{:.2f}".format(np.percentile(arr, 50)))
    print("    95% 的百分位数：{:.2f}".format(np.percentile(arr, 95)))


def print_statistics(type_strategy="MACD_KDJ", symbol_count=None):
    """打印统计数据"""
    prefix = ""
    if symbol_count is not None:
        prefix = f"\n=== 已处理 {symbol_count} 个 symbol 的统计结果 ===\n"
    else:
        prefix = "\n=== 最终统计结果 ===\n"
    
    print(prefix)
    
    # 基本统计
    print("正收益次数：" + str(len(plus_list)))
    if len(minus_list) > 0 or len(plus_list):
        print("正收益占比：" + str(round(100 * len(plus_list) / (len(minus_list) + len(plus_list)), 2)) + "%")
    
    total = 0
    for x in range(0, len(plus_list)):
        total += plus_list[x]
    print("总的正收益：" + str(round(total, 2)))
    
    total = 0
    for x in range(0, len(minus_list)):
        total += minus_list[x]
    print("总的负收益：" + str(round(total, 2)))
    
    # 每天统计
    for x in range(1, hold_days + 1):
        print("第 {} 天：".format(x))
        res_list = ratio_map[x]
        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for idx in range(0, len(res_list)):
            ratio = res_list[idx]
            if ratio > 0:
                plus_num += 1
                plus_val += ratio
            else:
                minus_num += 1
                minus_val += ratio
        print("     正收益次数：" + str(plus_num))
        if plus_num > 0 or minus_num > 0:
            print("     正收益占比：" + str(round(100 * plus_num / (plus_num + minus_num), 2)) + "%")
        print("     总的正收益：" + str(round(plus_val, 2)))
        print("     总的负收益：" + str(round(minus_val, 2)))
    
    # 打印总体统计
    all_returns = plus_list + minus_list
    if len(all_returns) > 0:
        print_console('总收益：', all_returns)
    if len(plus_list):
        print_console('正收益：', plus_list)
    if len(minus_list) > 0:
        print_console('负收益：', minus_list)
    for x in range(1, hold_days + 1):
        if len(ratio_map[x]) > 0:
            print_console("第 {} 天：".format(x), ratio_map[x])


def main():
    """主函数：执行回测"""
    print("="*80)
    print("MACD + KDJ 组合策略 - 简化版回测")
    print("="*80)
    print("策略条件：")
    print("买入信号：")
    print("  1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0")
    print("  2. KDJ 超卖金叉：K < 30 且 K 上穿 D")
    print("卖出信号：")
    print("  1. MACD 趋势向下：DIF < DEA（死叉状态）")
    print("  2. KDJ 超买死叉：K > 80 且 K 下穿 D")
    print("="*80)
    
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    symbol_count = 0
    
    for i, symbol in enumerate(all_symbols):
        symbol_count += 1
        print("[{}] 进度：{} / {}".format(
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), 
            i + 1, len(all_symbols)))
        
        try:
            df = get_local_stock_data(symbol, start_date)
            get_macd_kdj_buy_point(symbol, df)
            
            # 每 100 个 symbol 打印一次统计数据
            if symbol_count % 100 == 0:
                print_statistics(symbol_count=symbol_count)
        
        except Exception as e:
            print(f"处理 {symbol} 时出错：{e}")
            continue
    
    # 输出最终统计结果
    print_statistics()


if __name__ == '__main__':
    main()
