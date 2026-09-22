# coding: utf-8
"""
通达信公式策略回测 — 趋势共振

公式来源：趋势线 + 上下轨 + 放量突破 共振

    均价:=(3*C+H+L+O)/6;
    趋势线:=(8*均价+7*REF(均价,1)+6*REF(均价,2)+5*REF(均价,3)
             +4*REF(均价,4)+3*REF(均价,5)+2*REF(均价,6)+REF(均价,8))/36;
    上轨累和:=(HHV(趋势线,2)+HHV(趋势线,4)+HHV(趋势线,8))/3;
    下轨累和:=(LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3;
    上轨线:=(HHV(上轨累和,2)+HHV(上轨累和,4)+HHV(上轨累和,8))/3;
    下轨线A:=(LLV(下轨累和,2)+LLV(下轨累和,4)+LLV(下轨累和,8))/3;
    下轨线B:=(LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3;
    买入:=REF(下轨线A,1)=REF(趋势线,1) AND 下轨线A<趋势线;
    加仓:=REF(下轨线B,1)=REF(趋势线,1) AND 下轨线B<趋势线;
    强势条件:=C>REF(C,1)*1.03 AND MA(V,5)>MA(V,30);
    突破信号:=CROSS(C,上轨线) AND 强势条件;
    共振买入:=买入 AND 突破信号;
    共振加仓:=加仓 AND 突破信号;
    总共振:=共振买入 OR 共振加仓;
    排除ST:=NOT(NAMELIKE('ST') OR NAMELIKE('*ST') OR CODELIKE('688'));

核心信号：趋势线贴着通道下轨（前一日）后重新上行，且当日放量突破上轨线。
策略逻辑：每个「共振」信号次日开盘买入，持有期内达到 5% 止盈即卖出，
否则持有 hold_days 日后开盘卖出并统计收益。

实现说明：
  1. 下轨线B 与 下轨累和 的公式定义完全相同，属原公式的冗余定义，此处保留同名变量便于逐行对照；
  2. 因为 下轨线B == 下轨累和，且 下轨线A <= 下轨累和 <= 趋势线，买入条件成立时加仓条件
     基本同时成立，所以回测中绝大多数信号是「共振买入+共振加仓」；
  3. 通达信的 = 是浮点相等比较，而 Python 中 (a+a+a)/3 未必精确等于 a（相对误差约 1e-16），
     真实不等的差异在 1e-4 量级，故用 np.isclose 带 1e-9 容差判断，语义等价且不会误判。
"""
import os
import pandas as pd
import numpy as np
import baostock as bs
from lib.MyTT import (
    REF, MA, HHV, LLV, CROSS,
)
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 5
TAKE_PROFIT_RATE = 0.05

# 信号优化：过滤下降趋势、弱 K 线和次日过度跳空，减少追高交易。
USE_OPTIMIZED_SIGNAL = True
ALLOW_OVERLAPPING_TRADES = False
MAX_ENTRY_GAP = 0.03
MIN_PRICE_ABOVE_MA = 0.02
MIN_MA20_SLOPE = 0.005
MAX_SIGNAL_RANGE = 0.08
MIN_CLOSE_POSITION = 0.50
MAX_VOLUME_RATIO = 3.0

# 数据源：
#   "cache"     本地日线缓存 data/.cache（2024-01-01 ~ 2026-09-10，约 25ms/只，全市场约 2 分钟）
#   "sqlite"    本地全历史库 data/sqlite3.db（2000-01-04 ~ 2026-08-31，约 4s/只，全市场约 5 小时）
#   "watchlist" 读取自选股 JSON 后联网取数（需 baostock 登录）
DATA_SOURCE = "cache"
WATCHLIST_FILE = "./data/超跌反弹.json"

# 全市场回测区间（sqlite 数据源可拉到 2000 年；cache 数据源请用 2024-01-01 ~ 2026-09-10）
FULL_START_DATE = "2026-01-01"
FULL_END_DATE = "2026-09-11"
# sqlite 数据源使用的长历史区间
SQLITE_START_DATE = "2000-01-01"

# 是否逐笔打印买卖明细（ADXBreak 参考实现是直接打印的）
VERBOSE_TRADES = True

# 是否跳过持有期不完整的交易
# ADXBreak 参考实现会把出场日夹到数据最后一天，从而产生「持有 0 天、收益 0%」的退化交易
# 并被计入负收益，这里默认跳过，保证统计口径干净；置 False 可还原参考实现的行为
SKIP_INCOMPLETE_TRADES = True

# 浮点相等容差，用于 买入 / 加仓 中的 = 判断
EQUAL_RTOL = 1e-9
EQUAL_ATOL = 1e-12

SIGNAL_KEYS = ["共振买入", "共振加仓", "共振买入+共振加仓", "总计"]

# 逐笔交易明细和组合交易日历，供回测结束后生成逐日资金曲线。
trade_records = []
trading_calendar = set()

# 组合资金曲线参数：每笔交易占入场时组合权益的固定比例。
INIT_CAPITAL = 400000.0
# 当前策略信号较密，2% 可支持约 50 笔并发仓位，避免 5% 仓位下大量跳过交易。
POSITION_SIZE = 0.02
FEE_RATE = 0.0


def _new_stats():
    return {
        "plus": [],
        "minus": [],
        "ratio_map": {x: [] for x in range(1, hold_days + 1)},
        "count": 0,
        "symbols": [],
        "pyramid_counts": [],
        "hold_days_list": [],
        "exit_reasons": {},
        # 每笔交易在持有期内是否曾出现过正收益（用于 5 日正收益占比）。
        "positive_horizon": [],
    }


signal_stats = {k: _new_stats() for k in SIGNAL_KEYS}


# ============================================================
# Indicator calculation
# ============================================================

def calculate_indicators(df):
    """
    计算趋势共振公式全部中间变量与输出信号。
    要求 df 含列: open, high, low, close, volume
    """
    if df is None or len(df) < 60:
        return None
    if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        return None

    ndf = df.copy()
    O = ndf["open"].values.astype(float)
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)
    V = ndf["volume"].values.astype(float)

    # 均价 := (3*C+H+L+O)/6
    avg_price = (3 * C + H + L + O) / 6
    ndf["均价"] = avg_price

    # 趋势线 := (8*均价+7*REF(均价,1)+6*REF(均价,2)+5*REF(均价,3)
    #            +4*REF(均价,4)+3*REF(均价,5)+2*REF(均价,6)+REF(均价,8))/36
    # 注意原公式跳过了 REF(均价,7)，权重 8+7+6+5+4+3+2+1 = 36
    trend = (
        8 * avg_price
        + 7 * REF(avg_price, 1)
        + 6 * REF(avg_price, 2)
        + 5 * REF(avg_price, 3)
        + 4 * REF(avg_price, 4)
        + 3 * REF(avg_price, 5)
        + 2 * REF(avg_price, 6)
        + REF(avg_price, 8)
    ) / 36
    ndf["趋势线"] = trend

    # 上轨累和 := (HHV(趋势线,2)+HHV(趋势线,4)+HHV(趋势线,8))/3
    # 下轨累和 := (LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3
    upper_sum = (HHV(trend, 2) + HHV(trend, 4) + HHV(trend, 8)) / 3
    lower_sum = (LLV(trend, 2) + LLV(trend, 4) + LLV(trend, 8)) / 3
    ndf["上轨累和"] = upper_sum
    ndf["下轨累和"] = lower_sum

    # 上轨线 := (HHV(上轨累和,2)+HHV(上轨累和,4)+HHV(上轨累和,8))/3
    upper_line = (HHV(upper_sum, 2) + HHV(upper_sum, 4) + HHV(upper_sum, 8)) / 3
    # 下轨线A := (LLV(下轨累和,2)+LLV(下轨累和,4)+LLV(下轨累和,8))/3
    lower_line_a = (LLV(lower_sum, 2) + LLV(lower_sum, 4) + LLV(lower_sum, 8)) / 3
    # 下轨线B := (LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3，与下轨累和完全相同
    lower_line_b = lower_sum
    ndf["上轨线"] = upper_line
    ndf["下轨线A"] = lower_line_a
    ndf["下轨线B"] = lower_line_b

    # 买入 := REF(下轨线A,1)=REF(趋势线,1) AND 下轨线A<趋势线
    # 加仓 := REF(下轨线B,1)=REF(趋势线,1) AND 下轨线B<趋势线
    with np.errstate(invalid='ignore'):
        buy = np.isclose(REF(lower_line_a, 1), REF(trend, 1),
                         rtol=EQUAL_RTOL, atol=EQUAL_ATOL) & (lower_line_a < trend)
        add = np.isclose(REF(lower_line_b, 1), REF(trend, 1),
                         rtol=EQUAL_RTOL, atol=EQUAL_ATOL) & (lower_line_b < trend)
    ndf["买入"] = buy
    ndf["加仓"] = add

    # 强势条件 := C>REF(C,1)*1.03 AND MA(V,5)>MA(V,30)
    strong = (C > REF(C, 1) * 1.03) & (MA(V, 5) > MA(V, 30))
    ndf["强势条件"] = strong

    # 趋势与 K 线过滤器只使用信号日及之前的数据，避免引入未来函数。
    ma20 = MA(C, 20)
    ma60 = MA(C, 60)
    ma20_prev5 = REF(ma20, 5)
    candle_range = np.divide(
        H - L, C,
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(C) > 1e-12,
    )
    close_position = np.divide(
        C - L, H - L,
        out=np.full(len(ndf), 0.5, dtype=float),
        where=(H - L) > 1e-12,
    )
    volume_prev = REF(V, 1)
    volume_ratio = np.divide(
        V, volume_prev,
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(volume_prev) > 1e-12,
    )
    trend_filter = (
        (C > ma20 * (1 + MIN_PRICE_ABOVE_MA))
        & (C > ma60 * (1 + MIN_PRICE_ABOVE_MA))
        & (ma20 > ma20_prev5 * (1 + MIN_MA20_SLOPE))
    )
    candle_filter = (
        (C > O)
        & (close_position >= MIN_CLOSE_POSITION)
        & (candle_range <= MAX_SIGNAL_RANGE)
        & (volume_ratio <= MAX_VOLUME_RATIO)
    )
    ndf["MA20"] = ma20
    ndf["MA60"] = ma60
    ndf["MA20斜率"] = np.divide(
        ma20 - ma20_prev5, ma20_prev5,
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(ma20_prev5) > 1e-12,
    )
    ndf["信号振幅"] = candle_range
    ndf["收盘位置"] = close_position
    ndf["信号量比"] = volume_ratio
    ndf["趋势过滤"] = trend_filter
    ndf["K线过滤"] = candle_filter

    # 突破信号 := CROSS(C,上轨线) AND 强势条件
    breakout = CROSS(C, upper_line) & strong
    ndf["突破信号"] = breakout
    optimized_breakout = breakout & trend_filter & candle_filter
    ndf["突破信号优化"] = optimized_breakout

    # 共振买入 := 买入 AND 突破信号；共振加仓 := 加仓 AND 突破信号
    resonance_buy = buy & breakout
    resonance_add = add & breakout
    ndf["共振买入"] = resonance_buy
    ndf["共振加仓"] = resonance_add
    ndf["总共振"] = resonance_buy | resonance_add
    ndf["共振买入优化"] = buy & optimized_breakout
    ndf["共振加仓优化"] = add & optimized_breakout
    ndf["总共振优化"] = ndf["共振买入优化"] | ndf["共振加仓优化"]

    return ndf


def _signal_label(is_buy, is_add):
    """根据当日的共振类型拼出信号标签"""
    labels = []
    if is_buy:
        labels.append("共振买入")
    if is_add:
        labels.append("共振加仓")
    return "+".join(labels)


# ============================================================
# 股票名称 / 排除ST
# ============================================================

_name_map = None


def _get_name_map():
    """一次性载入 sh_sz_stock.json，避免全市场回测时反复读盘"""
    global _name_map
    if _name_map is None:
        symbol_file = os.path.join(get_data_dir(), 'sh_sz_stock.json')
        result = read_json(symbol_file)
        _name_map = {}
        for item in result:
            for code, name in item.items():
                _name_map[code] = name
    return _name_map


def get_symbol_name(symbol):
    """获取股票名称，等价于 get_symbols_name 但带缓存"""
    return _get_name_map().get(symbol, 'UNKNOWN')


def is_excluded_symbol(symbol):
    """
    排除 ST / *ST / 科创板(688)，对应公式：
        排除ST := NOT(NAMELIKE('ST') OR NAMELIKE('*ST') OR CODELIKE('688'));
    """
    code = symbol.split('.')[-1]
    if code.startswith('688'):
        return True
    return 'ST' in get_symbol_name(symbol).upper()


# ============================================================
# Trade recording
# ============================================================

def _record_trade(symbol, entry_idx, exit_idx, df, label="总计"):
    """
    记录一次完整的买卖交易

    买入价为信号次日开盘价。持有期内若开盘价或收盘价达到止盈价，
    分别按当日开盘价或收盘价卖出；未触发时按计划到期日开盘价卖出。
    同时计入对应信号类型和「总计」两组统计。
    """
    entry_price = float(df["open"].iloc[entry_idx])
    price_base = entry_price if abs(entry_price) > 1e-12 else 1e-10

    stats_list = [signal_stats[label]]
    if label != "总计":
        stats_list.append(signal_stats["总计"])

    max_val = -1000.0
    exit_reason = None
    actual_exit_idx = None
    actual_exit_price = None
    target_price = entry_price * (1 + TAKE_PROFIT_RATE)

    for day_offset in range(1, hold_days + 1):
        check_idx = entry_idx + day_offset
        if check_idx >= len(df):
            break
        check_open = float(df["open"].iloc[check_idx])
        check_close = float(df["close"].iloc[check_idx])
        ratio = round(100 * (check_close - entry_price) / price_base, 2)
        for s in stats_list:
            s["ratio_map"][day_offset].append(ratio)
        max_val = max(max_val, ratio)

        # 日内无法知道收盘前走势，因此先处理开盘跳空止盈，再处理收盘止盈。
        if check_open >= target_price:
            actual_exit_idx = check_idx
            actual_exit_price = check_open
            exit_reason = "开盘止盈"
            break
        if check_close >= target_price:
            actual_exit_idx = check_idx
            actual_exit_price = check_close
            exit_reason = "收盘止盈"
            break

    if actual_exit_idx is None:
        if exit_idx >= len(df):
            if SKIP_INCOMPLETE_TRADES:
                return None
            actual_exit_idx = len(df) - 1
        else:
            actual_exit_idx = exit_idx
        actual_exit_price = float(df["open"].iloc[actual_exit_idx])
        exit_reason = "到期开盘"

    exit_price = float(actual_exit_price)
    ret = (exit_price - entry_price) / price_base * 100
    max_val = max(max_val, ret)

    for s in stats_list:
        (s["plus"] if ret > 0 else s["minus"]).append(ret)
        s["count"] += 1
        s["symbols"].append(symbol)
        s["hold_days_list"].append(actual_exit_idx - entry_idx)
        s["exit_reasons"][exit_reason] = s["exit_reasons"].get(exit_reason, 0) + 1
        s["positive_horizon"].append(max_val > 0)

    # 保存持有期收盘价，组合曲线按每日收盘对未平仓头寸估值。
    marks = {df["date"].iloc[d]: float(df["close"].iloc[d])
             for d in range(entry_idx, actual_exit_idx + 1)}
    trade_records.append({
        "symbol": symbol,
        "entry_date": df["date"].iloc[entry_idx],
        "exit_date": df["date"].iloc[actual_exit_idx],
        "entry_price": entry_price,
        "exit_price": exit_price,
        "ret": ret,
        "kind": exit_reason,
        "marks": marks,
    })

    return entry_price, exit_price, ret, max_val, exit_reason, actual_exit_idx


# ============================================================
# Buy/sell point detection
# ============================================================

def get_buy_point(symbol, df):
    """
    单只股票回测：每个共振信号独立开仓（不做持仓合并 / 加仓管理），
    买入次日开盘，持有期内达到 5% 止盈即卖出，否则到期日开盘卖出。
    """
    if df is None or len(df) < 60:
        return
    ndf = calculate_indicators(df)
    if ndf is None:
        return

    trading_calendar.update(ndf["date"].tolist())

    # 排除 ST / 科创板
    if is_excluded_symbol(symbol):
        return

    buy_col = "共振买入优化" if USE_OPTIMIZED_SIGNAL else "共振买入"
    add_col = "共振加仓优化" if USE_OPTIMIZED_SIGNAL else "共振加仓"
    rb = ndf[buy_col].fillna(False).values
    ra = ndf[add_col].fillna(False).values
    buy_signal = rb | ra

    if not buy_signal.any():
        return

    buy_idxs = list(np.where(buy_signal)[0])
    all_dates = ndf["date"].values

    last_signal_idx = -10**9
    for idx in buy_idxs:
        if idx + 1 >= len(df):
            continue
        if (not ALLOW_OVERLAPPING_TRADES and
                idx - last_signal_idx <= hold_days):
            continue
        entry_idx = idx + 1
        exit_idx = entry_idx + hold_days

        # 次日跳空过大时放弃入场，避免把突破溢价当成策略收益。
        signal_close = float(ndf["close"].iloc[idx])
        entry_price = float(ndf["open"].iloc[entry_idx])
        if (USE_OPTIMIZED_SIGNAL and
                (signal_close <= 0 or entry_price > signal_close * (1 + MAX_ENTRY_GAP))):
            continue

        label = _signal_label(bool(rb[idx]), bool(ra[idx]))
        trade = _record_trade(symbol, entry_idx, exit_idx, ndf, label)
        if trade is None:
            continue
        last_signal_idx = idx
        entry_price, exit_price, ret, max_val, exit_reason, actual_exit_idx = trade
        if VERBOSE_TRADES:
            print("{} 买 信号日:{} [{}] 买入:{} 价:{:.2f} {} 卖出:{} 价:{:.2f} 收益:{:.2f}% 最大:{:.2f}%".format(
                symbol, all_dates[idx], label, all_dates[entry_idx], entry_price,
                exit_reason, all_dates[actual_exit_idx], exit_price, ret, max_val))


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
    print("  最终正收益次数：{}  负收益次数：{}".format(len(plus), len(minus)))
    positive_horizon = stats.get("positive_horizon", [])
    if len(positive_horizon) == total:
        horizon_plus = sum(bool(x) for x in positive_horizon)
        print("  5日内曾正收益次数：{}".format(horizon_plus))
        print("  正收益占比：{:.2f}%".format(100 * horizon_plus / total))
    else:
        print("  正收益占比：{:.2f}%".format(100 * len(plus) / total))

    all_returns = np.array(plus + minus)
    print("  平均收益：{:.2f}%".format(np.mean(all_returns)))
    print("  总的正收益：{:.2f}%  正收益均值：{:.2f}%".format(sum(plus), np.mean(plus) if plus else 0))
    print("  总的负收益：{:.2f}%  负收益均值：{:.2f}%".format(sum(minus), np.mean(minus) if minus else 0))
    print("  最大收益：{:.2f}%  最小收益：{:.2f}%".format(np.max(all_returns), np.min(all_returns)))
    print("  中位数收益：{:.2f}%".format(np.median(all_returns)))
    print("  95% 分位数：{:.2f}%".format(np.percentile(all_returns, 95)))
    print("  5% 分位数：{:.2f}%".format(np.percentile(all_returns, 5)))

    print()
    print("  涉及股票数：{}".format(len(set(stats["symbols"]))))

    if stats["hold_days_list"]:
        hd = np.array(stats["hold_days_list"])
        print("  持有天数: 最大={:.0f}  最小={:.0f}  平均={:.1f}".format(
            np.max(hd), np.min(hd), np.mean(hd)))

    if stats.get("exit_reasons"):
        print()
        print("  --- 卖出原因 ---")
        for reason, count in stats["exit_reasons"].items():
            print("  {}：{} 次 ({:.1f}%)".format(reason, count, 100 * count / total))

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
    print("  趋势共振策略 — 统计结果")
    print("=" * 70)

    for key in SIGNAL_KEYS:
        _print_signal_header(key)
        _print_signal_stats(key, signal_stats[key])


# ============================================================
# 组合资金曲线：等权、逐日结算
# ============================================================

def simulate_portfolio(records=None, position_size=POSITION_SIZE, fee_rate=FEE_RATE,
                       init_capital=INIT_CAPITAL, save_path=None):
    """将逐笔交易合成为组合逐日资金曲线，并可保存为 CSV。"""
    records = trade_records if records is None else records
    if not records:
        print("\n没有交易记录，无法生成资金曲线")
        return None

    # 保留交易区间内的所有交易日，使无持仓日期也参与年化、夏普和回撤计算。
    lo = min(r["entry_date"] for r in records)
    hi = max(r["exit_date"] for r in records)
    if trading_calendar:
        days = sorted(d for d in trading_calendar if lo <= d <= hi)
    else:
        days = sorted({d for r in records for d in r["marks"]})
    new_trades = {}
    for record in records:
        new_trades.setdefault(record["entry_date"], []).append(record)

    cash = float(init_capital)
    open_positions = []
    curve = []
    skipped, reduced = 0, 0
    invested_sum = 0.0

    for day in days:
        # 先结算今日卖出，再处理今日开盘买入，允许同日资金周转。
        keep = []
        for pos in open_positions:
            if pos["rec"]["exit_date"] == day:
                cash += pos["shares"] * pos["rec"]["exit_price"] * (1 - fee_rate)
            else:
                keep.append(pos)
        open_positions = keep

        for record in new_trades.get(day, []):
            equity_now = cash + sum(p["shares"] * p["last_close"] for p in open_positions)
            alloc = equity_now * position_size
            if alloc <= 0 or cash <= 1e-9:
                skipped += 1
                continue
            if cash < alloc:
                alloc = cash
                reduced += 1
            shares = alloc / record["entry_price"] / (1 + fee_rate)
            cash -= shares * record["entry_price"] * (1 + fee_rate)
            open_positions.append({
                "rec": record,
                "shares": shares,
                "last_close": record["entry_price"],
            })

        market_value = 0.0
        for pos in open_positions:
            close = pos["rec"]["marks"].get(day)
            if close is not None:
                pos["last_close"] = close
            market_value += pos["shares"] * pos["last_close"]

        equity = cash + market_value
        curve.append({
            "date": day,
            "equity": equity,
            "cash": cash,
            "market_value": market_value,
            "positions": len(open_positions),
        })
        if equity > 0:
            invested_sum += market_value / equity

    if not curve:
        print("\n没有有效交易日，无法生成资金曲线")
        return None

    eq = np.array([item["equity"] for item in curve], dtype=float)
    total_ret = eq[-1] / init_capital - 1
    with np.errstate(divide="ignore", invalid="ignore"):
        daily = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([])
    daily = daily[np.isfinite(daily)]
    years = len(eq) / 252.0
    annual = ((eq[-1] / init_capital) ** (1 / years) - 1
              if years > 0 and eq[-1] > 0 else float("nan"))
    max_dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    sharpe = (float(daily.mean() / daily.std() * np.sqrt(252))
              if len(daily) and daily.std() > 0 else float("nan"))
    max_pos = max(item["positions"] for item in curve)

    print("\n" + "=" * 80)
    print("组合资金曲线（等权、逐日结算）")
    print("=" * 80)
    print("初始资金：{:.0f}    单笔仓位：入场时权益的 {:.1%}    单边手续费：{:.4%}".format(
        init_capital, position_size, fee_rate))
    print("回测区间：{} ~ {}（{} 个交易日）".format(curve[0]["date"], curve[-1]["date"], len(curve)))
    print("期末权益：{:.2f}".format(eq[-1]))
    print("组合总收益：{:.2f}%".format(total_ret * 100))
    print("年化收益：{:.2f}%".format(annual * 100))
    print("最大回撤：{:.2f}%".format(max_dd * 100))
    print("日收益夏普：{:.2f}".format(sharpe))
    print("最大同时持仓：{} 笔    平均资金占用：{:.1f}%".format(
        max_pos, invested_sum / len(curve) * 100))
    if reduced:
        print("因现金不足被缩减仓位的交易：{} 笔".format(reduced))
    if skipped:
        print("因现金不足被跳过的交易：{} 笔".format(skipped))

    if save_path:
        pd.DataFrame(curve).to_csv(save_path, index=False, encoding="utf-8-sig")
        print("资金曲线已保存到 {}".format(save_path))
    return curve


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    all_symbols = get_daily_symbols()
    total = len(all_symbols)

    test_symbols = []
    start_date, end_date = FULL_START_DATE, FULL_END_DATE
    use_bs = False

    if DATA_SOURCE == "watchlist":
        test_symbols = read_json(WATCHLIST_FILE)
        start_date = SQLITE_START_DATE
        if len(test_symbols) > 0:
            bs.login()
            end_date = get_latest_trade_date()
            use_bs = True
    elif DATA_SOURCE == "sqlite":
        start_date = SQLITE_START_DATE

    print("数据源：{}  区间：{} ~ {}  股票数：{}".format(
        DATA_SOURCE, start_date, end_date,
        len(test_symbols) if test_symbols else total))
    print("信号模式：{}  重叠持仓：{}  次日最大跳空：{:.1%}".format(
        "优化" if USE_OPTIMIZED_SIGNAL else "原始",
        "允许" if ALLOW_OVERLAPPING_TRADES else "过滤",
        MAX_ENTRY_GAP))

    for i, symbol in enumerate(all_symbols):
        if test_symbols and symbol not in test_symbols:
            continue

        print("[{}] 进度：{} / {}".format(
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            if DATA_SOURCE == "sqlite":
                df = get_local_stock_data(symbol, start_date)
            else:
                df = get_stock_pd(symbol, start_date, end_date, "d")
            get_buy_point(symbol, df)
        except Exception:
            continue
        if (i + 1) % 100 == 0:
            print_statistics()
    print_statistics()

    # 输出组合资金曲线及逐日明细。
    simulate_portfolio(save_path=os.path.join(get_data_dir(), "trend_resonance_equity.csv"))

    if use_bs:
        bs.logout()
