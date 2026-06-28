# coding: utf-8
"""
成交量异动策略 — 基于缠论笔结构

策略逻辑：
1. 使用缠论输出笔数据，找到下降笔的最低点及对应成交量
2. 当天收阴线（close < open），且成交量接近最近的下降笔最低点成交量的1倍或2倍
3. 统计第二天收阳线的占比
"""
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs
import numpy as np
from czsc_sqlite import get_local_stock_data

stats = {
    "1x": {"total": 0, "up": 0, "ratios": []},
    "2x": {"total": 0, "up": 0, "ratios": []},
    "all": {"total": 0, "up": 0, "ratios": []},
}


def analyze(symbol, df):
    if df is None or len(df) < 60:
        return

    bars = get_stock_bars(symbol=symbol, df=df)
    c = CZSC(bars, get_signals=None)
    bi_list = c.bi_list
    if len(bi_list) < 3:
        return

    date_to_idx = {d: i for i, d in enumerate(df['date'])}
    last_di = 100000
    down_pts = []
    for bi in bi_list:
        if bi.direction == Direction.Down:
            if bi.fx_b.fx > last_di:
                last_di = bi.fx_b.fx
                continue
            last_di = bi.fx_b.fx
            d = bi.fx_b.dt.strftime("%Y-%m-%d")
            if d in date_to_idx:
                idx = date_to_idx[d]
                down_pts.append((idx, float(df['volume'].iloc[idx])))

    if not down_pts:
        return
    down_pts.sort(key=lambda x: x[0])

    last_di = -1
    last_dv = 0.0

    for idx in range(len(df)):
        while last_di + 1 < len(down_pts) and down_pts[last_di + 1][0] <= idx:
            last_di += 1
            last_dv = down_pts[last_di][1]

        if last_di < 0 or last_dv <= 0:
            continue

        if float(df['close'].iloc[idx]) >= float(df['open'].iloc[idx]):
            continue

        # 排除最低点当天及次日的信号
        if idx - down_pts[last_di][0] <= 1:
            continue

        cur_date = df['date'].iloc[idx]
        cur_vol = float(df['volume'].iloc[idx])
        vr = cur_vol / last_dv

        is_1x = 0.8 <= vr <= 1.2
        is_2x = 1.8 <= vr <= 2.2
        if not (is_1x or is_2x):
            continue

        next_up = False
        next_r = 0.0
        if idx + 1 < len(df):
            nc = float(df['close'].iloc[idx + 1])
            no = float(df['open'].iloc[idx + 1])
            next_up = nc > no
            next_r = round(100 * (nc - no) / no, 2)

        tag = "1x" if is_1x else "2x"
        ref_date = df['date'].iloc[down_pts[last_di][0]]
        print(f"{symbol} {cur_date} 阴线 量比:{vr:.2f}x({tag}) "
              f"参考低点:{ref_date}({last_dv:.0f}) "
              f"次日{'阳线' if next_up else '阴线'}({next_r:.2f}%)")

        stats["all"]["total"] += 1
        if next_up:
            stats["all"]["up"] += 1
        stats["all"]["ratios"].append(next_r)

        if is_1x:
            stats["1x"]["total"] += 1
            if next_up:
                stats["1x"]["up"] += 1
            stats["1x"]["ratios"].append(next_r)

        if is_2x:
            stats["2x"]["total"] += 1
            if next_up:
                stats["2x"]["up"] += 1
            stats["2x"]["ratios"].append(next_r)


def print_stats():
    print("\n" + "=" * 70)
    print("  成交量异动策略（基于缠论笔结构）— 统计结果")
    print("=" * 70)

    for key, label in [("1x", "成交量≈1倍"), ("2x", "成交量≈2倍"), ("all", "合计")]:
        s = stats[key]
        if s["total"] == 0:
            print(f"\n  【{label}】无交易信号")
            continue

        up_pct = round(100 * s["up"] / s["total"], 2)
        ratios = s["ratios"]

        print(f"\n  【{label}】")
        print(f"  信号次数：{s['total']}")
        print(f"  次日收阳线次数：{s['up']}")
        print(f"  次日收阳线占比：{up_pct}%")
        if ratios:
            print(f"  次日平均涨幅：{np.mean(ratios):.2f}%")
            print(f"  次日最大涨幅：{np.max(ratios):.2f}%")
            print(f"  次日最小涨幅：{np.min(ratios):.2f}%")
            pos = [r for r in ratios if r > 0]
            neg = [r for r in ratios if r <= 0]
            if pos:
                print(f"  次日正收益均值：{np.mean(pos):.2f}%")
            if neg:
                print(f"  次日负收益均值：{np.mean(neg):.2f}%")


if __name__ == "__main__":
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)

    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] {i + 1}/{total}")
        try:
            df = get_local_stock_data(symbol, start_date)
            if df is not None and len(df) > 60:
                analyze(symbol, df)
        except Exception:
            continue
        if (i + 1) % 100 == 0:
            print_stats()

    print_stats()
