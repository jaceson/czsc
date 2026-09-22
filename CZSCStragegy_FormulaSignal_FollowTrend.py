# coding: utf-8
"""
通达信公式策略回测 — 顺势上车

公式来源：顺势上车选股公式
核心信号：
  顺势上车: 首次突破成本+均线多头+回踩MA10+收盘站上MA5

策略逻辑：出现买入信号次日开盘买入，持有 hold_days 日后收盘卖出。
"""
import pandas as pd
import numpy as np
import baostock as bs
from lib.MyTT import (
    REF, EMA, SMA, HHV, LLV, MAX, MIN, ABS, MA, SUM,
    BARSLAST, BARSLASTCOUNT, BETWEEN, COUNT, FILTER,
    TOPRANGE, LOWRANGE, CROSS, IF, STD, DMA,
)
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 10

SIGNAL_KEYS = ["顺势上车"]


def _new_stats():
    return {
        "plus": [],
        "minus": [],
        "ratio_map": {x: [] for x in range(1, hold_days + 1)},
        "count": 0,
        "symbols": [],
        "pyramid_counts": [],
        "hold_days_list": [],
    }


signal_stats = {k: _new_stats() for k in SIGNAL_KEYS}


# ============================================================
# Indicator calculation
# ============================================================

def calculate_indicators(df):
    """
    计算顺势上车公式全部中间变量与输出。
    要求 df 含列: open, high, low, close, volume, amount
    """
    if df is None or len(df) < 60:
        return None
    ndf = df.copy()
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)
    O = ndf["open"].values.astype(float)
    V = ndf["volume"].values.astype(float)
    AMOUNT = ndf["amount"].values.astype(float)

    # VAR1 := CLOSE
    VAR1 = C

    # 计划均线: VAR2:=(EMA(VAR1,5)*7+EMA(VAR1,10)*3)/10
    VAR2 = (EMA(VAR1, 5) * 7 + EMA(VAR1, 10) * 3) / 10

    # VAR6 := (C*3+H+L+O)/6
    VAR6 = (C * 3 + H + L + O) / 6

    # VAR7/VAR8/VAR9: MACD变体
    VAR7 = EMA(VAR6, 13) - EMA(VAR6, 21)

    # VAR10/VAR11/VAR12: 趋势线
    VAR10 = EMA(VAR1, 7) - EMA(VAR1, 21)
    VAR11 = EMA(0.668 * REF(VAR10, 1) + 0.333 * VAR10, 1)

    # VAR15: 价格偏离DMA成本
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR13 = V / SUM(V, 13)
    VAR14 = DMA(VAR1, np.clip(np.where(np.abs(VAR13) > 1e-10, VAR13, 0), 0, 1))
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR15 = np.where(np.abs(VAR14) > 1e-10, (VAR1 - VAR14) / VAR14 * 40, 0)

    # VAR17: 价格偏离平均成本
    # 注意: 本地volume单位为股(shares)，TDX公式AMOUNT/(100*V)针对手(1手=100股)，
    #       故此处直接用 AMOUNT/V 得到每股均价
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR16 = MA(np.where(V > 1e-10, AMOUNT / V, C), 13)
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR17 = np.where(np.abs(VAR16) > 1e-10, (C - VAR16) / VAR16 * 100, 0)

    # VAR20/VAR22
    VAR20 = np.where(VAR10 >= VAR11, VAR10, VAR11)
    VAR22 = (VAR15 > 0) & (VAR20 > 0)

    # VAR23 := VAR17>5
    VAR23 = VAR17 > 5

    # MA均线
    MA5 = MA(VAR1, 5)
    MA10 = MA(VAR1, 10)

    # 顺势上车:
    # BARSLASTCOUNT(VAR23)=1 AND MA(VAR1,5)>MA(VAR1,10) AND L<MA(VAR1,10) AND VAR1>MA(VAR1,5)
    signal = np.where(
        (BARSLASTCOUNT(VAR23) == 1) &
        (MA5 > MA10) &
        (L < MA10) &
        (VAR1 > MA5),
        1, 0)

    ndf["顺势上车"] = signal
    ndf["MA5"] = MA5
    ndf["MA10"] = MA10

    return ndf


# ============================================================
# Backtesting engine
# ============================================================

def get_buy_point(symbol, df):
    if df is None or len(df) < 60:
        return
    ndf = calculate_indicators(df)
    if ndf is None:
        return

    signal = ndf["顺势上车"].values
    buy_signal = signal == 1

    if not buy_signal.any():
        return

    all_dates = ndf["date"].values
    all_open = ndf["open"].values.astype(float)
    all_close = ndf["close"].values.astype(float)
    n = len(ndf)

    stats = signal_stats["顺势上车"]

    def _record_exit(entry_idx, entry_price, exit_idx):
        exit_price = all_open[exit_idx]
        ret = (exit_price - entry_price) / entry_price * 100

        (stats["plus"] if ret > 0 else stats["minus"]).append(ret)
        stats["count"] += 1
        stats["symbols"].append(symbol)
        stats["hold_days_list"].append(exit_idx - entry_idx)
        return exit_price, ret

    for idx in np.where(buy_signal)[0]:
        if idx + 1 >= n:
            continue

        entry_idx = idx + 1
        entry_price = all_open[entry_idx]
        max_ret = -1000.0

        exit_idx = None
        reason = None

        for day_offset in range(1, hold_days + 1):
            check_idx = entry_idx + day_offset
            if check_idx >= n:
                break
            check_close = float(df["close"].iloc[check_idx])
            ratio = round(100 * (check_close - entry_price) / (entry_price + 1e-10), 2)
            stats["ratio_map"][day_offset].append(ratio)
            max_ret = max(max_ret, ratio)

            # 止盈/止损: 按当日收盘价判断，次日开盘卖出
            if ratio > 5.0:
                exit_idx = check_idx + 1 if check_idx + 1 < n else n - 1
                reason = "止盈"
                break
            elif ratio < -5.0:
                exit_idx = check_idx + 1 if check_idx + 1 < n else n - 1
                reason = "止损"
                break

        # 未触发止盈止损，持有期满按收盘平仓
        if exit_idx is None:
            exit_idx = entry_idx + hold_days
            if exit_idx >= n:
                exit_idx = n - 1
            reason = "平仓"
            day_offset = exit_idx - entry_idx
            if day_offset > 0:
                check_close = float(df["close"].iloc[exit_idx])
                ratio = round(100 * (check_close - entry_price) / (entry_price + 1e-10), 2)
                stats["ratio_map"][day_offset].append(ratio)
                max_ret = max(max_ret, ratio)

        exit_price, ret = _record_exit(entry_idx, entry_price, exit_idx)

        print("{} 买 信号日:{} 买入:{} 价:{:.2f} {} 卖出:{} 价:{:.2f} 收益:{:.2f}% 持有最高:{:.2f}%".format(
            symbol, all_dates[idx], all_dates[entry_idx], entry_price, reason,
            all_dates[exit_idx], exit_price, ret, max_ret))


# ============================================================
# Statistics printing
# ============================================================

def _print_signal_header(label):
    print()
    print("=" * 70)
    print("  【{}】".format(label))
    print("=" * 70)


def _print_signal_stats(label, stats):
    plus = stats["plus"]
    minus = stats["minus"]
    total = len(plus) + len(minus)

    if total == 0:
        print("  无交易信号\n")
        return

    print("  交易次数：{}".format(total))
    print("  正收益次数：{}  负收益次数：{}".format(len(plus), len(minus)))
    print("  正收益占比：{:.2f}%".format(100 * len(plus) / total) if total else "  正收益占比：N/A")

    all_returns = np.array(plus + minus)
    print("  平均收益：{:.2f}%".format(np.mean(all_returns)))
    print("  总的正收益：{:.2f}%  正收益均值：{:.2f}%".format(sum(plus), np.mean(plus) if plus else 0))
    print("  总的负收益：{:.2f}%  负收益均值：{:.2f}%".format(sum(minus), np.mean(minus) if minus else 0))
    print("  最大收益：{:.2f}%  最小收益：{:.2f}%".format(
        np.max(all_returns) if len(all_returns) else 0,
        np.min(all_returns) if len(all_returns) else 0,
    ))
    print("  中位数收益：{:.2f}%".format(np.median(all_returns)))
    print("  95% 分位数：{:.2f}%".format(np.percentile(all_returns, 95)))
    print("  5% 分位数：{:.2f}%".format(np.percentile(all_returns, 5)))

    print()
    total_symbols = len(set(stats["symbols"]))
    print("  涉及股票数：{}".format(total_symbols))

    if stats["hold_days_list"]:
        hd = np.array(stats["hold_days_list"])
        print("  持有天数: 最大={:.0f}  最小={:.0f}  平均={:.1f}".format(
            np.max(hd), np.min(hd), np.mean(hd)))

    print()
    print("  --- 逐日收益 ---")
    for x in range(1, hold_days + 1):
        day_ret = np.array(stats["ratio_map"][x])
        if len(day_ret) == 0:
            continue
        day_plus = np.sum(day_ret > 0)
        print("  第{}天  | 均值:{:>7.2f}%  中位:{:>7.2f}%  胜率:{:>5.1f}%  总正:{:>8.2f}  总负:{:>8.2f}".format(
            x, np.mean(day_ret), np.median(day_ret),
            100 * day_plus / len(day_ret),
            np.sum(day_ret[day_ret > 0]),
            np.sum(day_ret[day_ret <= 0]),
        ))


def print_statistics():
    print("=" * 70)
    print("  顺势上车策略 — 统计结果")
    print("=" * 70)

    for key in SIGNAL_KEYS:
        _print_signal_header(key)
        _print_signal_stats(key, signal_stats[key])


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    test_symbols = []
    start_date = "2026-01-01"
    end_date = "2026-09-01"
    all_symbols = get_daily_symbols()
    test_symbols = read_json("./data/超跌反弹.json")
    total = len(all_symbols)
    if len(test_symbols) > 0:
        bs.login()
        end_date = get_latest_trade_date()

    for i, symbol in enumerate(all_symbols):
        if len(test_symbols) > 0:
            if symbol not in test_symbols:
                continue

        print("[{}] 进度：{} / {}".format(
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            if len(test_symbols) > 0:
                df = get_stock_pd(symbol, start_date, end_date, "d")
            else:
                df = get_local_stock_data(symbol, start_date)
            get_buy_point(symbol, df)
        except Exception as e:
            continue
        if (i + 1) % 100 == 0:
            print_statistics()
    print_statistics()

    if len(test_symbols) > 0:
        bs.logout()
