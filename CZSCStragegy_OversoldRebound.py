# coding: utf-8
"""
超跌反弹策略（通达信公式对应）

公式来源：综合超跌反弹指标
核心买信号：
  1. CTD6: 超跌反弹主信号 — 股价深跌、筹码套牢、近期有异动
  2. XL3: 低位拐头信号 — 短期低点均线在长期支撑下方企稳

策略逻辑：出现 XL3 OR CTD6「买」信号次日开盘买入，持有 hold_days 日后统计收益。

主流程（优化后）：
  1. 多进程并行扫描全市场，输出最后一个交易日出现信号的股票
     （含 BCD1 值乘以 50 的通达信柱高值），并保存到 JSON。
  2. 串行执行完整历史回测并输出分信号类型统计。
"""
import os
import pandas as pd
import numpy as np
import baostock as bs
from concurrent.futures import ProcessPoolExecutor
from numpy.lib.stride_tricks import sliding_window_view
from lib.MyTT import (
    REF, EMA, SMA, HHV, LLV, MAX, MIN, ABS, MA, SUM, DMA,
    FORCAST, BETWEEN, COUNT, FILTER,
)
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 10

SIGNAL_KEYS = ["XL3", "CTD6", "XL3+CTD6", "启动点", "见底"]


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

# 最后一个交易日出现信号的股票列表（元素为 _extract_last_day_signal 的返回值）
last_day_signals = []


def _ref_frac(S, N):
    """Fractional REF: linear interpolation for non-integer N"""
    n_int = int(N)
    frac = N - n_int
    s1 = REF(S, n_int)
    s2 = REF(S, n_int + 1)
    return np.where(np.isnan(s2), s1, s1 * (1 - frac) + s2 * frac)


def _smooth_capital(volume, turn, window=20):
    """Smooth CAPITAL estimate from daily volume and turnover rate"""
    cap_raw = np.where(turn > 1e-10, volume * 100.0 / turn, np.nan)
    cap_filled = np.where(np.isnan(cap_raw), np.nanmedian(cap_raw), cap_raw)
    return EMA(cap_filled, window)


def _calc_distribution_metrics(close, lookback=60):
    """
    基于收盘价分布近似 WINNER/COST，完全向量化。
      - winner_high: 过去 lookback 日中收盘价 ≤ 1.1*C 的比例 (≈WINNER(1.1*C))
      - winner_low:  过去 lookback 日中收盘价 ≤ 0.9*C 的比例 (≈WINNER(0.9*C))
      - cost20:      过去 lookback 日收盘价的第20百分位 (≈COST(20))
    """
    n = len(close)
    winner_high = np.full(n, np.nan)
    winner_low = np.full(n, np.nan)
    cost20 = np.full(n, np.nan)

    if n <= lookback:
        return winner_high, winner_low, cost20

    windows = sliding_window_view(close, lookback)[:n - lookback]
    current = close[lookback:]

    winner_high[lookback:] = np.mean(windows <= (current * 1.1)[:, None], axis=1)
    winner_low[lookback:] = np.mean(windows <= (current * 0.9)[:, None], axis=1)
    cost20[lookback:] = np.percentile(windows, 20, axis=1)

    return winner_high, winner_low, cost20


def calculate_oversold_indicators(df):
    """
    计算超跌反弹公式全部中间变量与输出
    要求 df 含列: open, high, low, close, volume, amount, turn
    """
    if df is None or len(df) < 120:
        return None
    ndf = df.copy()
    O = ndf["open"].values.astype(float)
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)
    V = ndf["volume"].values.astype(float)
    AMOUNT = ndf["amount"].values.astype(float)
    TURN = ndf["turn"].values.astype(float)

    CAPITAL = _smooth_capital(V, TURN, 20)

    # RS := SMA(MAX(C-REF(C,1),0),14,1)/SMA(ABS(C-REF(C,1)),14,1)*100
    with np.errstate(divide='ignore', invalid='ignore'):
        RS = SMA(MAX(C - REF(C, 1), 0), 14, 1) / SMA(ABS(C - REF(C, 1)), 14, 1) * 100
    ndf["RS"] = RS

    # BCD := EMA(EMA(EMA(RS,7),3),3)
    BCD = EMA(EMA(EMA(RS, 7), 3), 3)
    ndf["BCD"] = BCD

    # BCD1 := (BCD-REF(BCD,1))/REF(BCD,1)*15
    BCD_REF1 = REF(BCD, 1)
    with np.errstate(divide='ignore', invalid='ignore'):
        BCD1 = np.where(np.abs(BCD_REF1) > 1e-10, (BCD - BCD_REF1) / BCD_REF1 * 15, 0)
    ndf["BCD1"] = BCD1

    # Y1 := AMOUNT/V/100
    Y1 = np.where(V > 1e-10, AMOUNT / V / 100, C / 100)
    ndf["Y1"] = Y1

    # Y2 := (3*H+L+O+2*C)/7
    Y2 = (3 * H + L + O + 2 * C) / 7
    ndf["Y2"] = Y2

    # Y3 := 100*(WINNER(1.1*C)-WINNER(0.9*C))
    winner_high, winner_low, cost20_val = _calc_distribution_metrics(C)
    Y3 = 100 * (winner_high - winner_low)
    ndf["Y3"] = Y3

    # Y4 := SUM(AMOUNT,13)/Y1/100
    Y4 = SUM(AMOUNT, 13) / np.where(np.abs(Y1) > 1e-10, Y1, 1e-10) / 100
    ndf["Y4"] = Y4

    # Y5 := DMA(Y2, V/Y4)
    alpha_y5 = np.where(np.abs(Y4) > 1e-10, V / Y4, 0)
    alpha_y5 = np.clip(alpha_y5, 0, 1)
    Y5 = DMA(Y2, alpha_y5)
    ndf["Y5"] = Y5

    # Y6 := (C-Y5)/Y5*100
    Y6 = np.where(np.abs(Y5) > 1e-10, (C - Y5) / Y5 * 100, 0)
    ndf["Y6"] = Y6

    # Y7 := (Y3<10) AND (Y6<=-10)
    Y7 = (Y3 < 10) & (Y6 <= -10)
    ndf["Y7"] = Y7

    # Y8 := SMA(MAX(C-REF(C,1.5),0),6,1)/SMA(ABS(C-REF(C,1.5)),1,1)*100
    C_REF15 = _ref_frac(C, 1.5)
    Y8_num = SMA(MAX(C - C_REF15, 0), 6, 1)
    Y8_den = SMA(ABS(C - C_REF15), 1, 1)
    with np.errstate(divide='ignore', invalid='ignore'):
        Y8 = np.where(Y8_den > 1e-10, Y8_num / Y8_den * 100, 0)
    ndf["Y8"] = Y8

    # CTA1 := (HHV(H,21)-C)/(HHV(H,21)-LLV(L,21))*100-10
    HH21 = HHV(H, 21)
    LL21 = LLV(L, 21)
    CTA1 = np.where(HH21 - LL21 > 1e-10, (HH21 - C) / (HH21 - LL21) * 100 - 10, 0)
    ndf["CTA1"] = CTA1

    # CTA2 := (C-LLV(L,21))/(HHV(H,21)-LLV(L,21))*100
    CTA2 = np.where(HH21 - LL21 > 1e-10, (C - LL21) / (HH21 - LL21) * 100, 0)
    ndf["CTA2"] = CTA2

    # CTA3 := SMA(CTA2,13,8)
    CTA3 = SMA(CTA2, 13, 8)
    ndf["CTA3"] = CTA3

    # CTA4 := CEILING(SMA(CTA3,13,8))
    CTA4 = np.ceil(SMA(CTA3, 13, 8))
    ndf["CTA4"] = CTA4

    # CTA5 := SMA(CTA1,21,8)
    CTA5 = SMA(CTA1, 21, 8)
    ndf["CTA5"] = CTA5

    # EDF1 := SMA(MAX(C-REF(C,2),0),7,1)/SMA(ABS(C-REF(C,2)),7,1)*100
    C_REF2 = REF(C, 2)
    with np.errstate(divide='ignore', invalid='ignore'):
        EDF1 = SMA(MAX(C - C_REF2, 0), 7, 1) / SMA(ABS(C - C_REF2), 7, 1) * 100
    ndf["EDF1"] = EDF1

    # EDF2 := CTA4-CTA5 < -65 AND EDF1 < 12
    EDF2 = (CTA4 - CTA5 < -65) & (EDF1 < 12)
    ndf["EDF2"] = EDF2

    # CTC1: Y6<=-10 AND BCD1<0
    CTC1 = (Y6 <= -10) & (BCD1 < 0)
    ndf["CTC1"] = CTC1

    # CTC2: Y6<=-16 AND BCD1<0
    CTC2 = (Y6 <= -16) & (BCD1 < 0)
    ndf["CTC2"] = CTC2

    # CTC3: Y7 AND BCD1<0
    CTC3 = Y7 & (BCD1 < 0)
    ndf["CTC3"] = CTC3

    # XYZ1 := MA(LOW,2)*0.96
    XYZ1 = MA(L, 2) * 0.96
    ndf["XYZ1"] = XYZ1

    # XYZ2 := MA(LOW,26)*0.85
    XYZ2 = MA(L, 26) * 0.85
    ndf["XYZ2"] = XYZ2

    # XYZ3 := REF(XYZ1,1)<XYZ2 AND REF(XYZ1,1)<XYZ1 AND REF(XYZ1,1)<REF(XYZ1,2)
    XYZ1_REF1 = REF(XYZ1, 1)
    XYZ1_REF2 = REF(XYZ1, 2)
    XYZ3 = (XYZ1_REF1 < XYZ2) & (XYZ1_REF1 < XYZ1) & (XYZ1_REF1 < XYZ1_REF2)
    ndf["XYZ3"] = XYZ3

    # C0 := REF(C,2)*0.865
    C0 = REF(C, 2) * 0.865
    ndf["C0"] = C0

    # C1 := REF(C,13)*0.772
    C1 = REF(C, 13) * 0.772
    ndf["C1"] = C1

    # DSY := 100*VOL/CAPITAL
    DSY = np.where(CAPITAL > 1e-10, 100 * V / CAPITAL, 0)
    ndf["DSY"] = DSY

    # CTC43 := (C-MIN(C0,C1))/C<0.1 AND SUM(DSY,5)/5<1.8
    C_MIN = np.where(np.isnan(C0) | np.isnan(C1), np.nan, np.minimum(C0, C1))
    cond_price = np.where(np.abs(C) > 1e-10, (C - C_MIN) / C < 0.1, False)
    cond_vol = SUM(DSY, 5) / 5 < 1.8
    CTC43 = cond_price & cond_vol
    ndf["CTC43"] = CTC43

    # CTD1 := DMA(EMA(C,12), SUM(V,5)/3/CAPITAL)
    EMA12 = EMA(C, 12)
    alpha_ctd1 = np.where(CAPITAL > 1e-10, SUM(V, 5) / 3 / CAPITAL, 0)
    alpha_ctd1 = np.clip(alpha_ctd1, 0, 1)
    CTD1 = DMA(EMA12, alpha_ctd1)
    ndf["CTD1"] = CTD1

    # CTD2 := REF(H,10)/C>1.35
    H_REF10 = REF(H, 10)
    CTD2 = np.where(C > 1e-10, H_REF10 / C > 1.35, False)
    ndf["CTD2"] = CTD2

    # CTD3 := (COST(20)-C)/C>0.15
    CTD3 = np.where((C > 1e-10) & (~np.isnan(cost20_val)),
                    (cost20_val - C) / C > 0.15, False)
    ndf["CTD3"] = CTD3

    # CTD4 := H>L*1.051
    CTD4 = H > L * 1.051
    ndf["CTD4"] = CTD4

    # CTD5 := CTD4 AND COUNT(CTD4,5)>1
    CTD5 = CTD4 & (COUNT(CTD4.astype(float), 5) > 1)
    ndf["CTD5"] = CTD5

    # CTD6 := (((C-CTD1)/CTD1*100<-30) OR CTD2) AND CTD3 AND CTD5
    cond_a = np.where(np.abs(CTD1) > 1e-10, (C - CTD1) / CTD1 * 100 < -30, False)
    CTD6 = (cond_a | CTD2) & CTD3 & CTD5
    ndf["CTD6"] = CTD6

    # XL1 := MA(LOW,2)*0.96
    XL1 = MA(L, 2) * 0.96
    ndf["XL1"] = XL1

    # XL2 := MA(LOW,26)*0.85
    XL2 = MA(L, 26) * 0.85
    ndf["XL2"] = XL2

    # XL3 := REF(XL1,1)<XL2 AND REF(XL1,1)<XL1 AND REF(XL1,1)<REF(XL1,2)
    XL1_REF1 = REF(XL1, 1)
    XL1_REF2 = REF(XL1, 2)
    XL3 = (XL1_REF1 < XL2) & (XL1_REF1 < XL1) & (XL1_REF1 < XL1_REF2)
    ndf["XL3"] = XL3

    # VAR1A := DMA(AMOUNT/VOL/100, VOL/CAPITAL)
    alpha_var1a = np.where(CAPITAL > 1e-10, V / CAPITAL, 0)
    alpha_var1a = np.clip(alpha_var1a, 0, 1)
    VAR1A = DMA(np.where(V > 1e-10, AMOUNT / V / 100, C / 100), alpha_var1a)
    ndf["VAR1A"] = VAR1A

    # VAR4AA := CLOSE/(REF(CLOSE,1))>1.05 AND (HIGH/CLOSE<1.01)
    C_REF1 = REF(C, 1)
    VAR4AA = (C / C_REF1 > 1.05) & (H / C < 1.01)
    ndf["VAR4AA"] = VAR4AA

    # 启动点 := FILTER(VAR4AA>0, 34)  (在回测中 DYNAINFO(4)>0 始终成立)
    launch_raw = VAR4AA.astype(float)
    launch_filtered = FILTER(launch_raw.copy(), 34)
    launch = (launch_filtered > 0) * 8
    ndf["启动点"] = launch

    # LS := C/REF(C,1)>1.048 AND C=H AND BETWEEN(FORCAST(V,4),0.2*FORCAST(V,12),2.1*FORCAST(V,12))
    LS = (C / REF(C, 1) > 1.048) & np.isclose(C, H) & BETWEEN(FORCAST(V, 4), 0.2 * FORCAST(V, 12), 2.1 * FORCAST(V, 12))
    ndf["LS"] = LS

    # 见底 := FILTER(LS, 28)
    bottom_raw = LS.astype(float)
    bottom_filtered = FILTER(bottom_raw.copy(), 28)
    ndf["见底"] = bottom_filtered > 0

    # 综合买信号: XL3 OR CTD6
    buy_signal = XL3 | CTD6
    ndf["买信号"] = buy_signal

    return ndf


def _extract_last_day_signal(symbol, ndf):
    """提取最后一个交易日出现的所有信号（含 BCD1*50），无信号返回 None"""
    if ndf is None or len(ndf) < 1:
        return None
    last_idx = len(ndf) - 1
    row = ndf.iloc[last_idx]

    labels = []
    if not bool(row["CTD6"]):
        return None
    if bool(row["XL3"]):
        labels.append("XL3")
    if bool(row["CTD6"]):
        labels.append("CTD6")
    if float(row["启动点"]) > 0:
        labels.append("启动点")
    if bool(row["见底"]):
        labels.append("见底")
    if not labels:
        return None

    bcd1 = float(row["BCD1"])
    return {
        "symbol": symbol,
        "name": get_symbols_name(symbol),
        "date": str(row["date"]),
        "signal": "+".join(labels),
        "open": float(row["open"]),
        "close": float(row["close"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "volume": float(row["volume"]),
        "amount": float(row["amount"]),
        "turn": float(row["turn"]),
        "BCD1": round(bcd1, 2),
        "BCD1*50": round(50 * bcd1, 2),
    }


def get_last_day_signals(symbol, df):
    """计算指标并返回最后一个交易日出现的信号，供并行扫描使用"""
    if df is None or len(df) < 120:
        return None
    ndf = calculate_oversold_indicators(df)
    if ndf is None:
        return None
    return _extract_last_day_signal(symbol, ndf)


def _record_position(symbol, entries, df):
    """记录一次持仓（可能包含多次加仓）到对应信号类型的统计中"""
    last_entry = entries[-1]
    last_entry_idx = last_entry["idx"]
    avg_cost = sum(e["price"] for e in entries) / len(entries)
    sig_label = last_entry["sig_label"]

    stats = signal_stats[sig_label]

    max_val = -1000.0
    for day_offset in range(hold_days + 1):
        check_idx = last_entry_idx + day_offset
        if check_idx >= len(df):
            break
        check_close = float(df["close"].iloc[check_idx])
        ratio = round(100 * (check_close - avg_cost) / (avg_cost + 1e-10), 2)
        if day_offset > 0:
            stats["ratio_map"][day_offset].append(ratio)
        max_val = max(max_val, ratio)

    exit_idx = last_entry_idx + hold_days
    exit_date = df["date"].iloc[exit_idx] if exit_idx < len(df) else None
    exit_price = float(df["close"].iloc[exit_idx]) if exit_idx < len(df) else None

    exit_ret = None
    if exit_price is not None:
        exit_ret = (exit_price - avg_cost) / (avg_cost + 1e-10) * 100
        (stats["plus"] if exit_ret > 0 else stats["minus"]).append(exit_ret)

    first_entry_idx = entries[0]["idx"]
    actual_hold_days = exit_idx - first_entry_idx if exit_idx < len(df) else hold_days

    stats["count"] += 1
    stats["symbols"].append(symbol)
    stats["pyramid_counts"].append(len(entries))
    stats["hold_days_list"].append(actual_hold_days)

    return max_val, exit_ret, exit_date


def get_oversold_buy_point(symbol, df, track_last_day=True):
    if df is None or len(df) < 120:
        return
    ndf = calculate_oversold_indicators(df)
    if ndf is None:
        return

    if track_last_day:
        last_sig = _extract_last_day_signal(symbol, ndf)
        if last_sig is not None:
            last_day_signals.append(last_sig)

    xl3 = ndf["XL3"].fillna(False).values
    ctd6 = ndf["CTD6"].fillna(False).values
    buy_signal = xl3 | ctd6
    if not buy_signal.any():
        return

    sig_idxs = []
    for idx in np.where(buy_signal)[0]:
        if not bool(ctd6[idx]):
            continue

        is_xl3 = bool(xl3[idx])
        is_ctd6 = bool(ctd6[idx])
        sl = "+".join([s for s, v in [("XL3", is_xl3), ("CTD6", is_ctd6)] if v])
        print("{} 日期：{} 信号：{} BCD1:{:.2f}".format(symbol, ndf["date"].iloc[idx], sl, 50 * float(ndf["BCD1"].iloc[idx])))
        
        if idx + 1 >= len(df):
            continue
        sig_idxs.append(idx)

    if not sig_idxs:
        return

    all_dates = ndf["date"].values
    all_open = ndf["open"].values.astype(float)
    all_close = ndf["close"].values.astype(float)

    # 持仓模拟: 依次处理每个信号
    position = None  # None or {"entries": [...], "last_entry_idx": int, "close_idx": int}

    def _make_entry(sig_idx):
        buy_idx = sig_idx + 1
        is_xl3 = bool(xl3[sig_idx])
        is_ctd6 = bool(ctd6[sig_idx])
        sl = "+".join([s for s, v in [("XL3", is_xl3), ("CTD6", is_ctd6)] if v])
        return {"idx": buy_idx, "price": float(all_open[buy_idx]), "date": all_dates[buy_idx],
                "sig_idx": sig_idx, "sig_label": sl}

    for sig_idx in sig_idxs:
        entry = _make_entry(sig_idx)

        # 持仓到期自动平仓（无论是否有新信号）
        if position is not None and sig_idx >= position["close_idx"]:
            max_ret, exit_ret, exit_date = _record_position(symbol, position["entries"], ndf)
            exit_str = "{:.2f}%".format(exit_ret) if exit_ret is not None else "N/A"
            print("{} 平仓 买入:{} 卖出:{} 均价:{:.2f} 持有{}日收益:{} 最大收益:{:.2f}%".format(
                symbol, position["entries"][0]["date"], exit_date,
                sum(e["price"] for e in position["entries"]) / len(position["entries"]),
                hold_days, exit_str, max_ret))
            position = None

        if position is None:
            position = {"entries": [entry], "last_entry_idx": entry["idx"],
                        "close_idx": entry["idx"] + hold_days}
            print("{} 开仓 信号:{} 买入:{} 价:{:.2f}  BCD1:{:.2f}".format(
                symbol, all_dates[sig_idx], entry["date"], entry["price"],
                50 * float(ndf["BCD1"].iloc[sig_idx])))
        else:
            days_since = sig_idx - position["last_entry_idx"]
            if days_since <= hold_days:
                position["entries"].append(entry)
                position["last_entry_idx"] = entry["idx"]
                position["close_idx"] = entry["idx"] + hold_days
                avg = sum(e["price"] for e in position["entries"]) / len(position["entries"])
                print("{} 加仓 信号:{} 买入:{} 价:{:.2f} 均价:{:.2f} BCD1:{:.2f}".format(
                    symbol, all_dates[sig_idx], entry["date"], entry["price"], avg,
                    50 * float(ndf["BCD1"].iloc[sig_idx])))
            else:
                max_ret, exit_ret, exit_date = _record_position(symbol, position["entries"], ndf)
                exit_str = "{:.2f}%".format(exit_ret) if exit_ret is not None else "N/A"
                print("{} 平仓 买入:{} 卖出:{} 均价:{:.2f} 持有{}日收益:{} 最大收益:{:.2f}%".format(
                    symbol, position["entries"][0]["date"], exit_date,
                    sum(e["price"] for e in position["entries"]) / len(position["entries"]),
                    hold_days, exit_str, max_ret))
                position = {"entries": [entry], "last_entry_idx": entry["idx"],
                            "close_idx": entry["idx"] + hold_days}
                print("{} 开仓 信号:{} 买入:{} 价:{:.2f}  BCD1:{:.2f}".format(
                    symbol, all_dates[sig_idx], entry["date"], entry["price"],
                    50 * float(ndf["BCD1"].iloc[sig_idx])))

    if position is not None:
        max_ret, exit_ret, exit_date = _record_position(symbol, position["entries"], ndf)
        exit_str = "{:.2f}%".format(exit_ret) if exit_ret is not None else "N/A"
        print("{} 平仓 买入:{} 卖出:{} 均价:{:.2f} 持有{}日收益:{} 最大收益:{:.2f}%".format(
            symbol, position["entries"][0]["date"], exit_date,
            sum(e["price"] for e in position["entries"]) / len(position["entries"]),
            hold_days, exit_str, max_ret))


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

    if stats["pyramid_counts"]:
        pc = np.array(stats["pyramid_counts"])
        single = int(np.sum(pc == 1))
        multi = int(np.sum(pc > 1))
        print("  平均加仓次数：{:.2f}  (仅开仓:{} / 加仓:{})".format(np.mean(pc), single, multi))

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
    print("  超跌反弹策略 — 分信号类型统计结果")
    print("=" * 70)

    for key in SIGNAL_KEYS:
        _print_signal_header(key)
        _print_signal_stats(key, signal_stats[key])


def print_last_day_signals(signals):
    """打印最后一个交易日出现信号的股票（含 BCD1*50 柱高值）"""
    print("\n" + "=" * 90)
    print("  最后一个交易日出现信号的股票（BCD1*50 为通达信柱高值）")
    print("=" * 90)
    if not signals:
        print("  无\n")
        return

    signals = sorted(signals, key=lambda r: r["BCD1*50"])
    print("{:<10}{:<10}{:<12}{:<14}{:>8}{:>8}{:>10}{:>8}".format(
        "代码", "名称", "日期", "信号", "收盘", "BCD1", "BCD1*50", "涨跌%"))
    print("-" * 90)
    for r in signals:
        pct = (r["close"] - r["open"]) / r["open"] * 100 if r["open"] else 0
        print("{:<10}{:<10}{:<12}{:<14}{:>8.2f}{:>8.2f}{:>10.2f}{:>8.2f}".format(
            r["symbol"], r["name"], r["date"], r["signal"],
            r["close"], r["BCD1"], r["BCD1*50"], pct))
    print("-" * 90)
    print("  共 {} 只股票出现信号\n".format(len(signals)))


def _bs_login_init():
    pass
    # bs.login()


def _scan_worker(args):
    """子进程扫描单个股票，返回最后一个交易日信号"""
    symbol, start_date, end_date = args
    try:
        df = get_stock_pd(symbol, start_date, end_date, 'd')
        return get_last_day_signals(symbol, df)
    except Exception:
        return None


def scan_last_day_signals(symbols, start_date, end_date, workers=None):
    """
    多进程并行扫描全市场，返回最后一个交易日出现信号的股票列表。
    baostock/通达信连接不保证线程安全，故使用进程池，每个子进程独立登录。
    """
    if workers is None:
        workers = min(os.cpu_count() or 1, 1)

    print("[{}] 开始并行扫描 {} 只股票（{} 进程）……".format(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), len(symbols), workers))

    results = []
    args = [(s, start_date, end_date) for s in symbols]
    with ProcessPoolExecutor(max_workers=workers, initializer=_bs_login_init) as executor:
        for i, res in enumerate(executor.map(_scan_worker, args), 1):
            if res is not None:
                results.append(res)
            if i % 100 == 0:
                print("[{}] 扫描进度：{} / {}".format(
                    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i, len(args)))

    print("[{}] 扫描完成，共 {} 只股票出现信号".format(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), len(results)))
    return results


if __name__ == "__main__":
    start_date = "2024-01-01"
    end_date = '2026-08-10'

    all_symbols = get_daily_symbols()
    total = len(all_symbols)

    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
    end_date = get_latest_trade_date()

    if True:
        # 1) 并行扫描：最后一个交易日出现信号的股票（含 BCD1*50）
        signals = scan_last_day_signals(all_symbols, start_date, end_date)
        print_last_day_signals(signals)
        if signals:
            write_json(signals, './data/超跌反弹_最新信号.json')
            print("结果已保存到 ./data/超跌反弹_最新信号.json")

    if False:
        # 2) 串行完整回测统计
        print("\n开始串行回测统计……")
        for i, symbol in enumerate(all_symbols):
            print("[{}] 回测进度：{} / {}".format(
                    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
            try:
                df = get_stock_pd(symbol, start_date, end_date, 'd')
                get_oversold_buy_point(symbol, df, track_last_day=False)
            except Exception as e:
                continue
            if (i + 1) % 100 == 0:
                print_statistics()
        print_statistics()

    bs.logout()

'''
RS:=SMA(MAX(C-REF(C,1),0),14,1)/SMA(ABS(C-REF(C,1)),14,1)*100;
BCD:= EMA(EMA(EMA(RS,7),3),3);
BCD1:=(BCD-REF(BCD,1))/REF(BCD,1)*15;
STICKLINE(BCD1>=0,0,BCD1*50,0.5,0),COLOR0000BE;
STICKLINE(BCD1<=0,0,BCD1*50,0.5,0),COLORCYAN;
Y1:=AMOUNT/V/100;
Y2:=(3*H+L+O+2*C)/7;
Y3:=100*(WINNER(1.1*C)-WINNER(0.9*C));
Y4:=SUM(AMOUNT,13)/Y1/100;  
Y5:= DMA(Y2,V/Y4);
Y6:=(C-Y5)/Y5*100;
Y7:=(Y3< 10) AND (Y6<=-10);
Y8:=SMA(MAX(C-REF(C,1.5),0),6,1)/SMA(ABS(C-REF(C,1.5)),1,1)*100;
CTC1: STICKLINE(Y6<=-10 AND BCD1< 0,BCD1*55,BCD1*45,1,0),COLORFF89B2;
CTC2:STICKLINE(Y6<=-16 AND BCD1< 0,BCD1*60,BCD1*55,1,1),COLORBLUE;
CTC3:STICKLINE(Y7 AND BCD1< 0,BCD1*65,BCD1*60,1,0),COLORFFFFFF;
CTA1:=(HHV(H,21)-C)/(HHV(H,21)-LLV(L,21))*100-10;
CTA2:=(C-LLV(L,21))/(HHV(H,21)-LLV(L,21))*100;
CTA3:=SMA(CTA2,13,8);{公式网WWW.GPXIAZAI.COM}
CTA4:=CEILING(SMA(CTA3,13,8));
CTA5:=SMA(CTA1,21,8);
EDF1:=SMA(MAX(C-REF(C,2),0),7,1)/SMA(ABS(C-REF(C,2)),7,1)*100;
EDF2:=CTA4-CTA5< -65 AND EDF1< 12;
CTC4:=EDF2;
XYZ1:=MA(LOW,2)*0.96;
XYZ2:=MA(LOW,26)*0.85;
XYZ3:= REF(XYZ1,1)< XYZ2 AND REF(XYZ1,1)< XYZ1 AND REF(XYZ1,1)< REF(XYZ1,2);
CTC42:=XYZ3;
C0:=REF(C,2)*0.865;
C1:=REF(C,13)*0.772;
DSY:=100*VOL/CAPITAL;
CTC43:=(C-MIN(C0,C1))/C< 0.1 AND SUM(DSY,5)/5< 1.8;
WW1:= SUM( MA(C,10),9)/10.110;
WW2:=CROSS(C,WW1);
CTD1:=DMA(EMA(C,12),SUM(V,5)/3/CAPITAL);
CTD2:=REF(H,10)/C>1.35;
CTD3:=(COST(20)-C)/C>0.15;
CTD4:=H>L*1.051;
CTD5:=CTD4 AND COUNT(CTD4,5)>1;
CTD6:=(((C-CTD1)/CTD1*100< -30) OR CTD2) AND CTD3 AND CTD5;
DRAWICON(CTD6,BCD1*-40,4);
XL1:=MA(LOW,2)*0.96;
XL2:=MA(LOW,26)*0.85;
XL3:=REF(XL1,1)< XL2 AND REF(XL1,1)< XL1 AND REF(XL1,1)< REF(XL1,2);
STICKLINE(XL3 OR CTD6,0,15,1,0),COLORFF7F00;
DRAWTEXT(XL3 OR CTD6,15,'←买'),COLORFF7F00;
VAR1A:=DMA(AMOUNT/VOL/100,VOL/CAPITAL);
VAR4AA:=CLOSE/(REF(CLOSE,1))>1.05 AND (HIGH/CLOSE< 1.01);
启动点:(FILTER(VAR4AA>0,34)AND DYNAINFO(4)>0)*8,COLORYELLOW;
STICKLINE(启动点,0,38,2,0),COLORYELLOW;
DRAWICON(启动点=8,30,25);
DRAWICON(启动点=8,20,26);
DRAWICON(启动点=8,10,27);
DRAWTEXT(启动点=8,20,'启动'),COLORYELLOW;
LS:=C/REF(C,1)>1.048 AND C=H AND BETWEEN(FORCAST(V,4),0.2*FORCAST(V,12),2.1*FORCAST(V,12));
见底:=FILTER(LS,28);
STICKLINE(见底,0,38,0.5,0),COLORRED;
DRAWTEXT(见底,30,'----止跌见底'),COLORRED;
DRAWICON(见底,30,9);
'''
'''
======================================================================
  超跌反弹策略 — 分信号类型统计结果
======================================================================

======================================================================
  【XL3】
======================================================================
  无交易信号


======================================================================
  【CTD6】
======================================================================
  交易次数：851
  正收益次数：639  负收益次数：212
  正收益占比：75.09%
  平均收益：8.22%
  总的正收益：8376.23%  正收益均值：13.11%
  总的负收益：-1384.74%  负收益均值：-6.53%
  最大收益：159.31%  最小收益：-23.86%
  中位数收益：7.26%
  95% 分位数：28.34%
  5% 分位数：-10.66%

  涉及股票数：98
  平均加仓次数：4.18  (仅开仓:246 / 加仓:605)
  持有天数: 最大=68  最小=10  平均=15.6

  --- 逐日收益 ---
  第1天  | 均值:   3.89%  中位:   3.61%  胜率: 70.4%  总正: 4457.18  总负:-1146.71
  第2天  | 均值:   4.86%  中位:   4.19%  胜率: 72.7%  总正: 5233.74  总负:-1094.63
  第3天  | 均值:   5.90%  中位:   4.81%  胜率: 76.7%  总正: 5882.65  总负: -858.99
  第4天  | 均值:   7.10%  中位:   5.86%  胜率: 79.2%  总正: 6864.28  总负: -821.61
  第5天  | 均值:   7.76%  中位:   6.61%  胜率: 78.4%  总正: 7405.87  总负: -799.04
  第6天  | 均值:   7.63%  中位:   6.14%  胜率: 78.1%  总正: 7357.83  总负: -863.05
  第7天  | 均值:   7.94%  中位:   6.67%  胜率: 77.8%  总正: 7646.55  总负: -890.16
  第8天  | 均值:   8.36%  中位:   6.95%  胜率: 78.6%  总正: 7997.25  总负: -880.23
  第9天  | 均值:   8.36%  中位:   6.73%  胜率: 76.4%  总正: 8159.21  总负:-1041.76
  第10天  | 均值:   8.22%  中位:   7.26%  胜率: 75.0%  总正: 8376.21  总负:-1384.81

======================================================================
  【XL3+CTD6】
======================================================================
  交易次数：95
  正收益次数：75  负收益次数：20
  正收益占比：78.95%
  平均收益：10.71%
  总的正收益：1151.02%  正收益均值：15.35%
  总的负收益：-133.22%  负收益均值：-6.66%
  最大收益：55.72%  最小收益：-18.31%
  中位数收益：10.58%
  95% 分位数：33.36%
  5% 分位数：-9.01%

  涉及股票数：57
  平均加仓次数：6.82  (仅开仓:2 / 加仓:93)
  持有天数: 最大=44  最小=10  平均=18.4

  --- 逐日收益 ---
  第1天  | 均值:   5.28%  中位:   5.04%  胜率: 72.6%  总正:  619.82  总负: -118.06
  第2天  | 均值:   5.50%  中位:   4.49%  胜率: 73.7%  总正:  626.07  总负: -103.59
  第3天  | 均值:   6.20%  中位:   4.72%  胜率: 77.9%  总正:  707.42  总负: -118.27
  第4天  | 均值:   7.06%  中位:   7.28%  胜率: 72.6%  总正:  797.34  总负: -127.04
  第5天  | 均值:   8.08%  中位:   8.15%  胜率: 73.7%  总正:  912.17  总负: -144.10
  第6天  | 均值:   8.24%  中位:   6.90%  胜率: 75.8%  总正:  916.13  总负: -132.97
  第7天  | 均值:   9.20%  中位:   8.21%  胜率: 75.8%  总正:  993.37  总负: -119.42
  第8天  | 均值:   9.99%  中位:   8.05%  胜率: 77.9%  总正: 1070.41  总负: -121.33
  第9天  | 均值:  10.96%  中位:   9.82%  胜率: 80.0%  总正: 1167.06  总负: -125.39
  第10天  | 均值:  10.71%  中位:  10.58%  胜率: 78.9%  总正: 1151.01  总负: -133.24

======================================================================
  【启动点】
======================================================================
  无交易信号


======================================================================
  【见底】
======================================================================
  无交易信号

'''