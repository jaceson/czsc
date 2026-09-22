# coding: utf-8
"""基于 ``czsc_daily_util.is_golden_point`` 的日线策略回测。

信号按每个交易日的历史截面重新计算，只使用当日及之前的数据。
买入、卖出、统计和资金曲线口径与 ``CZSCStragegy_FormulaSignal_ControlBottom`` 一致：
信号次日开盘买入，10% 止盈、3% 止损；持仓产生正收益后按峰值价格回撤 3% 止损，
未触发时第 5 个交易日开盘退出。
"""
import os
import contextlib
import io

import baostock as bs
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import czsc_daily_util as daily_util
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data


hold_days = 10
TAKE_PROFIT_RATE = 0.10
STOP_LOSS_RATE = -0.03
INIT_CAPITAL = 1000000.0
POSITION_SIZE = 0.05
FEE_RATE = 0.0
DATA_SOURCE = "sqlite"  # sqlite / cache
FULL_START_DATE = "2020-01-01"
FULL_END_DATE = "2026-01-01"
SQLITE_START_DATE = "2020-01-01"
WATCHLIST_FILE = "./data/超跌反弹.json"
VERBOSE_TRADES = True
SKIP_INCOMPLETE_TRADES = True
ALLOW_OVERLAPPING_TRADES = False
EXCLUDE_ST_688 = True

GOLDEN_THRESHOLD = 1.7
GOLDEN_KLINES = 10
GOLDEN_MAX_RATIO = 1.1
GOLDEN_MIN_ANGLE = 20
GOLDEN_CLOSE_RATIO = 1.1

SIGNAL_KEYS = ["黄金分割点"]
signal_stats = {}
trade_records = []
trading_calendar = set()


def _new_stats():
    return {
        "plus": [], "minus": [],
        "ratio_map": {d: [] for d in range(1, hold_days + 1)},
        "count": 0, "symbols": [], "hold_days_list": [],
        "exit_reasons": {}, "positive_horizon": [],
    }


def reset_stats():
    global signal_stats, trade_records, trading_calendar
    signal_stats = {key: _new_stats() for key in SIGNAL_KEYS}
    trade_records = []
    trading_calendar = set()


reset_stats()


_name_map = None


def get_symbol_name(symbol):
    global _name_map
    if _name_map is None:
        _name_map = {}
        try:
            for item in read_json(os.path.join(get_data_dir(), "sh_sz_stock.json")):
                _name_map.update(item)
        except Exception:
            pass
    return _name_map.get(symbol, "UNKNOWN")


def is_excluded_symbol(symbol):
    code = str(symbol).split(".")[-1]
    return EXCLUDE_ST_688 and (code.startswith("688") or "ST" in get_symbol_name(symbol).upper())


def _normalized_df(df):
    if df is None or len(df) < 60:
        return None
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return None
    ndf = df.copy()
    ndf["date"] = pd.to_datetime(ndf["date"], errors="raise").dt.normalize()
    ndf = ndf.sort_values("date").reset_index(drop=True)
    if ndf["date"].duplicated().any():
        raise ValueError("行情日期存在重复值")
    for col in ("open", "high", "low", "close", "volume"):
        ndf[col] = pd.to_numeric(ndf[col], errors="raise")
    if not np.isfinite(ndf[["open", "high", "low", "close", "volume"]].to_numpy()).all():
        raise ValueError("行情数据必须是有限数值")
    if (ndf["close"] <= 0).any():
        raise ValueError("收盘价必须为正")
    # is_golden_point -> days_trade_delta 使用 YYYY-MM-DD 字符串匹配拐点日期。
    ndf["date"] = ndf["date"].dt.strftime("%Y-%m-%d")
    return ndf


def calculate_signals(symbol, df):
    """逐日调用 is_golden_point，返回不含未来数据的黄金点信号列。"""
    ndf = _normalized_df(df)
    if ndf is None or is_excluded_symbol(symbol):
        return None
    signals = np.zeros(len(ndf), dtype=bool)
    # is_golden_point 内部会记录诊断日志；回测只保留信号结果，避免批量运行刷屏。
    old_disabled = getattr(logger, "disabled", False)
    old_write_json = daily_util.write_json
    logger.disabled = True
    # 选股函数会把最近黄金点写入 golden_log.json；回测不应改写共享诊断文件。
    daily_util.write_json = lambda *args, **kwargs: None
    try:
        for idx in range(len(ndf)):
            if idx < 59:
                continue
            history = ndf.iloc[:idx + 1].copy()
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    signals[idx] = bool(is_golden_point(
                        symbol, history,
                        threshold=GOLDEN_THRESHOLD,
                        klines=GOLDEN_KLINES,
                        max_ratio=GOLDEN_MAX_RATIO,
                        min_angle=GOLDEN_MIN_ANGLE,
                        close_ratio=GOLDEN_CLOSE_RATIO,
                    ))
            except (AttributeError, IndexError, KeyError, ValueError, AssertionError,
                    TypeError, ZeroDivisionError):
                signals[idx] = False
    finally:
        logger.disabled = old_disabled
        daily_util.write_json = old_write_json
        # 每个历史截面都是一次性计算，保留缓存只会增加内存占用。
        if "stock_czsc_cache" in globals():
            stock_czsc_cache.clear()
        if "stock_bars_cache" in globals():
            stock_bars_cache.clear()
    ndf["黄金分割点"] = signals
    return ndf


def _record_trade(symbol, entry_idx, exit_idx, df):
    entry = float(df["open"].iloc[entry_idx])
    if not np.isfinite(entry) or entry <= 0:
        return None
    target = entry * (1 + TAKE_PROFIT_RATE)
    stop = entry * (1 + STOP_LOSS_RATE)
    actual_idx = actual_price = None
    reason = None
    daily = []
    # 持仓产生正收益后，按期间最高开盘/收盘价计算回撤止损；
    # 尚未盈利时仍只执行相对入场价的固定止损。
    peak_price = entry
    peak_return = 0.0
    for offset in range(1, hold_days + 1):
        idx = entry_idx + offset
        if idx >= len(df):
            break
        op = float(df["open"].iloc[idx])
        close = float(df["close"].iloc[idx])
        ratio = round((close / entry - 1) * 100, 2)
        daily.append((offset, ratio))

        # 开盘优先检查止损/止盈，再检查相对前一日已确认峰值的回撤。
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

        # 收盘检查固定止损/止盈及当日回撤，收盘创新高则更新峰值供后续交易日使用。
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

    stats = signal_stats["黄金分割点"]
    for offset, ratio in daily:
        stats["ratio_map"][offset].append(ratio)
    ret = (actual_price / entry - 1) * 100
    max_ret = round(max([ret, peak_return] + [ratio for _, ratio in daily]), 2)
    stats["plus" if ret > 0 else "minus"].append(ret)
    stats["count"] += 1
    stats["symbols"].append(symbol)
    stats["hold_days_list"].append(actual_idx - entry_idx)
    stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
    stats["positive_horizon"].append(max_ret > 0)

    trade_records.append({
        "symbol": symbol,
        "signal_type": "黄金分割点",
        "signal_date": df["date"].iloc[entry_idx - 1],
        "entry_date": df["date"].iloc[entry_idx],
        "exit_date": df["date"].iloc[actual_idx],
        "entry_price": entry,
        "exit_price": float(actual_price),
        "ret": ret,
        "kind": reason,
        "max_return": max_ret,
        "marks": {df["date"].iloc[i]: float(df["close"].iloc[i])
                  for i in range(entry_idx, actual_idx + 1)},
    })
    return entry, float(actual_price), ret, reason, actual_idx


def get_buy_point(symbol, df):
    if df is None or is_excluded_symbol(symbol):
        return
    ndf = calculate_signals(symbol, df)
    if ndf is None:
        return
    trading_calendar.update(ndf["date"].tolist())
    last_signal = -10**9
    dates = ndf["date"].to_numpy()
    for idx in np.flatnonzero(ndf["黄金分割点"].to_numpy(dtype=bool)):
        if idx + 1 >= len(ndf):
            continue
        if not ALLOW_OVERLAPPING_TRADES and idx - last_signal <= hold_days:
            continue
        result = _record_trade(symbol, idx + 1, idx + 1 + hold_days, ndf)
        if result is None:
            continue
        last_signal = idx
        entry, price, ret, reason, exit_idx = result
        if VERBOSE_TRADES:
            fmt = lambda value: pd.Timestamp(value).strftime("%Y-%m-%d")
            print(f"{symbol} [黄金分割点] 信号日:{fmt(dates[idx])} 买入:{fmt(dates[idx + 1])} "
                  f"价:{entry:.2f} {reason} 卖出:{fmt(dates[exit_idx])} "
                  f"价:{price:.2f} 收益:{ret:.2f}%")


def print_statistics():
    stats = signal_stats["黄金分割点"]
    plus, minus = stats["plus"], stats["minus"]
    total = len(plus) + len(minus)
    print("=" * 70)
    print("黄金分割点策略统计结果")
    print("=" * 70)
    if not total:
        print("无交易信号")
        return
    values = np.asarray(plus + minus, dtype=float)
    print(f"交易次数：{total}")
    print(f"最终正收益次数：{len(plus)} 负收益次数：{len(minus)}")
    print(f"5日内曾正收益次数：{sum(stats['positive_horizon'])}")
    print(f"正收益占比：{100 * sum(stats['positive_horizon']) / total:.2f}%")
    print(f"平均收益：{np.mean(values):.2f}% 最大：{np.max(values):.2f}% 最小：{np.min(values):.2f}%")
    print(f"涉及股票数：{len(set(stats['symbols']))}")
    print(f"卖出原因：{stats['exit_reasons']}")
    for day in range(1, hold_days + 1):
        day_values = np.asarray(stats["ratio_map"][day], dtype=float)
        if len(day_values):
            print(f"第{day}天均值：{np.mean(day_values):.2f}% 胜率：{100 * np.mean(day_values > 0):.1f}%")


def _metrics(curve, records, init_capital):
    values = np.asarray([x["equity"] for x in curve], dtype=float)
    daily = np.diff(np.r_[init_capital, values]) / np.r_[init_capital, values[:-1]]
    daily = daily[np.isfinite(daily)]
    years = len(values) / 252
    annual = (values[-1] / init_capital) ** (1 / years) - 1 if years and values[-1] > 0 else np.nan
    max_dd = float((values / np.maximum.accumulate(np.r_[init_capital, values])[1:] - 1).min())
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) and daily.std() > 0 else np.nan
    wins = [float(r["ret"]) for r in records if float(r["ret"]) > 0]
    losses = [float(r["ret"]) for r in records if float(r["ret"]) < 0]
    return {
        "total_return": values[-1] / init_capital - 1,
        "annual_return": annual, "alpha": annual, "sharpe": sharpe,
        "max_drawdown": max_dd,
        "profit_loss_ratio": np.mean(wins) / abs(np.mean(losses)) if wins and losses else np.nan,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (np.inf if wins else np.nan),
        "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else np.nan,
        "trade_count": len(records),
    }


def plot_equity_curve(curve, image_path, init_capital=INIT_CAPITAL, metrics=None):
    if not curve:
        return None
    frame = pd.DataFrame(curve)
    frame["date"] = pd.to_datetime(frame["date"])
    equity = frame["equity"].astype(float)
    peak = equity.cummax().clip(lower=float(init_capital))
    drawdown = equity / peak - 1
    os.makedirs(os.path.dirname(os.path.abspath(image_path)), exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]}, constrained_layout=True)
    ax1.plot(frame["date"], equity, color="#1565c0", linewidth=1.6, label="Equity")
    ax1.axhline(init_capital, color="#888", linestyle="--", linewidth=0.8)
    ax1.set_title("黄金分割点策略资金曲线")
    ax1.set_ylabel("权益")
    if metrics:
        pct = lambda x: "--" if not np.isfinite(x) else f"{x * 100:.2f}%"
        num = lambda x: "--" if not np.isfinite(x) else f"{x:.2f}"
        info = (f"总收益率: {pct(metrics['total_return'])}    年化收益率: {pct(metrics['annual_return'])}\n"
                f"Alpha(无风险0%): {pct(metrics['alpha'])}    夏普比率: {num(metrics['sharpe'])}    "
                f"盈亏比: {num(metrics['profit_loss_ratio'])}    盈利因子: {num(metrics['profit_factor'])}\n"
                f"胜率: {pct(metrics['win_rate'])}    最大回撤: {pct(metrics['max_drawdown'])}    "
                f"交易次数: {metrics['trade_count']}")
        ax1.text(0.01, 0.97, info, transform=ax1.transAxes, va="top", fontsize=10,
                 bbox=dict(boxstyle="round,pad=0.45", facecolor="white", alpha=0.85))
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


def simulate_portfolio(records=None, position_size=POSITION_SIZE, fee_rate=FEE_RATE,
                       init_capital=INIT_CAPITAL, save_path=None, image_path=None):
    records = trade_records if records is None else records
    if not records:
        print("没有交易记录，无法生成资金曲线")
        return None
    lo, hi = min(r["entry_date"] for r in records), max(r["exit_date"] for r in records)
    days = sorted(d for d in set(trading_calendar) | {d for r in records for d in r["marks"]}
                  if lo <= d <= hi)
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
    metrics = _metrics(curve, records, init_capital)
    values = np.asarray([x["equity"] for x in curve], dtype=float)
    print("\n组合资金曲线（等权、逐日结算）")
    print("初始资金：{:.0f} 单笔仓位：{:.1%} 止盈：{:.1%} 止损：{:.1%} 期末权益：{:.2f}".format(
        init_capital, position_size, TAKE_PROFIT_RATE, abs(STOP_LOSS_RATE), values[-1]))
    print("组合总收益：{:.2f}% 年化收益：{:.2f}% 最大回撤：{:.2f}% 日收益夏普：{:.2f}".format(
        metrics["total_return"] * 100, metrics["annual_return"] * 100,
        metrics["max_drawdown"] * 100, metrics["sharpe"]))
    print("Alpha(无风险0%)：{:.2f}% 盈亏比：{} 盈利因子：{} 胜率：{:.2f}%".format(
        metrics["alpha"] * 100,
        "--" if not np.isfinite(metrics["profit_loss_ratio"]) else f"{metrics['profit_loss_ratio']:.2f}",
        "--" if not np.isfinite(metrics["profit_factor"]) else f"{metrics['profit_factor']:.2f}",
        metrics["win_rate"] * 100 if np.isfinite(metrics["win_rate"]) else 0.0))
    print("最大同时持仓：{} 笔 平均资金占用：{:.1f}%".format(
        max(x["positions"] for x in curve), invested_sum / len(curve) * 100))
    print("实际入场交易：{} 笔；因现金不足被缩减：{} 笔，被跳过：{} 笔".format(
        len(records) - skipped, reduced, skipped))
    if save_path:
        pd.DataFrame(curve).to_csv(save_path, index=False, encoding="utf-8-sig")
        print("资金曲线已保存到 {}".format(save_path))
    if image_path:
        plot_equity_curve(curve, image_path, init_capital, metrics)
    return curve


def main():
    reset_stats()
    symbols = read_json(WATCHLIST_FILE) if DATA_SOURCE == "watchlist" else get_daily_symbols()
    start_date = SQLITE_START_DATE if DATA_SOURCE == "sqlite" else FULL_START_DATE
    logged_in = False
    if DATA_SOURCE == "watchlist":
        bs.login()
        logged_in = True
    try:
        for i, symbol in enumerate(symbols, 1):
            print("进度：{} / {}，交易数：{}".format(i, len(symbols), len(trade_records)))
            try:
                df = (get_local_stock_data(symbol, start_date) if DATA_SOURCE == "sqlite"
                      else get_stock_pd(symbol, start_date, FULL_END_DATE, "d"))
                get_buy_point(symbol, df)
            except Exception as exc:
                print("处理 {} 失败：{}".format(symbol, exc))
            if i % 100 == 0:
                print_statistics()
        print_statistics()
        simulate_portfolio(
            save_path=os.path.join(get_data_dir(), "golden_point_equity.csv"),
            image_path=os.path.join(get_data_dir(), "golden_point_equity.png"),
        )
    finally:
        if logged_in:
            bs.logout()


if __name__ == "__main__":
    main()
'''
======================================================================
黄金分割点策略统计结果[2024-01-01到2026-09-14]
======================================================================
交易次数：1230
最终正收益次数：563 负收益次数：667
5日内曾正收益次数：978
正收益占比：79.51%
平均收益：2.37% 最大：35.22% 最小：-28.52%
涉及股票数：197
卖出原因：{'收盘止损': 212, '收盘回撤止损': 489, '收盘止盈': 75, '开盘回撤止损': 182, '到期开盘': 62, '开盘止损': 167, '开盘止盈': 43}
第1天均值：1.49% 胜率：59.6%
第2天均值：3.23% 胜率：72.0%
第3天均值：3.74% 胜率：75.3%
第4天均值：4.68% 胜率：76.1%
第5天均值：5.29% 胜率：84.1%
第6天均值：6.31% 胜率：88.8%
第7天均值：7.30% 胜率：89.2%
第8天均值：8.69% 胜率：88.7%
第9天均值：8.84% 胜率：96.0%
第10天均值：10.15% 胜率：94.0%

组合资金曲线（等权、逐日结算）
初始资金：1000000 单笔仓位：5.0% 止盈：20.0% 止损：3.0% 期末权益：1917016.36
组合总收益：91.70% 年化收益：31.73% 最大回撤：-13.43% 日收益夏普：1.65
Alpha(无风险0%)：31.73% 盈亏比：2.67 盈利因子：2.29 胜率：46.22%
最大同时持仓：23 笔 平均资金占用：28.3%
实际入场交易：728 笔；因现金不足被缩减：61 笔，被跳过：502 笔
'''