# coding: utf-8
"""以 czsc_daily_util.get_chan_buy_point_type 返回值为买点的日线回测。

每个候选信号日调用原函数，输入仅含截至当天的历史数据（日期字符串和连续索引）。
保留原函数六类买点、优先级、近期买点识别及历史样本 70% 正收益筛选。
信号日为函数返回非空值的当日；原函数可能返回昨日锚点，仍在信号次日开盘买入。
买入当天不卖出；T+1 起按开盘/收盘检查 +5% 止盈和 -5% 止损，
第五日开盘强制退出。跳空按实际价格结算，损失可能超过 5%。
统计与全周期共振回测相同：逐日收益为假设持有至第 1～5 日收盘的诊断收益，
与实际卖出收益分开；股票过滤、仓位、费用及重叠持仓均可配置。
逐日调用会重复构建缠论状态，全市场回测比普通向量公式慢。
"""
import os
import numpy as np
import pandas as pd

hold_days = 5
TAKE_PROFIT_RATE = 0.05
STOP_LOSS_RATE = -0.05
INIT_CAPITAL = 400000.0
POSITION_SIZE = 0.02
FEE_RATE = 0.0
DATA_SOURCE = "cache"
FULL_START_DATE = "2026-01-01"
FULL_END_DATE = "2026-09-11"
HISTORY_START_DATE = "2024-01-01"  # 函数历史样本起点；改变此值会影响内部筛选结果
WATCHLIST_FILE = "./data/超跌反弹.json"
VERBOSE_TRADES = True
SKIP_INCOMPLETE_TRADES = True
ALLOW_OVERLAPPING_TRADES = False
EXCLUDE_ST_688 = True
BUY_TYPES = ("1", "1p", "2", "2s", "3a", "3b")
SIGNAL_KEYS = [*BUY_TYPES, "总计"]
trade_records = []
trading_calendar = set()


def _new_stats():
    return {"plus": [], "minus": [], "ratio_map": {d: [] for d in range(1, hold_days + 1)},
            "count": 0, "symbols": [], "hold_days_list": [], "exit_reasons": {},
            "positive_horizon": []}


signal_stats = {k: _new_stats() for k in SIGNAL_KEYS}


def reset_stats():
    signal_stats.clear()
    signal_stats.update({k: _new_stats() for k in SIGNAL_KEYS})
    trade_records.clear()
    trading_calendar.clear()


def _record_trade(symbol, entry_idx, exit_idx, df, buy_type):
    if buy_type not in BUY_TYPES:
        raise ValueError(f"未知缠论买点：{buy_type}")
    entry = float(df["open"].iloc[entry_idx])
    if not np.isfinite(entry) or entry <= 0:
        return None
    actual_idx = None
    for idx in range(entry_idx + 1, min(exit_idx, len(df) - 1) + 1):
        op = float(df["open"].iloc[idx])
        if op <= entry * (1 + STOP_LOSS_RATE):
            actual_idx, price, reason = idx, op, "开盘止损"
            break
        if op >= entry * (1 + TAKE_PROFIT_RATE):
            actual_idx, price, reason = idx, op, "开盘止盈"
            break
        # 到期必须在开盘退出，不用当天收盘决定是否回到开盘成交。
        if idx == exit_idx:
            actual_idx, price, reason = idx, op, "到期开盘"
            break
        close = float(df["close"].iloc[idx])
        if close <= entry * (1 + STOP_LOSS_RATE):
            actual_idx, price, reason = idx, close, "收盘止损"
            break
        if close >= entry * (1 + TAKE_PROFIT_RATE):
            actual_idx, price, reason = idx, close, "收盘止盈"
            break
    if actual_idx is None:
        if SKIP_INCOMPLETE_TRADES or len(df) - 1 <= entry_idx:
            return None
        actual_idx, reason = len(df) - 1, "数据结束收盘"
        price = float(df["close"].iloc[actual_idx])
    ret = 100 * (price / entry - 1)
    stats_list = [signal_stats[buy_type], signal_stats["总计"]]
    daily_returns = []
    for offset in range(1, hold_days + 1):
        idx = entry_idx + offset
        if idx >= len(df):
            break
        ratio = 100 * (float(df["close"].iloc[idx]) / entry - 1)
        daily_returns.append(ratio)
        for stats in stats_list:
            stats["ratio_map"][offset].append(ratio)
    max_ret = max([ret] + daily_returns)
    for stats in stats_list:
        stats["plus" if ret > 0 else "minus"].append(ret)
        stats["count"] += 1
        stats["symbols"].append(symbol)
        stats["hold_days_list"].append(actual_idx - entry_idx)
        stats["positive_horizon"].append(max_ret > 0)
        stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
    trade_records.append({"symbol": symbol, "buy_type": buy_type,
                          "signal_date": df["date"].iloc[entry_idx - 1], "entry_date": df["date"].iloc[entry_idx],
                          "exit_date": df["date"].iloc[actual_idx], "entry_price": entry,
                          "exit_price": price, "ret": ret, "kind": reason,
                          "marks": {df["date"].iloc[i]: float(df["close"].iloc[i])
                                    for i in range(entry_idx, actual_idx + 1)}})
    return entry, price, ret, max_ret, reason, actual_idx


_name_map = None


def is_excluded_symbol(symbol):
    global _name_map
    if not EXCLUDE_ST_688:
        return False
    from czsc_daily_util import get_data_dir, read_json
    if _name_map is None:
        _name_map = {}
        for item in read_json(os.path.join(get_data_dir(), "sh_sz_stock.json")):
            _name_map.update(item)
    return str(symbol).split(".")[-1].startswith("688") or "ST" in _name_map.get(symbol, "").upper()


def get_chan_buy_point_type(*args, **kwargs):
    """延迟导入，以原函数的返回值作为唯一买点来源。"""
    from czsc_daily_util import get_chan_buy_point_type as detector
    return detector(*args, **kwargs)


def _prepare_data(df):
    if df is None or df.empty:
        return None
    required = {"date", "open", "high", "low", "close", "volume", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"缠论输入缺少列：{sorted(missing)}")
    ndf = df.copy()
    ndf["date"] = pd.to_datetime(ndf["date"], errors="raise").dt.normalize()
    ndf = ndf.sort_values("date").reset_index(drop=True)
    if ndf["date"].isna().any() or ndf["date"].duplicated().any():
        raise ValueError("日线日期缺失或重复")
    ndf = ndf.loc[ndf["date"].between(pd.Timestamp(HISTORY_START_DATE), pd.Timestamp(FULL_END_DATE))].reset_index(drop=True)
    for column in required - {"date"}:
        ndf[column] = pd.to_numeric(ndf[column], errors="raise")
        if not np.isfinite(ndf[column]).all():
            raise ValueError(f"{column} 存在非有限数值")
        if column in {"open", "high", "low", "close"} and (ndf[column] <= 0).any():
            raise ValueError(f"{column} 必须为正数")
    return ndf


def get_buy_point(symbol, df):
    ndf = _prepare_data(df)
    if ndf is None or len(ndf) < 2 or is_excluded_symbol(symbol):
        return
    dates = ndf["date"]
    trading_calendar.update(dates[dates >= pd.Timestamp(FULL_START_DATE)].tolist())
    # 原函数按字符串日期查找行索引，必须提供 YYYY-MM-DD 和连续 RangeIndex。
    detector_df = ndf.copy()
    detector_df["date"] = dates.dt.strftime("%Y-%m-%d")
    last_exit = -1
    for idx in range(1, len(ndf) - 1):
        if dates.iloc[idx] < pd.Timestamp(FULL_START_DATE):
            continue
        if not ALLOW_OVERLAPPING_TRADES and idx < last_exit:
            continue
        # 每日重新运行原函数，保留其历史样本、买点优先级和 70% 筛选。
        # 不传未来 K 线；不按缠论买点的历史锚点回填成交。
        prefix = detector_df.iloc[:idx + 1].copy().reset_index(drop=True)
        buy_type = get_chan_buy_point_type(
            symbol=symbol, start_date=prefix["date"].iloc[0],
            end_date=prefix["date"].iloc[-1], frequency="d", df=prefix)
        if buy_type is None:
            continue
        if buy_type not in BUY_TYPES:
            raise ValueError(f"get_chan_buy_point_type 返回未知类型：{buy_type!r}")
        entry_idx = idx + 1
        result = _record_trade(symbol, entry_idx, entry_idx + hold_days, ndf, buy_type)
        if result is None:
            continue
        entry, price, ret, maximum, reason, last_exit = result
        if VERBOSE_TRADES:
            print(f"{symbol} [缠论 {buy_type} 买] 信号日:{dates.iloc[idx]:%Y-%m-%d} "
                  f"买入:{dates.iloc[entry_idx]:%Y-%m-%d} 价:{entry:.2f} "
                  f"{reason} 卖出:{dates.iloc[last_exit]:%Y-%m-%d} 价:{price:.2f} 收益:{ret:.2f}%")


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
    print("  缠论买点策略 — 统计结果")
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
    dates = set(trading_calendar) | {d for r in records for d in r["marks"]}
    days = sorted(d for d in dates if lo <= d <= hi)
    new_trades = {}
    for record in records:
        new_trades.setdefault(record["entry_date"], []).append(record)

    cash = float(init_capital)
    open_positions = []
    curve = []
    skipped, reduced = 0, 0
    invested_sum = 0.0

    for day in days:
        # 仅开盘卖出所得可用于当天开盘买入。
        keep = []
        for pos in open_positions:
            if pos["rec"]["exit_date"] == day and "开盘" in pos["rec"]["kind"]:
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

        keep = []
        for pos in open_positions:
            if pos["rec"]["exit_date"] == day:
                cash += pos["shares"] * pos["rec"]["exit_price"] * (1 - fee_rate)
            else:
                keep.append(pos)
        open_positions = keep

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
        daily = np.diff(np.r_[init_capital, eq]) / np.r_[init_capital, eq[:-1]]
    daily = daily[np.isfinite(daily)]
    years = len(eq) / 252.0
    annual = ((eq[-1] / init_capital) ** (1 / years) - 1
              if years > 0 and eq[-1] > 0 else float("nan"))
    max_dd = float((eq / np.maximum.accumulate(np.r_[init_capital, eq])[1:] - 1).min())
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


def main():
    import baostock as bs
    from czsc_daily_util import get_daily_symbols, read_json, get_stock_pd, get_data_dir
    from czsc_sqlite import get_local_stock_data

    reset_stats()
    symbols = get_daily_symbols()
    if DATA_SOURCE == "watchlist":
        symbols = read_json(WATCHLIST_FILE)
    if DATA_SOURCE not in {"cache", "sqlite", "watchlist"}:
        raise ValueError("未知 DATA_SOURCE")
    if DATA_SOURCE == "watchlist":
        bs.login()
    print(f"缠论买点：{FULL_START_DATE} ~ {FULL_END_DATE}；历史预热自 {HISTORY_START_DATE}")
    print("原函数逐日调用（历史数据截至信号日）；+5% 止盈，-5% 止损；第五日开盘退出")
    try:
        for i, symbol in enumerate(symbols, 1):
            print(f"进度：{i} / {len(symbols)}")
            try:
                if DATA_SOURCE == "sqlite":
                    df = get_local_stock_data(symbol, HISTORY_START_DATE)
                else:
                    df = get_stock_pd(symbol, HISTORY_START_DATE, FULL_END_DATE, "d")
                get_buy_point(symbol, df)
            except Exception as exc:
                print(f"处理 {symbol} 失败：{exc}")
            if i % 100 == 0:
                print_statistics()
        print_statistics()
        if trade_records:
            pd.DataFrame([{k: v for k, v in rec.items() if k != "marks"}
                          for rec in trade_records]).to_csv(
                os.path.join(get_data_dir(), "chan_buy_point_trades.csv"),
                index=False, encoding="utf-8-sig")
        simulate_portfolio(save_path=os.path.join(get_data_dir(), "chan_buy_point_equity.csv"))
    finally:
        if DATA_SOURCE == "watchlist":
            bs.logout()


if __name__ == "__main__":
    main()
