# coding: utf-8
"""CTD6 信号回测，使用趋势共振脚本的交易、统计和组合资金曲线口径。

信号直接调用 CZSCStragegy_OversoldRebound_org.calculate_oversold_indicators，
只取 CTD6，不混入 XL3；原文件的 CAPITAL、COST/WINNER 近似计算保持不变。
所需行情列：date、open、high、low、close、volume、amount、turn，至少 120 根。

持仓规则：
* 信号次日开盘买入；持仓期间新 CTD6 信号次日开盘等金额加仓。
* 每次加仓资金等于首次实际投入资金，均价按总成本/总股数计算。
* 从最后一次实际买入起重新计 hold_days；信号可延续持仓，不设累计最大天数。
* 开盘止盈优先于加仓；未止盈则执行加仓，再检查到期，到期按开盘退出。
* 加仓日不做收盘全仓卖出；后续按均价和 TAKE_PROFIT_RATE 检查止盈。
* 只有止盈/到期，没有止损；统计每段完整持仓为一笔，末尾未到期默认不计平仓统计。
* 组合每次买入/加仓固定投入 POSITION_AMOUNT（含买入手续费）；资金不足则跳过，
  均价和到期日不变。组合按真实成交重算退出，不复用资金无限情况下的退出计划。
* 逐日收益从最后加仓后的第 1 日统计；持有期曾盈利使用各日当时的真实均价。
* 持仓期间正收益占比：曾出现正收益的已平仓交易数 / 全部已平仓交易数；
  使用持仓各日收盘收益和实际退出收益，包含买入/加仓日，零收益不算正收益。
保留 ST/688 过滤和原 CTD6 计算。收益和组合输出结构保持，未模拟涨跌停成交限制。

直接运行本文件；在顶部配置 DATA_SOURCE、日期、hold_days 等参数。
资金曲线默认写入 data/ctd6_equity.csv 和 data/ctd6_equity.png。
"""
import os
import pandas as pd
import numpy as np
import baostock as bs
from CZSCStragegy_OversoldRebound_org import calculate_oversold_indicators
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

hold_days = 10
TAKE_PROFIT_RATE = 0.1

# 持有期内的新信号合并为等金额加仓，不再使用固定信号间距过滤。

# 数据源：
#   "cache"     本地日线缓存 data/.cache（2024-01-01 ~ 2026-09-10，约 25ms/只，全市场约 2 分钟）
#   "sqlite"    本地全历史库 data/sqlite3.db（2000-01-04 ~ 2026-08-31，约 4s/只，全市场约 5 小时）
#   "watchlist" 读取自选股 JSON 后联网取数（需 baostock 登录）
DATA_SOURCE = "sqlite"
WATCHLIST_FILE = "./data/超跌反弹.json"

# 全市场回测区间（sqlite 数据源可拉到 2000 年；cache 数据源请用 2024-01-01 ~ 2026-09-10）
FULL_START_DATE = "2024-01-01"
FULL_END_DATE = "2026-09-30"
# sqlite 数据源使用的长历史区间
SQLITE_START_DATE = "2020-01-01"

# 是否逐笔打印买卖明细（ADXBreak 参考实现是直接打印的）
VERBOSE_TRADES = True

# 是否跳过持有期不完整的交易
# ADXBreak 参考实现会把出场日夹到数据最后一天，从而产生「持有 0 天、收益 0%」的退化交易
# 并被计入负收益，这里默认跳过，保证统计口径干净；置 False 可还原参考实现的行为
SKIP_INCOMPLETE_TRADES = True

SIGNAL_KEYS = ["CTD6", "总计"]

# 逐笔交易明细和组合交易日历，供回测结束后生成逐日资金曲线。
trade_records = []
market_frames = {}  # 保存逐日信号供组合按实际可用资金重放；包含未到期持仓。
portfolio_trade_records = []
portfolio_metrics = {}
trading_calendar = set()

# 组合资金曲线参数：每次买入和加仓投入固定金额，不随组合权益变化。
INIT_CAPITAL = 1000000.0
# 单次投入金额（元，含买入手续费）。
POSITION_AMOUNT = 40000.0
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
        # 每笔交易在持有期内是否曾出现过正收益。
        "positive_horizon": [],
    }


signal_stats = {k: _new_stats() for k in SIGNAL_KEYS}


# ============================================================
# Indicator calculation
# ============================================================

def calculate_indicators(df):
    """完整复用原文件指标计算，保持 CTD6 的所有中间变量及初始化逻辑。"""
    return calculate_oversold_indicators(df)


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
    沿用趋势共振回测的股票池过滤：排除 ST / *ST / 科创板(688)。
    """
    code = symbol.split('.')[-1]
    if code.startswith('688'):
        return True
    return 'ST' in get_symbol_name(symbol).upper()


# ============================================================
# Trade recording
# ============================================================

def _new_position(symbol):
    return {"symbol": symbol, "entries": [], "shares": 0., "cost": 0.,
            "budget": None, "due_idx": None, "observations": [], "marks": {}}


def _step_position(symbol, df, idx, position, allocate):
    """单股和组合共用：开盘止盈 -> 昨日信号买入/加仓 -> 到期 -> 收盘止盈。

    allocate(position, price) 返回本次实际股数和投入本金；资金不足返回 None。
    同一持仓每次投入相同金额；加仓日不做收盘全仓卖出，避免卖出当日新买股。
    """
    open_price = float(df["open"].iloc[idx])
    close_price = float(df["close"].iloc[idx])
    date = df["date"].iloc[idx]
    if position is not None:
        avg = position["cost"] / position["shares"]
        if open_price >= avg * (1 + TAKE_PROFIT_RATE):
            return None, _finish_position(position, df, idx, open_price, "止盈", "open")

    signal = idx > 0 and bool(df["CTD6"].iloc[idx - 1])
    if signal:
        candidate = position if position is not None else _new_position(symbol)
        fill = allocate(candidate, open_price)
        if fill is not None:
            shares, cost = fill
            candidate["shares"] += shares
            candidate["cost"] += cost
            candidate["entries"].append({
                "idx": idx, "date": date, "price": open_price,
                "signal_date": df["date"].iloc[idx - 1], "shares": shares, "cost": cost,
            })
            candidate["due_idx"] = idx + hold_days
            position = candidate
    if position is None:
        return None, None

    if idx >= position["due_idx"]:
        return None, _finish_position(position, df, idx, open_price, "到期", "open")

    position["marks"][date] = close_price
    avg = position["cost"] / position["shares"]
    ratio = 100 * (close_price / avg - 1)
    last_idx = position["entries"][-1]["idx"]
    position["observations"].append((idx, idx - last_idx, ratio))
    if idx > last_idx and close_price >= avg * (1 + TAKE_PROFIT_RATE):
        return None, _finish_position(position, df, idx, close_price, "止盈", "close")
    return position, None


def _finish_position(position, df, idx, price, reason, session):
    avg = position["cost"] / position["shares"]
    ret = 100 * (price / avg - 1)
    date = df["date"].iloc[idx]
    last_idx = position["entries"][-1]["idx"]
    observations = list(position["observations"])
    if not observations or observations[-1][0] != idx:
        observations.append((idx, idx - last_idx, ret))
    marks = dict(position["marks"])
    marks[date] = price
    return {
        "symbol": position["symbol"], "entry_date": position["entries"][0]["date"],
        "exit_date": date, "entry_price": avg, "exit_price": price, "ret": ret,
        "kind": reason, "exit_session": session, "marks": marks,
        "entries": list(position["entries"]), "add_count": len(position["entries"]) - 1,
        "last_entry_date": position["entries"][-1]["date"],
        "holding_days": idx - position["entries"][0]["idx"],
        "shares": position["shares"], "cost": position["cost"],
        "observations": observations, "exit_idx": idx, "source_frame": df,
    }


def _record_completed_trade(record, label="CTD6"):
    """每段持仓计一笔交易；逐日统计从最后加仓起算，不使用未来均价回算历史。"""
    last_idx = record["entries"][-1]["idx"]
    peak = max([record["ret"]] + [r for _, _, r in record["observations"]])
    labels = [label] if label == "总计" else [label, "总计"]
    for key in labels:
        stats = signal_stats[key]
        (stats["plus"] if record["ret"] > 0 else stats["minus"]).append(record["ret"])
        stats["count"] += 1
        stats["symbols"].append(record["symbol"])
        stats["pyramid_counts"].append(len(record["entries"]))
        stats["hold_days_list"].append(record["holding_days"])
        stats["positive_horizon"].append(peak > 0)
        reason = record["kind"]
        stats["exit_reasons"][reason] = stats["exit_reasons"].get(reason, 0) + 1
        for idx, offset, ret in record["observations"]:
            if idx > last_idx and 1 <= offset <= hold_days:
                stats["ratio_map"][offset].append(round(ret, 2))
    trade_records.append(record)
    if VERBOSE_TRADES:
        for i, entry in enumerate(record["entries"]):
            print("{} {} 信号日:{} [CTD6] 买入:{} 价:{:.2f}".format(
                record["symbol"], "买" if i == 0 else "加仓", entry["signal_date"], entry["date"], entry["price"]))
        print("{} {} 卖出:{} 价:{:.2f} 均价:{:.2f} 加仓:{}次 收益:{:.2f}% 最大:{:.2f}%".format(
            record["symbol"], record["kind"], record["exit_date"], record["exit_price"],
            record["entry_price"], record["add_count"], record["ret"], peak))


def get_buy_point(symbol, df):
    """合并持有期内 CTD6 信号，每次等金额加仓并重置到期日。"""
    if df is None or len(df) < 120:
        return
    ndf = calculate_indicators(df)
    if ndf is None:
        return
    trading_calendar.update(ndf["date"].tolist())
    if is_excluded_symbol(symbol):
        return
    ndf = ndf[["date", "open", "close", "CTD6"]].copy().reset_index(drop=True)
    ndf["CTD6"] = ndf["CTD6"].fillna(False).astype(bool)
    if not ndf["CTD6"].any():
        return
    dates = pd.to_datetime(ndf["date"])
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("日线日期必须有效、递增且无重复")
    prices = ndf[["open", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("成交和估值价格必须是有限正数")
    market_frames[symbol] = ndf
    position = None
    # 用每次 1 元的等额单位模拟，不影响均价及收益百分比。
    def allocate(pos, price):
        pos["budget"] = 1.
        return 1. / price, 1.

    for idx in range(len(ndf)):
        position, closed = _step_position(symbol, ndf, idx, position, allocate)
        if closed is not None:
            _record_completed_trade(closed)
    if position is not None:
        if SKIP_INCOMPLETE_TRADES:
            if VERBOSE_TRADES:
                print("{} 未到期 买入:{} 最后加仓:{} 加仓:{}次".format(
                    symbol, position["entries"][0]["date"], position["entries"][-1]["date"],
                    len(position["entries"]) - 1))
        else:
            _record_completed_trade(_finish_position(
                position, ndf, len(ndf) - 1, float(ndf["close"].iloc[-1]), "到期", "close"))


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
    print("  最终正收益占比：{:.2f}%".format(100 * len(plus) / total))
    positive_horizon = stats.get("positive_horizon", [])
    if len(positive_horizon) == total:
        horizon_plus = sum(bool(x) for x in positive_horizon)
        print("  持有期内曾正收益次数：{}".format(horizon_plus))
        print("  持仓期间正收益占比：{:.2f}%（{} / {} 笔已平仓交易）".format(
            100 * horizon_plus / total, horizon_plus, total))
    else:
        print("  持仓期间正收益占比：--（缺少持仓收益记录）")

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

    if stats["pyramid_counts"]:
        add_counts = [n - 1 for n in stats["pyramid_counts"]]
        print("  加仓次数：总计={}  平均加仓次数={:.2f}  最大加仓次数={}".format(
            sum(add_counts), np.mean(add_counts), max(add_counts)))

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
    print("  CTD6 策略 — 统计结果")
    print("=" * 70)

    for key in SIGNAL_KEYS:
        _print_signal_header(key)
        _print_signal_stats(key, signal_stats[key])


# ============================================================
# 组合资金曲线：固定金额、逐日结算
# ============================================================

def _metrics(curve, records, init_capital):
    """与 GoldenPoint 同口径；records 为组合实际平仓记录，收益使用百分数。

    日收益含初始资金到首日的变化；252 日年化，无风险收益为 0。
    盈亏比/盈利因子使用逐笔收益率；胜率排除零收益，交易次数包含零收益。
    持仓期间正收益占比使用当时均价下的逐日收盘收益及退出收益，分母含零收益交易。
    加仓次数仅统计已平仓交易的实际加仓，平均值包含未加仓的交易，首次买入不计入。
    records=None 表示只有资金曲线，交易指标未知（不能从权益变化反推）。
    """
    frame = pd.DataFrame(curve)
    if frame.empty:
        return {}
    values = frame["equity"].to_numpy(dtype=float)
    daily = np.diff(np.r_[init_capital, values]) / np.r_[init_capital, values[:-1]]
    daily = daily[np.isfinite(daily)]
    years = len(values) / 252
    annual = (values[-1] / init_capital) ** (1 / years) - 1 if years and values[-1] > 0 else np.nan
    max_dd = float((values / np.maximum.accumulate(np.r_[init_capital, values])[1:] - 1).min())
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) and daily.std() > 0 else np.nan
    known_records = records is not None
    records = [] if records is None else records
    wins = [float(r["ret"]) for r in records if float(r["ret"]) > 0]
    losses = [float(r["ret"]) for r in records if float(r["ret"]) < 0]
    horizon_known = known_records and all("observations" in r for r in records)
    horizon_count = sum(
        r["ret"] > 0 or any(ret > 0 for _, _, ret in r["observations"])
        for r in records
    ) if horizon_known else None
    adds_known = known_records and all("add_count" in r for r in records)
    add_counts = [r["add_count"] for r in records] if adds_known else []
    return {
        "total_return": values[-1] / init_capital - 1,
        "annual_return": annual, "alpha": annual, "sharpe": sharpe,
        "max_drawdown": max_dd,
        "profit_loss_ratio": np.mean(wins) / abs(np.mean(losses)) if wins and losses else np.nan,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (np.inf if wins else np.nan),
        "win_rate": len(wins) / (len(wins) + len(losses)) if wins or losses else np.nan,
        "trade_count": len(records) if known_records else None,
        "positive_horizon_count": horizon_count,
        "positive_horizon_rate": horizon_count / len(records) if horizon_known and records else np.nan,
        "avg_add_count": float(np.mean(add_counts)) if add_counts else np.nan,
        "max_add_count": max(add_counts) if add_counts else np.nan,
    }


def simulate_portfolio(records=None, position_amount=POSITION_AMOUNT, fee_rate=FEE_RATE,
                       init_capital=INIT_CAPITAL, save_path=None, image_path=None):
    """每次买入/加仓固定投入 position_amount（含买入手续费）。

    现金不足则跳过该次买入/加仓，不缩减金额，也不重置到期日。
    默认处理 get_buy_point 已载入的全部行情（包括尚未平仓的信号）。
    records 可传本模块产生的记录，以其对应完整行情重新计算组合。
    """
    global portfolio_trade_records, portfolio_metrics
    portfolio_trade_records = []
    portfolio_metrics = {}
    if (not np.isfinite([position_amount, init_capital, fee_rate]).all()
            or position_amount <= 0 or init_capital <= 0 or fee_rate < 0):
        raise ValueError("单次投入金额和初始资金须为正，手续费不得为负，且参数须为有限数值")
    frames = market_frames if records is None else {r["symbol"]: r["source_frame"] for r in records}
    if not frames:
        print("\n没有交易记录，无法生成资金曲线")
        return None
    events = {}
    starts = []
    for symbol, df in frames.items():
        signal_idxs = np.flatnonzero(df["CTD6"].fillna(False).to_numpy())
        starts.extend(df["date"].iloc[i + 1] for i in signal_idxs if i + 1 < len(df))
        for idx, day in enumerate(df["date"]):
            events.setdefault(day, []).append((symbol, idx))
    if not starts:
        print("\n没有交易记录，无法生成资金曲线")
        return None
    days = sorted(d for d in events if d >= min(starts))
    cash = float(init_capital)
    positions = {}
    last_closes = {}
    curve = []
    skipped = 0
    invested_sum = 0.

    def settle(record):
        nonlocal cash
        cash += record["shares"] * record["exit_price"] * (1 - fee_rate)
        portfolio_trade_records.append(record)

    for day in days:
        day_events = sorted(events[day])
        exited_at_open = set()
        # 所有股票的已知开盘退出先结算；收盘退出的现金只能留到下一交易日使用。
        for symbol, idx in day_events:
            pos = positions.get(symbol)
            if pos is None:
                continue
            df = frames[symbol]
            price = float(df["open"].iloc[idx])
            target = pos["cost"] / pos["shares"] * (1 + TAKE_PROFIT_RATE)
            signal = idx > 0 and bool(df["CTD6"].iloc[idx - 1])
            if price >= target or (idx >= pos["due_idx"] and not signal):
                reason = "止盈" if price >= target else "到期"
                settle(_finish_position(pos, df, idx, price, reason, "open"))
                positions.pop(symbol)
                exited_at_open.add(symbol)

        close_exits = []
        for symbol, idx in day_events:
            if symbol in exited_at_open:
                continue
            df = frames[symbol]

            def allocate(pos, price):
                nonlocal cash, skipped
                budget = position_amount
                if cash + 1e-9 < budget:
                    skipped += 1
                    return None
                pos["budget"] = budget
                cost = budget / (1 + fee_rate)
                cash -= budget
                return cost / price, cost

            pos, closed = _step_position(symbol, df, idx, positions.get(symbol), allocate)
            if pos is not None and idx == len(df) - 1 and not SKIP_INCOMPLETE_TRADES:
                closed = _finish_position(pos, df, idx, float(df["close"].iloc[idx]), "到期", "close")
                pos = None
            if pos is None:
                positions.pop(symbol, None)
            else:
                positions[symbol] = pos
            if closed is not None:
                if closed["exit_session"] == "open":
                    settle(closed)
                else:
                    close_exits.append(closed)
        for closed in close_exits:
            settle(closed)
        for symbol, idx in day_events:
            last_closes[symbol] = float(frames[symbol]["close"].iloc[idx])
        market_value = sum(pos["shares"] * last_closes[symbol] for symbol, pos in positions.items())
        equity = cash + market_value
        curve.append({"date": day, "equity": equity, "cash": cash,
                      "market_value": market_value, "positions": len(positions)})
        if equity > 0:
            invested_sum += market_value / equity

    if not curve:
        print("\n没有有效交易日，无法生成资金曲线")
        return None

    eq = np.array([item["equity"] for item in curve], dtype=float)
    metrics = _metrics(curve, portfolio_trade_records, init_capital)
    portfolio_metrics = metrics
    max_pos = max(item["positions"] for item in curve)

    print("\n" + "=" * 80)
    print("组合资金曲线（固定金额、逐日结算）")
    print("=" * 80)
    print("初始资金：{:.0f}    每次买入/加仓：{:.2f} 元（含买入手续费）    单边手续费：{:.4%}".format(
        init_capital, position_amount, fee_rate))
    print("回测区间：{} ~ {}（{} 个交易日）".format(curve[0]["date"], curve[-1]["date"], len(curve)))
    print("期末权益：{:.2f}".format(eq[-1]))
    print("组合总收益：{:.2f}%".format(metrics["total_return"] * 100))
    print("年化收益：{:.2f}%".format(metrics["annual_return"] * 100))
    print("最大回撤：{:.2f}%".format(metrics["max_drawdown"] * 100))
    print("日收益夏普：{:.2f}".format(metrics["sharpe"]))
    num = lambda value: "--" if not np.isfinite(value) else f"{value:.2f}"
    print("Alpha(无风险0%)：{}%  盈亏比：{}  盈利因子：{}  胜率：{}%  交易次数：{}".format(
        num(metrics["alpha"] * 100), num(metrics["profit_loss_ratio"]),
        num(metrics["profit_factor"]), num(metrics["win_rate"] * 100), metrics["trade_count"]))
    print("持仓期间正收益占比：{}%（{} / {} 笔已平仓交易）".format(
        num(metrics["positive_horizon_rate"] * 100),
        metrics["positive_horizon_count"], metrics["trade_count"]))
    max_adds = "--" if not np.isfinite(metrics["max_add_count"]) else str(int(metrics["max_add_count"]))
    print("平均加仓次数：{} 次    最大加仓次数：{} 次（已平仓交易）".format(
        num(metrics["avg_add_count"]), max_adds))
    print("最大同时持仓：{} 笔    平均资金占用：{:.1f}%".format(
        max_pos, invested_sum / len(curve) * 100))
    if skipped:
        print("因现金不足被跳过的买入/加仓：{} 次".format(skipped))

    print("组合实际平仓：{} 笔    期末未平仓：{} 笔".format(len(portfolio_trade_records), len(positions)))

    if save_path:
        pd.DataFrame(curve).to_csv(save_path, index=False, encoding="utf-8-sig")
        print("资金曲线已保存到 {}".format(save_path))
    if image_path:
        plot_equity_curve(curve, image_path, init_capital=init_capital, metrics=metrics)
    return curve


def plot_equity_curve(curve, image_path, init_capital=INIT_CAPITAL, metrics=None):
    """输出权益与回撤 PNG；支持逐日记录或已有 CSV 转成的 DataFrame。"""
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.dates import AutoDateLocator, ConciseDateFormatter
    from matplotlib.ticker import StrMethodFormatter

    frame = pd.DataFrame(curve)
    if frame.empty:
        return None
    dates = pd.to_datetime(frame["date"])
    equity = frame["equity"].to_numpy(dtype=float)
    # 与 simulate_portfolio 打印的回撤使用相同口径。
    drawdown = (equity / np.maximum.accumulate(np.r_[init_capital, equity])[1:] - 1) * 100
    if metrics is None:
        metrics = _metrics(frame, None, init_capital)
    pct = lambda value: "--" if not np.isfinite(value) else f"{value * 100:.2f}%"
    num = lambda value: "--" if not np.isfinite(value) else f"{value:.2f}"
    count = "--" if metrics["trade_count"] is None else str(metrics["trade_count"])
    fig = Figure(figsize=(14, 8), layout="constrained")
    FigureCanvasAgg(fig)
    ax1, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(dates, equity, color="#1565c0", linewidth=1.6, label="Portfolio equity")
    ax1.axhline(init_capital, color="#888888", linestyle="--", linewidth=1, label="Initial capital")
    ax1.set_title("CTD6 Portfolio Equity", fontsize=16, loc="left", pad=12)
    ax1.set_ylabel("Equity (CNY)")
    ax1.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax1.text(0.01, 0.97,
             f"Final equity: {equity[-1]:,.2f} CNY  |  Return: {pct(metrics['total_return'])}  |  Annual: {pct(metrics['annual_return'])}\n"
             f"Alpha (RF=0%): {pct(metrics['alpha'])}  |  Sharpe: {num(metrics['sharpe'])}  |  Max drawdown: {pct(metrics['max_drawdown'])}\n"
             f"Profit/loss ratio: {num(metrics['profit_loss_ratio'])}  |  Profit factor: {num(metrics['profit_factor'])}  |  Win rate: {pct(metrics['win_rate'])}\n"
             f"Closed trades: {count}  |  Trading days: {len(frame)}\n"
             f"Ever profitable (closed trades): {pct(metrics.get('positive_horizon_rate', np.nan))}\n"
             f"Adds per closed trade: Avg {num(metrics.get('avg_add_count', np.nan))}  |  "
             f"Max {num(metrics.get('max_add_count', np.nan))}",
             transform=ax1.transAxes, va="top", fontsize=10,
             bbox=dict(facecolor="white", edgecolor="#dddddd", alpha=.9, boxstyle="round,pad=0.5"))
    ax1.legend(loc="lower left")
    ax2.fill_between(dates, drawdown, 0, color="#d32f2f", alpha=.25)
    ax2.plot(dates, drawdown, color="#b71c1c", linewidth=1)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    locator = AutoDateLocator(minticks=4, maxticks=10)
    ax2.xaxis.set_major_locator(locator)
    ax2.xaxis.set_major_formatter(ConciseDateFormatter(locator))
    for ax in (ax1, ax2):
        ax.grid(True, alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
    os.makedirs(os.path.dirname(os.path.abspath(image_path)), exist_ok=True)
    try:
        fig.savefig(image_path, format="png", dpi=160)
    finally:
        fig.clear()
    print("资金曲线图片已保存到 {}".format(image_path))
    return image_path


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
    print("信号模式：CTD6原始  加仓：等首次金额  持有期：最后买入后{}日".format(hold_days))

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
    simulate_portfolio(save_path=os.path.join(get_data_dir(), "ctd6_equity.csv"),
                       image_path=os.path.join(get_data_dir(), "ctd6_equity.png"))

    if use_bs:
        bs.logout()
