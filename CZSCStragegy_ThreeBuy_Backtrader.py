# coding: utf-8
"""
缠论三买 — Backtrader 回测实现

公式来源：CZSCStragegy_ThreeBuy.py（手动回测版）
  1. 逐K线喂入CZSC，用 finished_bis 避免未来函数
  2. 检查缠论三买：当前下跌笔终点>中枢上高，前上涨笔起点<中枢上高

信号触发后次日开盘买入，持有 hold_days 日后卖出。
"""
import os
import sys
import sqlite3
import backtrader as bt
import pandas as pd
import numpy as np
from collections import OrderedDict
from czsc_daily_util import get_daily_symbols, get_stock_pd, get_stock_bars
from czsc.utils.sig import get_zs_seq
from czsc.objects import RawBar, Freq
from czsc.analyze import CZSC
from czsc.enum import Direction, Mark

HOLD_DAYS = 5
DAILY_RETURN = 0

# ============================================================
#  信号计算（复用原始策略逻辑，无未来函数）
# ============================================================

def check_three_buy(bi_list, zs_list):
    if not bi_list:
        return False, None, None

    last_bi = bi_list[-1]
    if last_bi.direction != Direction.Down:
        return False, None, None

    last_zs = None
    for zs in reversed(zs_list):
        if zs.is_valid:
            last_zs = zs
            break
    if last_zs is None or len(last_zs.bis) <= 4:
        return False, None, None

    zs_last_bi = last_zs.bis[-1]
    last_up_bi = bi_list[-2]

    if last_bi.fx_b.fx <= last_zs.zg:
        return False, None, None
    if zs_last_bi.fx_b.dt >= last_bi.fx_b.dt:
        return False, None, None
    if last_up_bi.fx_a.fx >= last_zs.zg:
        return False, None, None

    return True, last_bi, last_zs


def calculate_threebuy_signal(df):
    if df is None or len(df) < 300:
        return None

    symbol = df['code'].iloc[0] if 'code' in df.columns else 'unknown'

    bars = []
    for i, row in df.iterrows():
        dt_val = pd.to_datetime(row['date'])
        bars.append(RawBar(
            symbol=symbol, id=i, freq=Freq.D,
            open=float(row['open']), close=float(row['close']),
            high=float(row['high']), low=float(row['low']),
            vol=float(row['volume']), amount=0.0,
            dt=dt_val,
        ))

    signal = np.zeros(len(df), dtype=bool)
    date_to_index = {str(d): idx for idx, d in enumerate(df['date'])}

    c = CZSC.__new__(CZSC)
    c.verbose = False
    c.max_bi_num = 500
    c.bars_raw = []
    c.bars_ubi = []
    c.bi_list = []
    c.symbol = symbol
    c.freq = Freq.D
    c.get_signals = None
    c.signals = None
    c.cache = OrderedDict()

    prev_bi_count = 0

    for bar in bars:
        c.update(bar)

        if len(c.bi_list) <= prev_bi_count:
            continue
        prev_bi_count = len(c.bi_list)

        finished = c.finished_bis
        if len(finished) < 6:
            continue

        zs_list = get_zs_seq(finished)

        is_buy, last_bi, last_zs = check_three_buy(finished, zs_list)
        if not is_buy:
            continue

        k1, k2, k3 = last_bi.fx_b.new_bars
        buy_date_str = k3.dt.strftime("%Y-%m-%d")
        if buy_date_str not in date_to_index:
            continue

        buy_idx = date_to_index[buy_date_str]
        if buy_idx >= len(df) or (buy_idx + HOLD_DAYS) >= len(df):
            continue

        signal[buy_idx] = True

    return pd.Series(signal, index=df.index)


# ============================================================
#  Backtrader 框架
# ============================================================

def _new_bt_stats():
    return {
        "trade_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "total_profit": 0.0,
        "returns": [],
        "ratio_map": {x: [] for x in range(1, HOLD_DAYS + 1)},
        "symbols": [],
    }


class SignalPandasData(bt.feeds.PandasData):
    lines = ("threebuy",)
    params = (
        ("threebuy", "threebuy"),
    )


class ThreeBuyStrategy(bt.Strategy):
    params = (
        ("hold_days", HOLD_DAYS),
        ("printlog", False),
    )

    def __init__(self):
        self.signal_line = self.datas[0].threebuy

        self.order = None
        self.entry_price = 0.0
        self.entry_bar = 0
        self.bars_held = 0

        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0.0
        self.returns = []
        self.ratio_map = {x: [] for x in range(1, self.params.hold_days + 1)}
        self._current_daily_rets = []
        self._pending_buy = False

    def log(self, txt):
        if self.params.printlog:
            print("{} {}".format(self.datas[0].datetime.date(0), txt))

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                self.entry_price = order.executed.price
                self.log("买入 价格={:.2f}".format(self.entry_price))
            else:
                profit_pct = (order.executed.price - self.entry_price) / self.entry_price * 100
                self.trade_count += 1
                if profit_pct > 0:
                    self.win_count += 1
                else:
                    self.loss_count += 1
                self.total_profit += profit_pct
                self.returns.append(profit_pct)
                for d, ret in enumerate(self._current_daily_rets, 1):
                    if d in self.ratio_map:
                        self.ratio_map[d].append(ret)
                self.log("卖出 价格={:.2f} 收益={:+.2f}%".format(
                    order.executed.price, profit_pct))

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            pass

        self.order = None

    def next(self):
        if self.order:
            return

        if self.position:
            self.bars_held += 1
            current_close = self.data.close[0]
            daily_ret = round((current_close - self.entry_price) / self.entry_price * 100, 2)
            self._current_daily_rets.append(daily_ret)

            if self.bars_held >= self.params.hold_days or daily_ret>DAILY_RETURN:
                self.order = self.close()
            return

        if self._pending_buy:
            self._pending_buy = False
            self.order = self.buy()
            self.entry_bar = len(self)
            self.bars_held = 0
            self._current_daily_rets = []
            return

        raw = self.signal_line[0]
        if isinstance(raw, np.generic):
            raw = raw.item()
        signal_on = raw > 0 if not isinstance(raw, bool) else raw

        if signal_on:
            self._pending_buy = True
            self.log("信号触发 三买")


def prepare_dataframe(df):
    signal = calculate_threebuy_signal(df)
    if signal is None:
        return None

    out = df[["open", "high", "low", "close", "volume"]].copy()
    out["threebuy"] = signal.fillna(False).astype(int)

    out["datetime"] = pd.to_datetime(df["date"])
    out.set_index("datetime", inplace=True)
    out.sort_index(inplace=True)
    return out


def run_single_backtest(df_bt, cash=1000000, commission=0.0003):
    cerebro = bt.Cerebro()
    data = SignalPandasData(dataname=df_bt)
    cerebro.adddata(data)
    cerebro.addstrategy(ThreeBuyStrategy, printlog=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    results = cerebro.run()
    strat = results[0]
    return strat


def _merge_stats(stats_dict, strat, symbol):
    s = stats_dict
    s["trade_count"] += strat.trade_count
    s["win_count"] += strat.win_count
    s["loss_count"] += strat.loss_count
    s["total_profit"] += strat.total_profit
    s["returns"].extend(strat.returns)
    for d in range(1, HOLD_DAYS + 1):
        s["ratio_map"][d].extend(strat.ratio_map.get(d, []))
    if strat.trade_count > 0:
        s["symbols"].append(symbol)


def print_statistics(stats_dict):
    print()
    print("=" * 100)
    print("  缠论三买策略 — Backtrader 回测结果（全市场）")
    print("=" * 100)

    s = stats_dict
    total = s["trade_count"]
    if total == 0:
        print("  无交易信号")
        print("=" * 100)
        return

    win_rate = s["win_count"] / total * 100
    avg_ret = s["total_profit"] / total
    all_ret = np.array(s["returns"])

    print("  交易数：{}".format(total))
    print("  胜率：{:.1f}%".format(win_rate))
    print("  平均收益：{:+.2f}%".format(avg_ret))
    print("  总收益：{:+.2f}%".format(s["total_profit"]))
    print("  最大单笔收益：{:+.2f}%".format(np.max(all_ret)))
    print("  最小单笔收益：{:+.2f}%".format(np.min(all_ret)))
    print("  中位数收益：{:+.2f}%".format(np.median(all_ret)))
    print("  95%分位：{:+.2f}%".format(np.percentile(all_ret, 95)))
    print("  5%分位：{:+.2f}%".format(np.percentile(all_ret, 5)))
    print("  涉及股票数：{}".format(len(set(s["symbols"]))))

    print()
    print("  --- 逐日收益明细 ---")
    day_header = "  {:>6}".format("天数")
    day_header += " {:>10}".format("均值%")
    day_header += " {:>10}".format("中位数%")
    day_header += " {:>10}".format("胜率%")
    day_header += " {:>10}".format("总正")
    day_header += " {:>10}".format("总负")
    print(day_header)
    print("  " + "-" * 60)

    for d in range(1, HOLD_DAYS + 1):
        arr = np.array(s["ratio_map"].get(d, []))
        if len(arr) == 0:
            continue
        day_plus = np.sum(arr > 0)
        print("  {:>6} {:>+9.2f}% {:>+9.2f}% {:>9.1f}% {:>10.2f} {:>10.2f}".format(
            d, np.mean(arr), np.median(arr),
            100 * day_plus / len(arr),
            np.sum(arr[arr > 0]),
            np.sum(arr[arr <= 0]),
        ))

    print("=" * 100)


if __name__ == "__main__":
    start_date = "2020-01-01"
    end_date = "2025-12-31"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)

    print("[{}] 开始批量加载数据...".format(pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sqlite3.db'))
    all_data = pd.read_sql(
        "SELECT DISTINCT code, date, open, high, low, close, volume FROM STOCK_DAILY "
        "WHERE frequency = 'd' AND date >= ? AND date <= ? ORDER BY code, date",
        conn, params=(start_date, end_date)
    )
    conn.close()
    print("[{}] 批量加载完成，共 {} 行，{} 只股票".format(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        len(all_data), all_data['code'].nunique()))

    all_data['open'] = all_data['open'].astype(float)
    all_data['high'] = all_data['high'].astype(float)
    all_data['low'] = all_data['low'].astype(float)
    all_data['close'] = all_data['close'].astype(float)
    all_data['volume'] = all_data['volume'].astype(float)

    bt_stats = _new_bt_stats()
    processed = 0
    skipped = 0

    for symbol, df in all_data.groupby('code'):
        processed += 1
        if processed % 100 == 0:
            print("[{}] 进度：{} / {}，跳过：{}，交易：{}".format(
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
                processed, total, skipped, bt_stats["trade_count"]))
            print_statistics(bt_stats)

        try:
            if len(df) < 300:
                skipped += 1
                continue

            signal = calculate_threebuy_signal(df.reset_index(drop=True))
            if signal is None or not signal.any():
                skipped += 1
                continue

            out = df[["open", "high", "low", "close", "volume"]].copy()
            out = out.reset_index(drop=True)
            out["threebuy"] = signal.fillna(False).astype(int)
            out["datetime"] = pd.to_datetime(df["date"].values)
            out.set_index("datetime", inplace=True)
            out.sort_index(inplace=True)

            strat = run_single_backtest(out, cash=1000000, commission=0.0003)
            _merge_stats(bt_stats, strat, symbol)
        except Exception:
            skipped += 1
            continue

    print_statistics(bt_stats)
'''
====================================================================================================
  缠论三买策略 — Backtrader 回测结果（全市场）
====================================================================================================
  交易数：19789
  胜率：82.2%
  平均收益：+1.89%
  总收益：+37428.14%
  最大单笔收益：+44.28%
  最小单笔收益：-32.31%
  中位数收益：+1.42%
  95%分位：+8.23%
  5%分位：-3.23%
  涉及股票数：4221

  --- 逐日收益明细 ---
      天数        均值%       中位数%        胜率%         总正         总负
  ------------------------------------------------------------
       1     +1.06%     +0.64%      62.0%   31897.93  -10991.23
       2     -0.59%     -0.55%      40.0%    7293.35  -11695.24
       3     -1.28%     -0.93%      33.7%    3393.22   -9185.89
       4     -2.65%     -2.01%      22.4%    1492.77   -9422.06
       5     -3.15%     -2.34%      19.7%     871.33   -8171.55
====================================================================================================
'''