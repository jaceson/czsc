# coding: utf-8
"""控盘+抄底共振策略的 CATS 日线实现。

公式信号和原控盘+抄底回测保持一致：
只有同一天同时出现「控盘」与「抄底」才允许买入，信号在下一交易日开盘执行。
卖出规则同样保持一致：从买入后的第一个交易日起，按开盘/收盘检查 20% 止盈、
3% 固定止损；产生正收益后按持仓最高价回撤 3% 移动止损；未触发时第 5 个交易日开盘退出。

本文件供 CATS 策略运行环境加载，``initialize`` 和 ``handle_data`` 为入口。
"""

import json
import math
import os

import numpy as np

import pandas as pd
from lib.MyTT import REF, SMA, MA, HHV, LLV, BARSLAST, BARSLASTCOUNT, BETWEEN


universe = ["600030.SH"]
benchmark = "000300.SH"
start = "2026-01-01"
end = "2026-09-11"
frequency = "daily"

every_trade_cash = 40000
MAX_HOLD_DAYS = 5
TAKE_PROFIT_RATE = 0.20
STOP_LOSS_RATE = -0.03
PEAK_PROFIT_THRESHOLD = 0.0


# 与 LifeLine_talib_daily.py 相同，从 CATS 的 sample 股票列表构造代码。
cur_dir = os.getcwd()
symbol_file = os.path.join(cur_dir, "sample/sh_sz_stock.json")
try:
    with open(symbol_file, "r", encoding="utf-8") as file:
        stock_items = json.load(file)
    universe = []
    for item in stock_items:
        stock_code = next(iter(item))
        code, exchange = stock_code.split(".")
        universe.append(code + "." + exchange.upper())
    universe = universe[:1000]
except (OSError, ValueError, TypeError, StopIteration):
    # CATS 环境没有 sample 文件时保留上面的示例标的，方便单标的运行。
    pass

try:
    add_trade_account(CatsTradeAccount("CATS668", "S0", sim_capital_base=1000000.0))
    set_commission_equity(AShareCommission(
        open_commission=0.0003, sell_commission=0.0003,
        open_tax=0.0, sell_tax=0.001, min_commission=5.0,
    ))
except NameError:
    # 允许在本地仅导入/测试信号计算；CATS 运行环境会提供这些 API。
    pass


def _dynamic_count(condition, periods):
    """通达信 COUNT(condition, N) 的动态周期实现。"""
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
    """按每根 K 线的动态周期计算 HHV/LLV。"""
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
    """直接计算控盘、抄底及唯一交易信号，不依赖其它策略文件。"""
    required = {"date", "open", "high", "low", "close", "volume"}
    if df is None or len(df) < 60 or not required.issubset(df.columns):
        return None
    ndf = df.copy()
    ndf["date"] = pd.to_datetime(ndf["date"], errors="raise").dt.normalize()
    ndf = ndf.sort_values("date").reset_index(drop=True)
    if ndf["date"].duplicated().any():
        raise ValueError("行情日期存在重复值")
    O = ndf["open"].values.astype(float)
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)
    V = ndf["volume"].values.astype(float)
    if not all(np.isfinite(x).all() for x in (O, H, L, C, V)) or (C <= 0).any():
        raise ValueError("行情数据必须是有限数值，收盘价必须为正")

    X_2B = C < O
    X_0N = X_2B & (np.cumsum(X_2B) == 4)
    X_D2 = BARSLAST(X_0N)
    X_VM = np.floor(X_D2 / 6)
    X_K2 = BARSLASTCOUNT(X_VM == REF(X_VM, 1)) == 5
    X_NM = np.isclose(C, LLV(C, 60), equal_nan=False)
    X_BA = BARSLAST(X_NM)
    X_RQ = BETWEEN(X_BA, 1, 60) & (_safe_ratio(C, REF(C, 1)) > 1.043)
    X_UY = X_RQ & (_dynamic_count(X_RQ, X_BA) == 1)
    X_Z8 = BARSLAST(X_UY)
    X_ZO = np.isclose(C, _dynamic_extreme(C, X_Z8, "min"), equal_nan=False)
    X_Z6 = BARSLAST(X_ZO)
    X_MD = (X_Z6 == 1) & (C > _dynamic_ref(C, X_Z6)) & (H > L)
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
    X_S3 = np.where(X_LT, X_TX, 0) + np.where(X_7O, X_3Z, 0) + np.where(X_2Q, X_0L, 0)
    X_5G = (C >= X_S3) & (_safe_ratio(C, REF(C, 1)) > 1.043)
    X_QQ = (_dynamic_count(X_5G, X_Z8) == 1) & X_5G
    bottom_signal = BARSLASTCOUNT(X_CQ) == 1
    ndf["控盘"] = X_QQ
    ndf["抄底"] = bottom_signal
    ndf["控盘+抄底"] = X_QQ & bottom_signal
    ndf["总信号"] = ndf["控盘+抄底"]
    return ndf


def calc_signal(df):
    """返回与行情等长的控盘+抄底共振信号序列。"""
    if df is None or len(df) < 60:
        return None
    # CATS history 通常使用 DatetimeIndex，而公式回测器要求 date 列。
    if "date" not in df.columns:
        prepared = df.copy()
        index = getattr(prepared, "index", None)
        if index is None:
            return None
        prepared["date"] = index
    else:
        prepared = df
    try:
        ndf = calculate_indicators(prepared)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):
        return None
    if ndf is None:
        return None
    return ndf["控盘+抄底"].fillna(False).values.astype(bool)


def initialize(context):
    context.buy_price = {}
    context.buy_date = {}
    context.hold_days = {}
    context.peak_price = {}
    context.peak_return = {}


def _clear_position_state(context, stkcode):
    for name in ("buy_price", "buy_date", "hold_days", "peak_price", "peak_return"):
        getattr(context, name, {}).pop(stkcode, None)


def _current_open(stkcode):
    current = get_current_data(stkcode)
    value = getattr(current, "day_open_price", None)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) and value > 0 else None


def _sell(context, stkcode, price, reason, current_dt):
    buy_price = context.buy_price.get(stkcode, 0.0)
    ret_pct = (price / buy_price - 1) * 100 if buy_price > 0 else 0.0
    log.info("控盘+抄底卖出：{},{},原因:{},持仓天数:{},收益率:{:+.2f}%".format(
        stkcode, current_dt, reason, context.hold_days.get(stkcode, 0), ret_pct))
    order_target(stkcode, 0)
    _clear_position_state(context, stkcode)


def handle_data(context, data):
    for stkcode in context.universe:
        df = data.history(stkcode, ["open", "close", "high", "low", "volume"], 100, "1d")
        if df is None or len(df) < 60:
            continue

        signal = calc_signal(df)
        if signal is None:
            continue
        buy_signal = bool(signal[-1])
        position = context.portfolio[0].positions[stkcode].amount

        if position > 0:
            context.hold_days[stkcode] = context.hold_days.get(stkcode, 0) + 1
            buy_price = float(context.buy_price.get(stkcode, 0.0))
            if buy_price <= 0:
                continue

            target = buy_price * (1 + TAKE_PROFIT_RATE)
            stop = buy_price * (1 + STOP_LOSS_RATE)
            peak_price = float(context.peak_price.get(stkcode, buy_price))
            peak_return = float(context.peak_return.get(stkcode, 0.0))
            cur_open = _current_open(stkcode)
            if cur_open is None:
                cur_open = float(df["close"].iloc[-1])

            # 开盘检查顺序与独立回测一致：固定止损、固定止盈、峰值回撤止损。
            if cur_open <= stop:
                _sell(context, stkcode, cur_open, "开盘止损", data.current_dt)
                continue
            if cur_open >= target:
                _sell(context, stkcode, cur_open, "开盘止盈", data.current_dt)
                continue
            if peak_return > PEAK_PROFIT_THRESHOLD and cur_open <= peak_price * (1 + STOP_LOSS_RATE):
                _sell(context, stkcode, cur_open, "开盘回撤止损", data.current_dt)
                continue
            if cur_open > peak_price:
                peak_price = cur_open
                peak_return = (peak_price / buy_price - 1) * 100

            # history 的最后一根是最新已完成日线，作为收盘事件检查。
            cur_close = float(df["close"].iloc[-1])
            if cur_close <= stop:
                _sell(context, stkcode, cur_close, "收盘止损", data.current_dt)
                continue
            if cur_close >= target:
                _sell(context, stkcode, cur_close, "收盘止盈", data.current_dt)
                continue
            if peak_return > PEAK_PROFIT_THRESHOLD and cur_close <= peak_price * (1 + STOP_LOSS_RATE):
                _sell(context, stkcode, cur_close, "收盘回撤止损", data.current_dt)
                continue
            if cur_close > peak_price:
                peak_price = cur_close
                peak_return = (peak_price / buy_price - 1) * 100

            context.peak_price[stkcode] = peak_price
            context.peak_return[stkcode] = peak_return

            if context.hold_days.get(stkcode, 0) >= MAX_HOLD_DAYS:
                _sell(context, stkcode, cur_open, "到期开盘", data.current_dt)
                continue

        elif buy_signal:
            open_price = _current_open(stkcode)
            if open_price is None:
                continue
            cash = context.portfolio[0].cash
            if cash < every_trade_cash:
                continue
            order_amount = math.floor(every_trade_cash / open_price / 100) * 100
            if order_amount <= 0:
                continue
            log.info("控盘+抄底买入：{},{},价:{:.2f},现金:{:.2f},数量:{}".format(
                stkcode, data.current_dt, open_price, cash, order_amount))
            order(stkcode, order_amount)
            context.buy_price[stkcode] = open_price
            context.buy_date[stkcode] = data.current_dt.strftime("%Y-%m-%d")
            context.hold_days[stkcode] = 0
            context.peak_price[stkcode] = open_price
            context.peak_return[stkcode] = 0.0
