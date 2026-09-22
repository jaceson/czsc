# coding: utf-8
"""通达信公式策略：控盘 / 抄底。

买点仅使用同日同时出现的 ``X_QQ``（控盘）与
``BARSLASTCOUNT(X_CQ)=1``（抄底）共振信号，单独信号全部屏蔽。
信号次日开盘买入，T+1 起按开盘/收盘检查 +5% 止盈、-5% 止损，
出现正收益后，按持仓峰值价格回撤 STOP_LOSS_RATE 移动止损；未触发则第五个交易日开盘退出。

默认扫描全市场每只股票最后一根 K 线的共振信号，打印行情并保存到
``data/控盘抄底_最新信号.json``；将 ``RUN_BACKTEST`` 设为 True 可同时执行回测。

动态周期函数按当前 K 线向前取值；公式中的 CONST 使用当前值，避免将
最后一根 K 线的控制线回填到历史数据。
"""
import os
import numpy as np
import pandas as pd
import baostock as bs
from concurrent.futures import ProcessPoolExecutor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from lib.MyTT import REF, SMA, MA, HHV, LLV, BARSLAST, BARSLASTCOUNT, BETWEEN, COUNT
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 5
TAKE_PROFIT_RATE = 0.2
STOP_LOSS_RATE = -0.03
INIT_CAPITAL = 1000000.0
POSITION_SIZE = 0.1
FEE_RATE = 0.0
DATA_SOURCE = "cache" #sqlite\cache
FULL_START_DATE = "2024-01-01"
FULL_END_DATE = "2026-09-11"
SQLITE_START_DATE = "2024-01-01"
WATCHLIST_FILE = "./data/超跌反弹.json"
VERBOSE_TRADES = True
SKIP_INCOMPLETE_TRADES = True
ALLOW_OVERLAPPING_TRADES = False
EXCLUDE_ST_688 = True
# 默认先扫描最新交易日，完整回测仍可通过开关启用。
RUN_LAST_DAY_SCAN = True
RUN_BACKTEST = False
LAST_DAY_OUTPUT = "控盘抄底_最新信号.json"

BASE_SIGNAL_KEYS = ["控盘+抄底"]
SIGNAL_KEYS = BASE_SIGNAL_KEYS.copy()
signal_stats = {}
trade_records = []
trading_calendar = set()
# 最后一根 K 线出现共振信号的股票，供交互式调用和主流程输出。
last_day_signals = []


def _new_stats():
    return {
        "plus": [], "minus": [],
        "ratio_map": {d: [] for d in range(1, hold_days + 1)},
        "count": 0, "symbols": [], "hold_days_list": [],
        "exit_reasons": {}, "positive_horizon": [],
    }


def reset_stats():
    global signal_stats, trade_records, trading_calendar, last_day_signals
    SIGNAL_KEYS[:] = BASE_SIGNAL_KEYS
    signal_stats = {key: _new_stats() for key in SIGNAL_KEYS}
    trade_records = []
    trading_calendar = set()
    last_day_signals = []


reset_stats()


_name_map = None


def get_symbol_name(symbol):
    global _name_map
    if _name_map is None:
        _name_map = {}
        try:
            for item in (read_json(os.path.join(get_data_dir(), "sh_sz_stock.json")) or []):
                if isinstance(item, dict):
                    _name_map.update(item)
        except Exception:
            pass
    return _name_map.get(symbol, "UNKNOWN")


def is_excluded_symbol(symbol):
    code = str(symbol).split(".")[-1]
    return EXCLUDE_ST_688 and (code.startswith("688") or "ST" in get_symbol_name(symbol).upper())


def _dynamic_count(condition, periods):
    """COUNT(condition, periods[i])，N=0 时按通达信累计到当前 K 线统计。"""
    condition = np.asarray(condition, dtype=bool)
    periods = np.asarray(periods, dtype=float)
    cumulative = np.concatenate(([0.0], np.cumsum(condition, dtype=float)))
    result = np.zeros(len(condition), dtype=float)
    for i, period in enumerate(periods):
        if not np.isfinite(period):
            continue
        width = int(period)
        if width <= 0:
            result[i] = cumulative[i + 1]
        else:
            result[i] = cumulative[i + 1] - cumulative[max(0, i - width + 1)]
    return result


def _dynamic_ref(values, periods):
    values = np.asarray(values, dtype=float)
    periods = np.asarray(periods, dtype=float)
    result = np.full(len(values), np.nan)
    for i, period in enumerate(periods):
        if np.isfinite(period) and period >= 0:
            j = i - int(period)
            if j >= 0:
                result[i] = values[j]
    return result


def _dynamic_extreme(values, periods, mode):
    """Variable-window HHV/LLV using a sparse table for exact range queries."""
    values = np.asarray(values, dtype=float)
    periods = np.asarray(periods, dtype=float)
    n = len(values)
    result = np.full(n, np.nan)
    if n == 0:
        return result

    finite = np.isfinite(values)
    fill_value = np.inf if mode == "min" else -np.inf
    base = np.where(finite, values, fill_value)
    tables = [base]
    span = 1
    while span * 2 <= n:
        previous = tables[-1]
        if mode == "min":
            current = np.minimum(previous[:-span], previous[span:])
        else:
            current = np.maximum(previous[:-span], previous[span:])
        tables.append(current)
        span *= 2

    periods_int = np.where(np.isfinite(periods), periods, -1).astype(np.int64)
    ends = np.arange(n, dtype=np.int64)
    starts = np.where(periods_int <= 0, 0, np.maximum(0, ends - periods_int + 1))
    valid = periods_int >= 0
    lengths = ends - starts + 1
    logs = np.zeros(n + 1, dtype=np.int64)
    logs[1:] = np.floor(np.log2(np.arange(1, n + 1))).astype(np.int64)
    for level in np.unique(logs[lengths[valid]]):
        mask = valid & (logs[lengths] == level)
        if not mask.any():
            continue
        width = 1 << int(level)
        left = tables[level][starts[mask]]
        right = tables[level][ends[mask] - width + 1]
        result[mask] = np.minimum(left, right) if mode == "min" else np.maximum(left, right)
    result[~np.isfinite(result)] = np.nan
    return result


def _safe_ratio(numerator, denominator):
    return np.divide(numerator, denominator, out=np.full(len(numerator), np.nan),
                     where=np.abs(denominator) > 1e-12)


def calculate_indicators(df):
    """计算公式变量并返回控盘、抄底及仅保留共振的交易信号。"""
    required = {"date", "open", "high", "low", "close", "volume"}
    if df is None or len(df) < 60 or not required.issubset(df.columns):
        return None
    ndf = df.copy()
    ndf["date"] = pd.to_datetime(ndf["date"], errors="raise").dt.normalize()
    ndf = ndf.sort_values("date").reset_index(drop=True)
    if ndf["date"].duplicated().any():
        raise ValueError("行情日期存在重复值")
    O = ndf["open"].to_numpy(dtype=float)
    H = ndf["high"].to_numpy(dtype=float)
    L = ndf["low"].to_numpy(dtype=float)
    C = ndf["close"].to_numpy(dtype=float)
    V = ndf["volume"].to_numpy(dtype=float)
    if not all(np.isfinite(x).all() for x in (O, H, L, C, V)) or (C <= 0).any():
        raise ValueError("行情数据必须是有限数值，收盘价必须为正")

    X_2B = C < O
    X_3H = np.maximum.accumulate(H)  # HHV(H,0)
    X_UF = LLV(L, 60)
    X_3D = O - L
    X_0N = X_2B & (np.cumsum(X_2B) == 4)  # COUNT(X_2B,0)=4
    X_D2 = BARSLAST(X_0N)
    X_ST = REF(H, 10)
    X_VM = np.floor(X_D2 / 6)
    X_K2 = BARSLASTCOUNT(X_VM == REF(X_VM, 1)) == 5
    X_D9 = REF(H, 5)
    X_RP = (X_0N | X_K2) & (X_D2 >= 0)
    X_LO = np.isclose(C, np.round(REF(C, 1) * 1.1, 2), atol=0.011, equal_nan=False)
    X_DI = MA(V, 1)
    X_GJ = np.isclose(H, np.round(REF(C, 1) * 1.1, 2), atol=0.011, equal_nan=False) & (C < H)
    X_QH = np.isclose(C, np.round(REF(C, 1) * 1.2, 2), atol=0.011, equal_nan=False)
    X_IB = MA(V, 9)
    X_R5 = np.isclose(H, np.round(REF(C, 1) * 1.2, 2), atol=0.011, equal_nan=False) & (C < H)
    IND_3OR = REF(C, 43)
    IND_G4R = SMA(C, 5, 1)
    X_NE = np.full(len(C), 47.0)
    IND_SZU = HHV(H, 59)
    IND_K64 = pd.Series(C).ewm(span=59, adjust=False).mean().to_numpy()
    IND_KJ2 = MA(C, 20)
    X_OF = MA(V, 5)
    X_V4 = C
    X_CK = REF(H, 1)
    X_NM = np.isclose(C, LLV(C, 60), equal_nan=False)
    X_BA = BARSLAST(X_NM)
    X_G2 = _dynamic_ref(C, X_BA)
    X_12 = O - L
    X_RQ = BETWEEN(X_BA, 1, 60) & (_safe_ratio(C, REF(C, 1)) > 1.043)
    X_C3 = REF(H, 3)
    X_UY = X_RQ & (_dynamic_count(X_RQ, X_BA) == 1)
    X_D6 = np.full(len(C), 72.0)
    X_Z8 = BARSLAST(X_UY)
    X_WY = _dynamic_ref(C, X_Z8)
    X_OO = C
    X_ZO = np.isclose(C, _dynamic_extreme(C, X_Z8, "min"), equal_nan=False)
    X_Z6 = BARSLAST(X_ZO)
    X_8I = C
    X_MD = (X_Z6 == 1) & (C > _dynamic_ref(C, X_Z6)) & (H > L)
    X_AF = np.full(len(C), "")
    X_RT = O - L
    IND_3YQ = MA(C, 10) - MA(C, 32)
    IND_EHX = REF(C, 55)
    IND_PP4 = MA(C, 38)
    IND_NX1 = _safe_ratio(H - L, C) * 100
    X_46 = C
    IND_4FS = pd.Series(C).ewm(span=31, adjust=False).mean().to_numpy()
    X_56 = MA(V, 8)
    X_LT = _dynamic_count(X_MD, X_Z8) == 1
    X_ZV = BARSLAST(X_LT & X_MD)
    X_7O = _dynamic_count(X_MD, X_Z8) == 2
    X_EC = BARSLAST(X_7O & X_MD)
    X_2Q = _dynamic_count(X_MD, X_Z8) == 3
    X_75 = BARSLAST(X_2Q & X_MD)
    X_CQ = _dynamic_count(X_MD, X_Z8) > 3
    X_TX = _dynamic_ref(C, X_ZV)
    X_49 = _dynamic_ref(C, X_EC)
    X_1V = _dynamic_ref(C, X_75)
    X_3Z = np.fmax(X_TX, X_49)
    X_0L = np.fmax(X_3Z, X_1V)
    X_RG = np.where(X_LT, X_TX, 0)
    X_EY = np.where(X_7O, X_3Z, 0)
    X_ZW = np.where(X_2Q, X_0L, 0)
    X_S3 = X_RG + X_EY + X_ZW
    # CONST(X_S3) 的历史因果实现：使用当前时点的 X_S3。
    X_A7 = X_S3
    X_5G = (C >= X_A7) & (_safe_ratio(C, REF(C, 1)) > 1.043)
    X_QQ = (_dynamic_count(X_5G, X_Z8) == 1) & X_5G
    bottom_signal = BARSLASTCOUNT(X_CQ) == 1
    total_signal = X_QQ | bottom_signal

    values = locals()
    for key in ("X_2B", "X_3H", "X_UF", "X_3D", "X_0N", "X_D2", "X_ST", "X_VM",
                "X_K2", "X_D9", "X_RP", "X_LO", "X_DI", "X_GJ", "X_QH", "X_IB",
                "X_R5", "IND_3OR", "IND_G4R", "X_NE", "IND_SZU", "IND_K64", "IND_KJ2",
                "X_OF", "X_V4", "X_CK", "X_NM", "X_BA", "X_G2", "X_12", "X_RQ",
                "X_C3", "X_UY", "X_D6", "X_Z8", "X_WY", "X_OO", "X_ZO", "X_Z6",
                "X_8I", "X_MD", "X_AF", "X_RT", "IND_3YQ", "IND_EHX", "IND_PP4",
                "IND_NX1", "X_46", "IND_4FS", "X_56", "X_LT", "X_ZV", "X_7O", "X_EC",
                "X_2Q", "X_75", "X_CQ", "X_TX", "X_49", "X_1V", "X_3Z", "X_0L",
                "X_RG", "X_EY", "X_ZW", "X_S3", "X_A7", "X_5G", "X_QQ"):
        ndf[key] = values[key]
    ndf["控盘"] = X_QQ
    ndf["抄底"] = bottom_signal
    # 仅保留同日同时出现的控盘+抄底共振信号；单独信号不参与交易。
    ndf["控盘+抄底"] = X_QQ & bottom_signal
    ndf["总信号"] = ndf["控盘+抄底"]
    return ndf


def _extract_last_day_signal(symbol, ndf):
    """提取单只股票最后一个交易日的共振信号及行情数据。

    信号必须出现在该股票数据的最后一根 K 线上，避免把历史信号误当成
    当前信号。返回值只使用 Python 标量，因而可以直接写入 JSON。
    """
    if ndf is None or len(ndf) == 0:
        return None

    row = ndf.iloc[-1]

    def _bool_value(value):
        if value is None or pd.isna(value):
            return False
        return bool(value)

    if not _bool_value(row.get("总信号", row.get("控盘+抄底", False))):
        return None

    def _bool(name):
        return _bool_value(row.get(name, False))

    def _number(name, default=np.nan):
        value = row.get(name, default)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return round(value, 6) if np.isfinite(value) else None

    date = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
    open_price = _number("open")
    close_price = _number("close")
    change_pct = None
    if open_price and close_price is not None:
        change_pct = round((close_price / open_price - 1) * 100, 2)

    return {
        "symbol": str(symbol),
        "name": get_symbol_name(symbol),
        "date": date,
        "signal": "控盘+抄底",
        "控盘": _bool("控盘"),
        "抄底": _bool("抄底"),
        "控盘+抄底": _bool("控盘+抄底"),
        "open": open_price,
        "high": _number("high"),
        "low": _number("low"),
        "close": close_price,
        "volume": _number("volume"),
        "amount": _number("amount"),
        "turn": _number("turn"),
        "change_pct": change_pct,
        # 保留关键公式变量，便于复核信号和后续选股排序。
        "X_QQ": _bool("X_QQ"),
        "X_CQ": _bool("X_CQ"),
        "X_S3": _number("X_S3"),
        "X_A7": _number("X_A7"),
        "X_5G": _bool("X_5G"),
        "X_Z8": _number("X_Z8"),
    }


def get_last_day_signals(symbol, df):
    """计算指标并返回最后一个交易日的共振信号。"""
    if df is None or is_excluded_symbol(symbol):
        return None
    try:
        ndf = calculate_indicators(df)
        return _extract_last_day_signal(symbol, ndf)
    except (KeyError, TypeError, ValueError, IndexError, FloatingPointError):
        return None


def print_last_day_signals(signals):
    """打印最后一个交易日出现控盘+抄底信号的股票及行情数据。"""
    print("\n" + "=" * 128)
    print("  最后一个交易日出现控盘+抄底信号的股票")
    print("=" * 128)
    if not signals:
        print("  无信号\n")
        return

    ordered = sorted(signals, key=lambda item: (item.get("date", ""), item.get("symbol", "")))
    header = (
        "{:<12}{:<10}{:<12}{:<14}{:>9}{:>9}{:>9}{:>9}{:>12}{:>10}"
        .format("代码", "名称", "日期", "信号", "开盘", "最高", "最低", "收盘", "成交量", "涨跌%")
    )
    print(header)
    print("-" * 128)
    for item in ordered:
        def _fmt(value, digits=2):
            return "--" if value is None else format(float(value), ".{}f".format(digits))

        print(
            "{:<12}{:<10}{:<12}{:<14}{:>9}{:>9}{:>9}{:>9}{:>12}{:>10}".format(
                item.get("symbol", ""), item.get("name", "UNKNOWN")[:8], item.get("date", ""),
                item.get("signal", ""), _fmt(item.get("open")), _fmt(item.get("high")),
                _fmt(item.get("low")), _fmt(item.get("close")), _fmt(item.get("volume"), 0),
                _fmt(item.get("change_pct")),
            )
        )
    print("-" * 128)
    print("  共 {} 只股票出现信号\n".format(len(ordered)))


def _bs_login_init():
    """进程池初始化；缓存模式下登录失败不影响本地数据扫描。"""
    try:
        bs.login()
    except Exception:
        pass


def _scan_worker(args):
    symbol, start_date, end_date, data_source = args
    try:
        if data_source == "sqlite":
            df = get_local_stock_data(symbol, start_date, end_date, "d")
        else:
            df = get_stock_pd(symbol, start_date, end_date, "d")
        return get_last_day_signals(symbol, df)
    except Exception:
        # 单只股票数据异常不应中断全市场扫描。
        return None


def scan_last_day_signals(symbols, start_date, end_date, workers=None):
    """扫描全市场，返回各股票最后一根 K 线出现的共振信号。"""
    symbols = list(symbols or [])
    if workers is None:
        workers = min(os.cpu_count() or 1, 4)
    workers = max(1, int(workers))
    if not symbols:
        return []

    print("[{}] 开始扫描 {} 只股票（{} 进程）……".format(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), len(symbols), workers))
    results = []
    # 显式传递数据源，兼容 macOS spawn 模式下子进程不继承运行时全局变量。
    args = [(symbol, start_date, end_date, DATA_SOURCE) for symbol in symbols]
    with ProcessPoolExecutor(max_workers=workers, initializer=_bs_login_init) as executor:
        for index, result in enumerate(executor.map(_scan_worker, args), 1):
            if result is not None:
                results.append(result)
            if index % 100 == 0 or index == len(args):
                print("[{}] 扫描进度：{} / {}".format(
                    pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), index, len(args)))

    results.sort(key=lambda item: (item.get("date", ""), item.get("symbol", "")))
    print("[{}] 扫描完成，共 {} 只股票出现信号".format(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), len(results)))
    return results


def _record_trade(symbol, entry_idx, exit_idx, df, label):
    entry = float(df["open"].iloc[entry_idx])
    if not np.isfinite(entry) or entry <= 0:
        return None
    target, stop = entry * (1 + TAKE_PROFIT_RATE), entry * (1 + STOP_LOSS_RATE)
    actual_idx = actual_price = None
    reason = None
    stats = [signal_stats[label]]
    daily = []
    # 记录持仓期间的最高正收益。回撤止损按峰值价格的相对跌幅计算；
    # 未出现过正收益前，仍执行固定入场价止损。
    peak_price = entry
    peak_return = 0.0
    for offset in range(1, hold_days + 1):
        idx = entry_idx + offset
        if idx >= len(df):
            break
        op, close = float(df["open"].iloc[idx]), float(df["close"].iloc[idx])
        open_ratio = (op / entry - 1) * 100
        ratio = round((close / entry - 1) * 100, 2)
        daily.append((offset, ratio))

        # 开盘先相对前一交易日形成的峰值检查，避免用当天收盘信息提前成交。
        if op <= stop:
            actual_idx, actual_price, reason = idx, op, "开盘止损"
            break
        if op >= target:
            actual_idx, actual_price, reason = idx, op, "开盘止盈"
            break
        if peak_return > 0 and op <= peak_price * (1 + STOP_LOSS_RATE):
            actual_idx, actual_price, reason = idx, op, "开盘回撤止损"
            break
        if op > peak_price:
            peak_price = op
            peak_return = (peak_price / entry - 1) * 100

        close_ratio = (close / entry - 1) * 100
        if close <= stop:
            actual_idx, actual_price, reason = idx, close, "收盘止损"
            break
        if close >= target:
            actual_idx, actual_price, reason = idx, close, "收盘止盈"
            break
        if peak_return > 0 and close <= peak_price * (1 + STOP_LOSS_RATE):
            actual_idx, actual_price, reason = idx, close, "收盘回撤止损"
            break
        if close > peak_price:
            peak_price = close
            peak_return = (peak_price / entry - 1) * 100
    if actual_idx is None:
        if exit_idx >= len(df) and SKIP_INCOMPLETE_TRADES:
            return None
        actual_idx = min(exit_idx, len(df) - 1)
        actual_price, reason = float(df["open"].iloc[actual_idx]), "到期开盘"
    for item in stats:
        for offset, ratio in daily:
            item["ratio_map"][offset].append(ratio)
    ret = (actual_price / entry - 1) * 100
    max_ret = round(max([ret, peak_return] + [ratio for _, ratio in daily]), 2)
    for item in stats:
        item["plus" if ret > 0 else "minus"].append(ret)
        item["count"] += 1
        item["symbols"].append(symbol)
        item["hold_days_list"].append(actual_idx - entry_idx)
        item["exit_reasons"][reason] = item["exit_reasons"].get(reason, 0) + 1
        item["positive_horizon"].append(max_ret > 0)
    trade_records.append({
        "symbol": symbol, "signal_type": label,
        "signal_date": df["date"].iloc[entry_idx - 1],
        "entry_date": df["date"].iloc[entry_idx],
        "exit_date": df["date"].iloc[actual_idx], "entry_price": entry,
        "exit_price": float(actual_price), "ret": ret, "kind": reason,
        "max_return": max_ret,
        "marks": {df["date"].iloc[i]: float(df["close"].iloc[i])
                  for i in range(entry_idx, actual_idx + 1)},
    })
    return entry, float(actual_price), ret, max_ret, reason, actual_idx


def get_buy_point(symbol, df):
    if df is None or is_excluded_symbol(symbol):
        return
    ndf = calculate_indicators(df)
    if ndf is None:
        return
    trading_calendar.update(ndf["date"].tolist())
    last_signal = -10**9
    dates = ndf["date"].to_numpy()
    for idx in np.flatnonzero(ndf["控盘+抄底"].fillna(False).to_numpy(dtype=bool)):
        if idx + 1 >= len(ndf) or (not ALLOW_OVERLAPPING_TRADES and idx - last_signal <= hold_days):
            continue
        label = "控盘+抄底"
        result = _record_trade(symbol, idx + 1, idx + 1 + hold_days, ndf, label)
        if result is None:
            continue
        last_signal = idx
        entry, price, ret, maximum, reason, exit_idx = result
        if VERBOSE_TRADES:
            fmt = lambda value: pd.Timestamp(value).strftime("%Y-%m-%d")
            print(f"{symbol} [{label}] 信号日:{fmt(dates[idx])} 买入:{fmt(dates[idx + 1])} "
                  f"价:{entry:.2f} {reason} 卖出:{fmt(dates[exit_idx])} "
                  f"价:{price:.2f} 收益:{ret:.2f}%")


def _print_one(label, stats):
    plus, minus = stats["plus"], stats["minus"]
    total = len(plus) + len(minus)
    print(f"\n【{label}】")
    if not total:
        print("无交易信号")
        return
    horizon = stats["positive_horizon"]
    values = np.asarray(plus + minus, dtype=float)
    print(f"交易次数：{total}")
    print(f"最终正收益次数：{len(plus)} 负收益次数：{len(minus)}")
    print(f"5日内曾正收益次数：{sum(horizon)}")
    print(f"正收益占比：{100 * sum(horizon) / total:.2f}%")
    print(f"平均收益：{np.mean(values):.2f}% 最大：{np.max(values):.2f}% 最小：{np.min(values):.2f}%")
    print(f"涉及股票数：{len(set(stats['symbols']))}")
    print(f"卖出原因：{stats['exit_reasons']}")
    for day in range(1, hold_days + 1):
        values = np.asarray(stats["ratio_map"][day], dtype=float)
        if len(values):
            print(f"第{day}天均值：{np.mean(values):.2f}% 胜率：{100 * np.mean(values > 0):.1f}%")


def print_statistics():
    print("=" * 70)
    print("控盘+抄底共振策略统计结果")
    print("=" * 70)
    for label in SIGNAL_KEYS:
        _print_one(label, signal_stats[label])


def simulate_portfolio(records=None, position_size=POSITION_SIZE, fee_rate=FEE_RATE,
                       init_capital=INIT_CAPITAL, save_path=None, image_path=None):
    records = trade_records if records is None else records
    if not records:
        print("没有交易记录，无法生成资金曲线")
        return None
    lo, hi = min(r["entry_date"] for r in records), max(r["exit_date"] for r in records)
    dates = set(trading_calendar) | {d for r in records for d in r["marks"]}
    days = sorted(d for d in dates if lo <= d <= hi)
    by_entry = {}
    for rec in records:
        by_entry.setdefault(rec["entry_date"], []).append(rec)
    cash, positions, curve, invested_sum = float(init_capital), [], [], 0.0
    reduced = skipped = 0
    for day in days:
        remaining = []
        for pos in positions:
            if pos["rec"]["exit_date"] == day and "开盘" in pos["rec"]["kind"]:
                cash += pos["shares"] * pos["rec"]["exit_price"] * (1 - fee_rate)
            else:
                remaining.append(pos)
        positions = remaining
        for rec in by_entry.get(day, []):
            equity = cash + sum(p["shares"] * p["last_close"] for p in positions)
            allocation = equity * position_size
            if allocation <= 0 or cash <= 1e-9:
                skipped += 1
                continue
            if cash < allocation:
                allocation, reduced = cash, reduced + 1
            shares = allocation / rec["entry_price"] / (1 + fee_rate)
            cash -= shares * rec["entry_price"] * (1 + fee_rate)
            positions.append({"rec": rec, "shares": shares, "last_close": rec["entry_price"]})
        market_value = 0.0
        for pos in positions:
            close = pos["rec"]["marks"].get(day)
            if close is not None:
                pos["last_close"] = close
            market_value += pos["shares"] * pos["last_close"]
        equity = cash + market_value
        curve.append({"date": day, "equity": equity, "cash": cash,
                      "market_value": market_value, "positions": len(positions)})
        invested_sum += market_value / equity if equity > 0 else 0
        remaining = []
        for pos in positions:
            if pos["rec"]["exit_date"] == day and "收盘" in pos["rec"]["kind"]:
                cash += pos["shares"] * pos["rec"]["exit_price"] * (1 - fee_rate)
            else:
                remaining.append(pos)
        positions = remaining
    if not curve:
        return None
    values = np.asarray([r["equity"] for r in curve], dtype=float)
    daily = np.diff(np.r_[init_capital, values]) / np.r_[init_capital, values[:-1]]
    daily = daily[np.isfinite(daily)]
    years = len(values) / 252
    annual = (values[-1] / init_capital) ** (1 / years) - 1 if years and values[-1] > 0 else np.nan
    max_dd = float((values / np.maximum.accumulate(np.r_[init_capital, values])[1:] - 1).min())
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) and daily.std() > 0 else np.nan
    total_return = values[-1] / init_capital - 1
    wins = [float(r["ret"]) for r in records if float(r.get("ret", 0)) > 0]
    losses = [float(r["ret"]) for r in records if float(r.get("ret", 0)) < 0]
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (np.inf if wins else np.nan)
    metrics = {
        "total_return": total_return, "annual_return": annual,
        # 未提供基准指数时，Alpha 按无风险收益率 0% 计算，等于策略年化超额收益。
        "alpha": annual, "sharpe": sharpe, "max_drawdown": max_dd,
        "profit_loss_ratio": (np.mean(wins) / abs(np.mean(losses))) if losses and wins else np.nan,
        "profit_factor": profit_factor,
        "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else np.nan,
        "trade_count": len(records),
    }
    print("\n组合资金曲线（等权、逐日结算）")
    print("初始资金：{:.0f} 单笔仓位：{:.1%} 止盈：{:.1%} 止损：{:.1%} 期末权益：{:.2f}".format(
        init_capital, position_size, TAKE_PROFIT_RATE, abs(STOP_LOSS_RATE), values[-1]))
    print("组合总收益：{:.2f}% 年化收益：{:.2f}% 最大回撤：{:.2f}% 日收益夏普：{:.2f}".format(
        (values[-1] / init_capital - 1) * 100, annual * 100, max_dd * 100, sharpe))
    print("Alpha(无风险0%)：{:.2f}% 盈亏比：{} 盈利因子：{} 胜率：{:.2f}%".format(
        annual * 100,
        "--" if not np.isfinite(metrics["profit_loss_ratio"]) else f"{metrics['profit_loss_ratio']:.2f}",
        "--" if not np.isfinite(metrics["profit_factor"]) else f"{metrics['profit_factor']:.2f}",
        metrics["win_rate"] * 100 if np.isfinite(metrics["win_rate"]) else 0.0))
    print("最大同时持仓：{} 笔 平均资金占用：{:.1f}%".format(
        max(r["positions"] for r in curve), invested_sum / len(curve) * 100))
    print("实际入场交易：{} 笔；因现金不足被缩减：{} 笔，被跳过：{} 笔".format(
        len(records) - skipped, reduced, skipped))
    if save_path:
        pd.DataFrame(curve).to_csv(save_path, index=False, encoding="utf-8-sig")
        print("资金曲线已保存到 {}".format(save_path))
    if image_path:
        plot_equity_curve(curve, image_path, init_capital=init_capital, metrics=metrics)
    return curve


def plot_equity_curve(curve, image_path, init_capital=INIT_CAPITAL, metrics=None):
    """保存组合权益和回撤图，使用 Agg 后端，适合无桌面环境批量回测。"""
    if not curve:
        return None
    frame = pd.DataFrame(curve)
    frame["date"] = pd.to_datetime(frame["date"])
    equity = frame["equity"].astype(float)
    peak = equity.cummax().clip(lower=float(init_capital))
    drawdown = equity / peak - 1.0
    os.makedirs(os.path.dirname(os.path.abspath(image_path)), exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]}, constrained_layout=True,
    )
    ax1.plot(frame["date"], equity, color="#1565c0", linewidth=1.6, label="Equity")
    ax1.axhline(init_capital, color="#888888", linestyle="--", linewidth=0.8)
    ax1.set_ylabel("权益")
    ax1.set_title("控盘+抄底共振策略资金曲线")
    if metrics:
        def pct(v):
            return "--" if not np.isfinite(v) else f"{v * 100:.2f}%"
        def num(v):
            return "--" if not np.isfinite(v) else f"{v:.2f}"
        info = (
            f"总收益率: {pct(metrics['total_return'])}    年化收益率: {pct(metrics['annual_return'])}\n"
            f"Alpha(无风险0%): {pct(metrics['alpha'])}    夏普比率: {num(metrics['sharpe'])}    "
            f"盈亏比: {num(metrics['profit_loss_ratio'])}    盈利因子: {num(metrics['profit_factor'])}\n"
            f"胜率: {pct(metrics['win_rate'])}    最大回撤: {pct(metrics['max_drawdown'])}    "
            f"交易次数: {metrics['trade_count']}"
        )
        ax1.text(0.01, 0.97, info, transform=ax1.transAxes, va="top", ha="left",
                 fontsize=10, bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.85))
    ax1.grid(True, alpha=0.25)
    ax1.legend(loc="upper left")
    ax2.fill_between(frame["date"], drawdown * 100, 0, color="#d32f2f", alpha=0.35)
    ax2.plot(frame["date"], drawdown * 100, color="#b71c1c", linewidth=0.9)
    ax2.set_ylabel("回撤 (%)")
    ax2.set_xlabel("日期")
    ax2.grid(True, alpha=0.25)
    fig.savefig(image_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print("资金曲线图片已保存到 {}".format(image_path))
    return image_path


def main():
    symbols = get_daily_symbols()
    if DATA_SOURCE == "watchlist":
        symbols = read_json(WATCHLIST_FILE)
    start_date = SQLITE_START_DATE if DATA_SOURCE == "sqlite" else FULL_START_DATE
    logged_in = False
    try:
        login_result = bs.login()
        logged_in = getattr(login_result, "error_code", "1") == "0"
    except Exception:
        pass
    # 使用工具函数获取实际最后交易日；失败时仍允许使用配置的结束日期。
    try:
        end_date = get_latest_trade_date()
    except Exception:
        end_date = FULL_END_DATE
    try:
        if RUN_LAST_DAY_SCAN:
            global last_day_signals
            last_day_signals = scan_last_day_signals(symbols, start_date, end_date)
            print_last_day_signals(last_day_signals)
            if last_day_signals:
                output_path = os.path.join(get_data_dir(), LAST_DAY_OUTPUT)
                write_json(last_day_signals, output_path)
                print("最后一天信号数据已保存到 {}".format(output_path))

        if RUN_BACKTEST:
            reset_stats()
            for i, symbol in enumerate(symbols, 1):
                print("进度：{} / {}".format(i, len(symbols)))
                try:
                    df = (get_local_stock_data(symbol, start_date)
                          if DATA_SOURCE == "sqlite"
                          else get_stock_pd(symbol, start_date, end_date, "d"))
                    get_buy_point(symbol, df)
                except Exception as exc:
                    print("处理 {} 失败：{}".format(symbol, exc))
                if i % 100 == 0:
                    print_statistics()
            print_statistics()
            simulate_portfolio(
                save_path=os.path.join(get_data_dir(), "control_bottom_equity.csv"),
                image_path=os.path.join(get_data_dir(), "control_bottom_equity.png"),
            )
    finally:
        if logged_in:
            bs.logout()


if __name__ == "__main__":
    main()
