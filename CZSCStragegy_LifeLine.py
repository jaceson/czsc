# coding: utf-8
"""
生命线策略（通达信公式对应）
公式要点：
  VAR12-VAR13>0 红柱，<0 绿柱；生命线=EMA(VAR13,5)；
  买：VAR13 上穿 VAR12 且 VAR12<VAR13 且 VAR12>60 时发出；
  卖：VAR12 上穿 VAR13 且 VAR12>VAR13 且 VAR12<18 时发出。
策略逻辑：出现「买」信号次日开盘买入，持有 hold_days 日后统计收益。
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import (
    REF, EMA, SMA, HHV, LLV, MAX, MIN, ABS,
)
from czsc_daily_util import get_daily_symbols
from czsc_sqlite import get_local_stock_data

# 统计变量
plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []


def _if(cond, a, b):
    """IF(cond,a,b) 逐元素"""
    return np.where(cond, a, b)


def _cross_up(a, b):
    """上穿：前一根 a<=b，当前 a>b"""
    ra = REF(np.asarray(a), 1)
    rb = REF(np.asarray(b), 1)
    return (~np.isnan(ra)) & (~np.isnan(rb)) & (ra <= rb) & (np.asarray(a) > np.asarray(b))


def calculate_lifeline_indicators(df):
    """
    计算生命线公式全部中间变量与输出
    要求 df 含列: high, low, close
    返回的 df 增加列: VAR1..VAR13, 生命线, 买, 卖, COLORRED, COLOR00FF0F 等
    """
    if df is None or len(df) < 70:
        return None
    ndf = df.copy()
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)

    # VAR1:=HHV(HIGH,9)-LLV(LOW,9);
    VAR1 = HHV(H, 9) - LLV(L, 9)
    VAR1 = np.where(VAR1 <= 0, np.nan, VAR1)

    # VAR2:=HHV(HIGH,9)-CLOSE;
    VAR2 = HHV(H, 9) - C

    # VAR3:=CLOSE-LLV(LOW,9);
    VAR3 = C - LLV(L, 9)

    # VAR4:=VAR2/VAR1*100-70;
    VAR4 = VAR2 / VAR1 * 100 - 70

    # VAR5:=(CLOSE-LLV(LOW,60))/(HHV(HIGH,60)-LLV(LOW,60))*100;
    h60 = HHV(H, 60)
    l60 = LLV(L, 60)
    VAR5 = (C - l60) / (np.where(h60 - l60 <= 0, np.nan, h60 - l60) + 1e-10) * 100

    # VAR6:=(2*CLOSE+HIGH+LOW)/4;
    VAR6 = (2 * C + H + L) / 4

    # VAR7:=SMA(VAR3/VAR1*100,3,1);
    VAR7 = SMA((VAR3 / VAR1 * 100), 3, 1)

    # VAR8:=LLV(LOW,34);
    VAR8 = LLV(L, 34)

    # VAR9:=SMA(VAR7,3,1)-SMA(VAR4,9,1);
    VAR9 = SMA(VAR7, 3, 1) - SMA(VAR4, 9, 1)

    # VAR10:=IF(VAR9>100,VAR9-100,0);
    VAR10 = _if(VAR9 > 100, VAR9 - 100, 0)

    # VAR11:=HHV(HIGH,34);
    VAR11 = HHV(H, 34)

    # VAR12:=EMA((VAR6-VAR8)/(VAR11-VAR8)*100,13);
    den12 = VAR11 - VAR8
    den12 = np.where(den12 <= 0, np.nan, den12)
    VAR12 = EMA((VAR6 - VAR8) / (den12 + 1e-10) * 100, 13)

    # VAR13:=EMA(0.667*REF(VAR12,1)+0.333*VAR12,2);
    VAR13 = EMA(0.667 * REF(VAR12, 1) + 0.333 * VAR12, 2)

    ndf["VAR1"] = VAR1
    ndf["VAR2"] = VAR2
    ndf["VAR3"] = VAR3
    ndf["VAR4"] = VAR4
    ndf["VAR5"] = VAR5
    ndf["VAR6"] = VAR6
    ndf["VAR7"] = VAR7
    ndf["VAR8"] = VAR8
    ndf["VAR9"] = VAR9
    ndf["VAR10"] = VAR10
    ndf["VAR11"] = VAR11
    ndf["VAR12"] = VAR12
    ndf["VAR13"] = VAR13

    # STICKLINE(VAR12-VAR13>0,VAR12,VAR13,5,0), COLORRED;
    # STICKLINE(VAR12-VAR13<0,VAR12,VAR13,5,0), COLOR00FF0F;
    COLORRED = (VAR12 - VAR13) > 0
    COLOR00FF0F = (VAR12 - VAR13) < 0
    ndf["COLORRED"] = COLORRED
    ndf["COLOR00FF0F"] = COLOR00FF0F
    ndf["COLORRED_TOP"] = np.where(COLORRED, VAR12, np.nan)
    ndf["COLORRED_BOTTOM"] = np.where(COLORRED, VAR13, np.nan)
    ndf["COLOR00FF0F_TOP"] = np.where(COLOR00FF0F, VAR12, np.nan)
    ndf["COLOR00FF0F_BOTTOM"] = np.where(COLOR00FF0F, VAR13, np.nan)

    # 生命线: EMA(VAR13,5), COLORYELLOW;
    生命线 = EMA(VAR13, 5)
    ndf["生命线"] = 生命线

    # 买: IF(CROSS(VAR13,VAR12) AND VAR12<VAR13 AND VAR12>60, VAR13, 88);
    cross_buy = _cross_up(VAR13, VAR12)
    cond_buy = cross_buy & (VAR12 < VAR13) & (VAR12 > 60)
    买 = _if(cond_buy, VAR13, 88)
    ndf["买"] = 买
    ndf["买信号"] = cond_buy

    # 卖: IF(CROSS(VAR12,VAR13) AND VAR12>VAR13 AND VAR12<18, 38, 18);
    cross_sell = _cross_up(VAR12, VAR13)
    cond_sell = cross_sell & (VAR12 > VAR13) & (VAR12 < 18)
    卖 = _if(cond_sell, 38, 18)
    ndf["卖"] = 卖
    ndf["卖信号"] = cond_sell

    return ndf


def get_lifeline_buy_condition(symbol, df, min_bars=70):
    """
    得到「买」信号条件序列：当日出现买信号，次日开盘可买入。
    返回与 df 同索引的 bool Series。
    """
    if df is None or len(df) < min_bars:
        return pd.Series([False] * len(df), index=df.index if df is not None else None)
    ndf = calculate_lifeline_indicators(df)
    if ndf is None:
        return pd.Series([False] * len(df), index=df.index)
    return ndf["买信号"].fillna(False)


def get_lifeline_buy_point(symbol, df):
    """
    生命线策略买入点：出现「买」信号次日开盘买入，持有 hold_days 日统计收益。
    """
    global plus_list, minus_list, ratio_map
    if df is None or len(df) < 70:
        return
    ndf = calculate_lifeline_indicators(df)
    if ndf is None:
        return
    buy_signal = ndf["买信号"].fillna(False)
    if not buy_signal.any():
        return

    for idx in np.where(buy_signal)[0]:
        buy_date = df["date"].iloc[idx]
        buy_idx = idx + 1
        if buy_idx >= len(df):
            continue
        buy_price = float(df["open"].iloc[buy_idx])
        buy_date_next = df["date"].iloc[buy_idx]

        max_val = -1000
        for day_offset in range(1, hold_days + 1):
            sell_idx = buy_idx + day_offset
            if sell_idx >= len(df):
                break
            sell_close = float(df["close"].iloc[sell_idx])
            ratio = round(100 * (sell_close - buy_price) / (buy_price + 1e-10), 2)
            ratio_map[day_offset].append(ratio)
            max_val = max(max_val, ratio)

        if max_val > 0:
            plus_list.append(max_val)
        else:
            minus_list.append(max_val)
        print("{} 买信号日期: {} 买入日期: {} 买入价: {:.2f} 持有{}日内最大收益: {:.2f}%".format(
            symbol, buy_date, buy_date_next, buy_price, hold_days, max_val))


def print_console(title, arr):
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


def print_statistics():
    global plus_list, minus_list, ratio_map
    print("=" * 60)
    print("生命线策略统计结果")
    print("=" * 60)
    print("正收益次数：{}".format(len(plus_list)))
    total = len(plus_list) + len(minus_list)
    if total > 0:
        print("正收益占比：{:.2f}%".format(100 * len(plus_list) / total))
    if plus_list:
        print("总的正收益：{:.2f}".format(sum(plus_list)))
    if minus_list:
        print("总的负收益：{:.2f}".format(sum(minus_list)))
    for x in range(1, hold_days + 1):
        print("第 {} 天：".format(x))
        res_list = ratio_map[x]
        if not res_list:
            print("     无数据")
            continue
        plus_num = sum(1 for r in res_list if r > 0)
        print("     正收益次数：{}".format(plus_num))
        if res_list:
            print("     正收益占比：{:.2f}%".format(100 * plus_num / len(res_list)))
        print("     总的正收益：{:.2f}".format(sum(r for r in res_list if r > 0)))
        print("     总的负收益：{:.2f}".format(sum(r for r in res_list if r <= 0)))
        print_console("     第{}天收益统计：".format(x), res_list)
    if plus_list:
        print_console("正收益：", plus_list)
    if minus_list:
        print_console("负收益：", minus_list)
    print("=" * 60)


if __name__ == "__main__":
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    for i, symbol in enumerate(all_symbols):
        if (i + 1) % 100 == 0 or total <= 50:
            print("[{}] 进度：{} / {}".format(
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            df = get_local_stock_data(symbol, start_date)
            get_lifeline_buy_point(symbol, df)
        except Exception as e:
            continue
    print_statistics()

'''
通达信公式：生命线策略
VAR1:=HHV(HIGH,9)-LLV(LOW,9);
VAR2:=HHV(HIGH,9)-CLOSE;
VAR3:=CLOSE-LLV(LOW,9);
VAR4:=VAR2/VAR1*100-70;
VAR5:=(CLOSE-LLV(LOW,60))/(HHV(HIGH,60)-LLV(LOW,60))*100;
VAR6:=(2*CLOSE+HIGH+LOW)/4;
VAR7:=SMA(VAR3/VAR1*100,3,1);
VAR8:=LLV(LOW,34);
VAR9:=SMA(VAR7,3,1)-SMA(VAR4,9,1);
VAR10:=IF(VAR9>100,VAR9-100,0);
VAR11:=HHV(HIGH,34);
VAR12:=EMA((VAR6-VAR8)/(VAR11-VAR8)*100,13);
VAR13:=EMA(0.667*REF(VAR12,1)+0.333*VAR12,2);
STICKLINE(VAR12-VAR13>0,VAR12,VAR13,5,0),    COLORRED;
STICKLINE(VAR12-VAR13<0,VAR12,VAR13,5,0),COLOR00FF0F;
生命线:EMA(VAR13,5), COLORYELLOW;
买:IF(CROSS(VAR13,VAR12) AND VAR12<VAR13 AND VAR12>60,VAR13,88), COLORRED ;
卖:IF(CROSS(VAR12,VAR13) AND VAR12>VAR13 AND VAR12<18,38,18),  COLORGREEN;
'''