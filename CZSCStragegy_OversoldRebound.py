# coding: utf-8
"""
超跌反弹策略（通达信公式对应）

公式来源：综合超跌反弹指标
核心买信号：
  1. CTD6: 超跌反弹主信号 — 股价深跌、筹码套牢、近期有异动
  2. XL3: 低位拐头信号 — 短期低点均线在长期支撑下方企稳

策略逻辑：出现 XL3 OR CTD6「买」信号次日开盘买入，持有 hold_days 日后统计收益。
"""
import pandas as pd
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from lib.MyTT import (
    REF, EMA, SMA, HHV, LLV, MAX, MIN, ABS, MA, SUM, DMA,
    FORCAST, BETWEEN, COUNT, FILTER,
)
from czsc_daily_util import get_daily_symbols
from czsc_sqlite import get_local_stock_data

hold_days = 5

SIGNAL_KEYS = ["XL3", "CTD6", "XL3+CTD6", "启动点", "见底"]


def _new_stats():
    return {
        "plus": [],
        "minus": [],
        "ratio_map": {x: [] for x in range(1, hold_days + 1)},
        "count": 0,
        "symbols": [],
    }


signal_stats = {k: _new_stats() for k in SIGNAL_KEYS}


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


def _record_trade(stats, symbol, buy_idx, df, sig_label):
    """记录一次交易到对应信号类型的统计中"""
    buy_price = float(df["open"].iloc[buy_idx])
    max_val = -1000.0
    for day_offset in range(1, hold_days + 1):
        sell_idx = buy_idx + day_offset
        if sell_idx >= len(df):
            break
        sell_close = float(df["close"].iloc[sell_idx])
        ratio = round(100 * (sell_close - buy_price) / (buy_price + 1e-10), 2)
        stats["ratio_map"][day_offset].append(ratio)
        max_val = max(max_val, ratio)

    if max_val > 0:
        stats["plus"].append(max_val)
    else:
        stats["minus"].append(max_val)
    stats["count"] += 1
    stats["symbols"].append(symbol)
    return max_val


def get_oversold_buy_point(symbol, df):
    if df is None or len(df) < 120:
        return
    ndf = calculate_oversold_indicators(df)
    if ndf is None:
        return

    # --- 主信号: XL3 / CTD6 ---
    xl3 = ndf["XL3"].fillna(False).values
    ctd6 = ndf["CTD6"].fillna(False).values
    buy_signal = xl3 | ctd6
    if buy_signal.any():
        for idx in np.where(buy_signal)[0]:
            buy_idx = idx + 1
            if buy_idx >= len(df):
                continue
            is_xl3 = bool(xl3[idx])
            is_ctd6 = bool(ctd6[idx])
            sig_label = "+".join(
                [s for s, v in [("XL3", is_xl3), ("CTD6", is_ctd6)] if v]
            )
            max_val = _record_trade(signal_stats[sig_label], symbol, buy_idx, df, sig_label)
            print("{} 买信号日期: {} 买入日期: {} 买入价: {:.2f} 信号: {} 持有{}日内最大收益: {:.2f}%".format(
                symbol, df["date"].iloc[idx], df["date"].iloc[buy_idx],
                float(df["open"].iloc[buy_idx]), sig_label, hold_days, max_val))

    # --- 辅助信号: 启动点 ---
    launch = ndf["启动点"].fillna(0).values
    if launch.any():
        for idx in np.where(launch > 0)[0]:
            buy_idx = idx + 1
            if buy_idx >= len(df):
                continue
            max_val = _record_trade(signal_stats["启动点"], symbol, buy_idx, df, "启动点")
            print("{} 启动点日期: {} 买入日期: {} 买入价: {:.2f} 持有{}日内最大收益: {:.2f}%".format(
                symbol, df["date"].iloc[idx], df["date"].iloc[buy_idx],
                float(df["open"].iloc[buy_idx]), hold_days, max_val))

    # --- 辅助信号: 见底 ---
    bottom = ndf["见底"].fillna(False).values
    if bottom.any():
        for idx in np.where(bottom)[0]:
            buy_idx = idx + 1
            if buy_idx >= len(df):
                continue
            max_val = _record_trade(signal_stats["见底"], symbol, buy_idx, df, "见底")
            print("{} 见底日期: {} 买入日期: {} 买入价: {:.2f} 持有{}日内最大收益: {:.2f}%".format(
                symbol, df["date"].iloc[idx], df["date"].iloc[buy_idx],
                float(df["open"].iloc[buy_idx]), hold_days, max_val))


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
    print("  总的正收益：{:.2f}%".format(sum(plus)))
    print("  总的负收益：{:.2f}%".format(sum(minus)))
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


if __name__ == "__main__":
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    for i, symbol in enumerate(all_symbols):
        print("[{}] 进度：{} / {}".format(
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            df = get_local_stock_data(symbol, start_date)
            get_oversold_buy_point(symbol, df)
        except Exception as e:
            continue
        if (i + 1) % 100 == 0:
            print_statistics()
    print_statistics()
