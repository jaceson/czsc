# coding: utf-8
"""
通达信共振信号策略回测
参考 CZSCStragegy_Goldenline.py 模式实现

通达信公式：
    低位极值:=LLV(LOW,12);
    高位极值:=HHV(HIGH,12);
    动量比例:=(CLOSE-低位极值)/(高位极值-低位极值)*10;
    平滑一阶:=SMA(动量比例,3,2);
    平滑二阶:=SMA(平滑一阶,10,9);
    趋势稳态:=MA(平滑二阶,3);
    形态确认:=C>O AND C/O>1.040 AND C/O<1.057;
    突破确认:=CROSS(C,MA(C,10));
    趋势反转:=平滑二阶>=趋势稳态 AND NOT(REF(平滑二阶>=趋势稳态,1));
    高开企稳:=O/REF(C,1)>1.005 AND O/REF(C,1)<1.040;
    均线结构:=MA(C,5)<MA(C,10);
    价位安全区:=C*100>REF(HHV(H,5)*96,1) AND C*100<REF(HHV(H,5)*101,1);
    共振信号:形态确认 AND 突破确认 AND 趋势反转 AND 高开企稳 AND 均线结构 AND 价位安全区;

买入：信号出现后，第二天开盘价买入
卖出：持有 N 日（默认 5 日），按持有期内每日收盘价统计收益
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
    close = df['close'].values.astype(float)
    open_ = df['open'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)

    # 动量指标
    低位极值 = LLV(low, 12)
    高位极值 = HHV(high, 12)
    denom = 高位极值 - 低位极值
    safe_denom = np.where(denom != 0, denom, np.nan)
    动量比例 = (close - 低位极值) / safe_denom * 10
    平滑一阶 = SMA(动量比例, 3, 2)
    平滑二阶 = SMA(平滑一阶, 10, 9)
    趋势稳态 = MA(平滑二阶, 3)

    # 各子条件
    形态确认 = (close > open_) & (close / open_ > 1.040) & (close / open_ < 1.057)
    突破确认 = CROSS(close, MA(close, 10))
    趋势状态 = 平滑二阶 >= 趋势稳态
    趋势反转 = 趋势状态 & ~np.concatenate(([False], 趋势状态[:-1]))
    高开比例 = open_ / REF(close, 1)
    高开企稳 = (高开比例 > 1.005) & (高开比例 < 1.040)
    均线结构 = MA(close, 5) < MA(close, 10)
    前五日高 = REF(HHV(high, 5) * 96, 1)
    前五日高101 = REF(HHV(high, 5) * 101, 1)
    价位安全区 = (close * 100 > 前五日高) & (close * 100 < 前五日高101)

    condition = 形态确认 & 突破确认 & 趋势反转 & 高开企稳 & 均线结构 & 价位安全区
    return pd.Series(condition, index=df.index).fillna(False)


def backtest(symbol, df):
    if df is None or len(df) < 300:
        return

    condition = get_formula_condition(df)
    if not condition.any():
        return

    signal_indices = df[condition].index
    last_buy_idx = -1

    for idx in signal_indices:
        buy_idx = idx + 1
        if buy_idx >= len(df):
            continue

        if last_buy_idx >= 0 and (buy_idx - last_buy_idx) <= hold_days:
            continue

        sell_end = buy_idx + hold_days - 1
        if sell_end >= len(df):
            continue

        buy_price = float(df['open'].iloc[buy_idx])
        buy_date = df['date'].iloc[buy_idx]

        print(f"{symbol} 信号日期：{df['date'].iloc[idx]}，买入日期：{buy_date}，买入价格(开盘价)：{buy_price:.2f}")

        max_val = -1000.0
        last_buy_idx = buy_idx

        for day_offset in range(0, hold_days):
            sell_idx = buy_idx + day_offset
            stock_close = float(df['close'].iloc[sell_idx])
            ratio = round(100.0 * (stock_close - buy_price) / buy_price, 2)
            ratio_map[day_offset + 1].append(ratio)
            max_val = max(max_val, ratio)

        if max_val > 0:
            plus_list.append(max_val)
        else:
            minus_list.append(max_val)


def print_statistics(title, arr):
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
    print("\n" + "=" * 70)
    print("  共振信号策略（信号次日开盘买入|持有5日） 统计结果")
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
        print_statistics("\n总收益（持有期内最大收益）：", all_returns)
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

        print(f"\n第 {x} 天（买入后第{x}个交易日收盘）：")
        print(f"    正收益次数：{plus_num}")
        if plus_num + minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(sum(r for r in res_list if r > 0), 2)}")
        print(f"    总的负收益：{round(sum(r for r in res_list if r <= 0), 2)}")
        print_statistics(f"    第 {x} 天统计：", res_list)


if __name__ == '__main__':
    start_date = "2020-01-01"
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