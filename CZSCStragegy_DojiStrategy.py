# coding: utf-8
"""
十字星+连续大涨+一年新高策略
通达信公式策略回测

选股条件（通达信公式）：
    实体:=ABS(CLOSE-OPEN);
    振幅:=HIGH-LOW;
    十字星:=实体/振幅<0.2 AND 振幅>0;
    涨幅:=(REF(CLOSE,1)-REF(CLOSE,2))/REF(CLOSE,2);
    连续三天大涨:=EVERY(涨幅>0.03,3);
    一年新高:=REF(CLOSE,1)>=HHV(CLOSE,252);
    选股:十字星 AND 连续三天大涨 AND 一年新高;

买入：信号当日收盘价买入
持有：hold_days 天，统计每日收益
"""
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import numpy as np
from czsc_sqlite import get_local_stock_data

plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []


def get_formula_condition(df):
    """
    计算公式选股条件

    Returns:
        pd.Series: 布尔序列，True 表示满足选股条件
    """
    close = df['close'].values.astype(float)
    open_ = df['open'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)

    body = ABS(close - open_)
    amplitude = high - low
    doji = (body / (amplitude + 1e-10) < 0.2) & (amplitude > 0)

    gain = (REF(close, 1) - REF(close, 2)) / (REF(close, 2) + 1e-10)
    three_up = EVERY(gain > 0.03, 3)

    new_high = REF(close, 1) >= HHV(close, 252)

    condition = doji & three_up & new_high
    return pd.Series(condition, index=df.index)


def backtest(symbol, df):
    """对单只股票进行回测"""
    if df is None or len(df) < 300:
        return

    condition = get_formula_condition(df)
    if not condition.any():
        return

    signal_indices = df[condition].index
    last_buy_idx = -1

    for idx in signal_indices:
        if last_buy_idx > 0 and (idx - last_buy_idx) <= hold_days:
            continue

        if idx + hold_days >= len(df):
            continue

        buy_price = float(df['close'].iloc[idx])
        buy_date = df['date'].iloc[idx]

        print(f"{symbol} 信号日期：{buy_date}，买入价格：{buy_price:.2f}")

        max_val = -1000.0
        last_buy_idx = idx

        for day_offset in range(1, hold_days + 1):
            sell_idx = idx + day_offset
            if sell_idx < len(df):
                stock_close = float(df['close'].iloc[sell_idx])
                ratio = round(100.0 * (stock_close - buy_price) / buy_price, 2)
                ratio_map[day_offset].append(ratio)
                max_val = max(max_val, ratio)

        if max_val > 0:
            plus_list.append(max_val)
        else:
            minus_list.append(max_val)


def print_statistics(title, arr):
    """打印统计信息"""
    if len(arr) == 0:
        print(f"{title}: 无数据")
        return

    average = np.mean(arr)
    max_value = np.max(arr)
    min_value = np.min(arr)
    p50 = np.percentile(arr, 50)
    p95 = np.percentile(arr, 95)

    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 百分位：{p50:.2f}")
    print(f"    95% 百分位：{p95:.2f}")


def print_console():
    """打印最终统计结果"""
    print("\n" + "=" * 70)
    print("  十字星+连续大涨+一年新高策略  统计结果")
    print("=" * 70)

    total_trades = len(plus_list) + len(minus_list)
    print(f"\n总交易次数：{total_trades}")
    print(f"正收益次数：{len(plus_list)}")

    if total_trades > 0:
        win_rate = round(100 * len(plus_list) / total_trades, 2)
        print(f"正收益占比：{win_rate}%")

    total_plus = sum(plus_list) if plus_list else 0
    total_minus = sum(minus_list) if minus_list else 0
    print(f"总的正收益：{total_plus:.2f}")
    print(f"总的负收益：{total_minus:.2f}")

    all_returns = plus_list + minus_list
    if all_returns:
        print_statistics("\n总收益：", all_returns)
    if plus_list:
        print_statistics("正收益：", plus_list)
    if minus_list:
        print_statistics("负收益：", minus_list)

    for x in range(1, hold_days + 1):
        res_list = ratio_map[x]
        if not res_list:
            continue

        plus_num = sum(1 for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)

        print(f"\n第 {x} 天：")
        print(f"    正收益次数：{plus_num}")
        if plus_num + minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(sum(r for r in res_list if r > 0), 2)}")
        print(f"    总的负收益：{round(sum(r for r in res_list if r <= 0), 2)}")
        print_statistics(f"    第 {x} 天统计：", res_list)


if __name__ == '__main__':
    start_date = "2015-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    print(f"共 {total} 只股票，开始回测...")

    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] {i + 1}/{total} {symbol}")
        try:
            df = get_local_stock_data(symbol, start_date)
            backtest(symbol, df)
        except Exception as e:
            print(f"处理 {symbol} 出错：{e}")
            import traceback
            traceback.print_exc()
            continue

        if (i + 1) % 100 == 0:
            print_console()

    print_console()
