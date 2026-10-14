# coding: utf-8
"""底部 / 大资金潜伏策略（通达信公式对应）。

VAR3:=(CLOSE-MA(CLOSE, 6))/MA(CLOSE, 6)*100;
VAR4:=(CLOSE-MA(CLOSE, 24))/MA(CLOSE, 24)*100;
VAR5:=(CLOSE-MA(CLOSE, 32))/MA(CLOSE, 32)*100;
VAR6:=(VAR3+VAR4+VAR5)/3;
VAR7:=EMA(VAR6, 5);
VAR8:=IF(VAR6<=-20, 10, 0);
VAR9:=HHV(VAR8, 10);{公式网WWW.GPXIAZAI.COM}
STICKLINE(VAR8=10, 20, 10, 5, 0), COLOR6666FF;
VARA:=IF(VAR9 AND CROSS(MA(CLOSE, 3), MA(CLOSE, 5)), 20, 0);
DRAWTEXT(VARA=20, 15, '底部'), LINETHICK1, COLORWHITE;
STICKLINE((VARA=20), 0, 10, 5, 0), COLORWHITE;
VARE:=MA(100*(CLOSE-LLV(CLOSE, 34))/(HHV(HIGH, 34)-LLV(LOW, 34)), 5)-20;
VARF:=100-3*SMA((CLOSE-LLV(LOW, 75))/(HHV(HIGH, 75)-LLV(LOW, 75))*100, 20, 1)+2*SMA(SMA((CLOSE-LLV(LOW, 75))/(HHV(HIGH, 75)-LLV(LOW, 75))*100, 20, 1), 15, 1);
VAR10:=100-3*SMA((OPEN-LLV(LOW, 75))/(HHV(HIGH, 75)-LLV(LOW, 75))*100, 20, 1)+2*SMA(SMA((OPEN-LLV(LOW, 75))/(HHV(HIGH, 75)-LLV(LOW, 75))*100, 20, 1), 15, 1);
VAR11:=VARF< REF(VAR10, 1)AND VOL>REF(VOL, 1)AND CLOSE>REF(CLOSE, 1);
DRAWTEXT(VAR11 AND COUNT(VAR11, 30)=1, 15, '大资金潜伏'), LINETHICK1, COLORYELLOW;
STICKLINE(VAR11 AND COUNT(VAR11, 30)=1, 1, 10, 5, 0), COLORFF00FF;

买信号：VARA=20「底部」或 VAR11 AND COUNT(VAR11,30)=1「大资金潜伏」。
指标及买点替换为本公式；持仓处理、全局统计和运行入口沿用
CZSCStragegy_OversoldRebound_org.py，原策略专用的 CTD6 过滤不用于本公式。

数据不足 120 根时返回；达到 120 根后遍历所有历史买点，不另设前 120 根禁买。
次日开盘等股数买入，持仓中出现买点继续加仓，从最后买入起算 hold_days。
按最后一次买点分组；未到期持仓同样计入 count、加仓和已有逐日收益统计，
只有存在到期收盘价的持仓才计入 plus/minus。逐日收益保留两位小数。
最大收益包含最后买入当日收盘。保持参考脚本的打印和统计口径。

运行：venv/bin/python CZSCStragegy_BottomAccumulation.py
在文件末尾修改 test_symbols、start_date、end_date，在顶部修改 hold_days。
"""
import pandas as pd
import numpy as np
import baostock as bs
from lib.MyTT import COUNT, EMA, HHV, LLV, MA, REF, SMA
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 10
SIGNAL_KEYS = ["底部", "大资金潜伏", "底部+大资金潜伏"]


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


def _safe_ratio(numerator, denominator):
    result = np.full(len(numerator), np.nan)
    np.divide(numerator, denominator, out=result,
              where=np.isfinite(denominator) & (denominator != 0))
    return result


def calculate_indicators(df):
    """返回含全部原式变量及两类买点的副本；输入需含 OHLC、volume。"""
    if df is None or len(df) < 120:
        return None
    ndf = df.copy()
    prices = ndf[["open", "high", "low", "close"]].to_numpy(dtype=float)
    O, H, L, C = prices.T
    V = ndf["volume"].to_numpy(dtype=float)
    ma6, ma24, ma32 = MA(C, 6), MA(C, 24), MA(C, 32)
    var3 = _safe_ratio(C - ma6, ma6) * 100
    var4 = _safe_ratio(C - ma24, ma24) * 100
    var5 = _safe_ratio(C - ma32, ma32) * 100
    var6 = (var3 + var4 + var5) / 3
    var7 = EMA(var6, 5)
    var8 = np.where(var6 <= -20, 10, 0)
    var9 = HHV(var8, 10)
    ma3, ma5 = MA(C, 3), MA(C, 5)
    cross = (ma3 > ma5) & (REF(ma3, 1) <= REF(ma5, 1))
    vara = np.where((var9 > 0) & cross, 20, 0)
    # 分子是最低收盘价，分母是最高价与最低价的区间，保留原式区别。
    vare = MA(_safe_ratio(C - LLV(C, 34), HHV(H, 34) - LLV(L, 34)) * 100, 5) - 20
    low75 = LLV(L, 75)
    span75 = HHV(H, 75) - low75
    close_rsv = _safe_ratio(C - low75, span75) * 100
    open_rsv = _safe_ratio(O - low75, span75) * 100
    close_sma = SMA(close_rsv, 20, 1)
    open_sma = SMA(open_rsv, 20, 1)
    varf = 100 - 3 * close_sma + 2 * SMA(close_sma, 15, 1)
    var10 = 100 - 3 * open_sma + 2 * SMA(open_sma, 15, 1)
    var11 = (varf < REF(var10, 1)) & (V > REF(V, 1)) & (C > REF(C, 1))
    count30 = COUNT(var11, 30)
    values = {
        "VAR3": var3, "VAR4": var4, "VAR5": var5, "VAR6": var6,
        "VAR7": var7, "VAR8": var8, "VAR9": var9, "VARA": vara,
        "VARE": vare, "VARF": varf, "VAR10": var10, "VAR11": var11,
        "VAR11_COUNT30": count30, "底部": vara == 20,
        "大资金潜伏": var11 & (count30 == 1),
    }
    for name, value in values.items():
        ndf[name] = value
    ndf["买信号"] = ndf["底部"] | ndf["大资金潜伏"]
    return ndf


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


def get_bottom_accumulation_buy_point(symbol, df):
    if df is None or len(df) < 120:
        return
    ndf = calculate_indicators(df)
    if ndf is None:
        return

    bottom = ndf["底部"].fillna(False).values
    latent = ndf["大资金潜伏"].fillna(False).values
    buy_signal = bottom | latent
    if not buy_signal.any():
        return

    sig_idxs = []
    for idx in np.where(buy_signal)[0]:
        is_bottom = bool(bottom[idx])
        is_latent = bool(latent[idx])
        if not is_bottom or not is_latent:
            continue
        sl = "+".join([s for s, v in [("底部", is_bottom), ("大资金潜伏", is_latent)] if v])
        print("{} 日期：{} 信号：{} VAR6:{:.2f}".format(symbol, ndf["date"].iloc[idx], sl, float(ndf["VAR6"].iloc[idx])))

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
        is_bottom = bool(bottom[sig_idx])
        is_latent = bool(latent[sig_idx])
        sl = "+".join([s for s, v in [("底部", is_bottom), ("大资金潜伏", is_latent)] if v])
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
            print("{} 开仓 信号:{} 买入:{} 价:{:.2f}  VAR6:{:.2f}".format(
                symbol, all_dates[sig_idx], entry["date"], entry["price"],
                float(ndf["VAR6"].iloc[sig_idx])))
        else:
            days_since = sig_idx - position["last_entry_idx"]
            if days_since <= hold_days:
                position["entries"].append(entry)
                position["last_entry_idx"] = entry["idx"]
                position["close_idx"] = entry["idx"] + hold_days
                avg = sum(e["price"] for e in position["entries"]) / len(position["entries"])
                print("{} 加仓 信号:{} 买入:{} 价:{:.2f} 均价:{:.2f} VAR6:{:.2f}".format(
                    symbol, all_dates[sig_idx], entry["date"], entry["price"], avg,
                    float(ndf["VAR6"].iloc[sig_idx])))
            else:
                max_ret, exit_ret, exit_date = _record_position(symbol, position["entries"], ndf)
                exit_str = "{:.2f}%".format(exit_ret) if exit_ret is not None else "N/A"
                print("{} 平仓 买入:{} 卖出:{} 均价:{:.2f} 持有{}日收益:{} 最大收益:{:.2f}%".format(
                    symbol, position["entries"][0]["date"], exit_date,
                    sum(e["price"] for e in position["entries"]) / len(position["entries"]),
                    hold_days, exit_str, max_ret))
                position = {"entries": [entry], "last_entry_idx": entry["idx"],
                            "close_idx": entry["idx"] + hold_days}
                print("{} 开仓 信号:{} 买入:{} 价:{:.2f}  VAR6:{:.2f}".format(
                    symbol, all_dates[sig_idx], entry["date"], entry["price"],
                    float(ndf["VAR6"].iloc[sig_idx])))

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
    print("  底部 / 大资金潜伏策略 — 分信号类型统计结果")
    print("=" * 70)

    for key in SIGNAL_KEYS:
        _print_signal_header(key)
        _print_signal_stats(key, signal_stats[key])


if __name__ == "__main__":
    # 与参考脚本一致：指定代码时取最新行情；设为空列表时遍历本地数据库。
    test_symbols = []
    start_date = "2020-01-01"
    end_date = '2026-09-28'
    all_symbols = get_daily_symbols()
    test_symbols = []
    total = len(all_symbols)
    if len(test_symbols)>0:
        bs.login()
        end_date = get_latest_trade_date()

    for i, symbol in enumerate(all_symbols):
        # 测试个别股票
        if len(test_symbols)>0:
            if symbol not in test_symbols:
                continue

        print("[{}] 进度：{} / {}".format(
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            # 测试个别股票，获取最新k线
            if len(test_symbols)>0:
                df = get_stock_pd(symbol, start_date, end_date, 'd')
            else:
                df = get_local_stock_data(symbol, start_date)
            get_bottom_accumulation_buy_point(symbol, df)
        except Exception as e:
            continue
        if (i + 1) % 100 == 0:
            print_statistics()
    print_statistics()

    if len(test_symbols)>0:
        # 登出系统
        bs.logout()
