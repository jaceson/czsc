# coding: utf-8
"""
超跌反弹策略 — Backtrader 回测实现

分别用 XL3、CTD6、XL3+CTD6（买信号）、启动点、见底 五个信号作为买点，
持有 hold_days 日后卖出，对比各信号表现。
"""
import backtrader as bt
import pandas as pd
import numpy as np
from czsc_daily_util import get_daily_symbols
from czsc_sqlite import get_local_stock_data
from CZSCStragegy_OversoldRebound import calculate_oversold_indicators

SIGNAL_KEYS = ["XL3", "CTD6", "XL3+CTD6", "启动点", "见底"]
HOLD_DAYS = 5


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
    """自定义数据源：在标准 OHLCV 之外额外加载 5 个信号列"""
    lines = ("xl3", "ctd6", "xl3_ctd6", "launch", "bottom")
    params = (
        ("xl3", "xl3"),
        ("ctd6", "ctd6"),
        ("xl3_ctd6", "xl3_ctd6"),
        ("launch", "launch"),
        ("bottom", "bottom"),
    )


class OversoldReboundStrategy(bt.Strategy):
    """超跌反弹策略（单信号版）

    参数:
        signal_name: 使用的信号类型，取自 SIGNAL_KEYS
        hold_days:   持有天数
        printlog:    是否逐笔打印
    """
    params = (
        ("signal_name", "XL3"),
        ("hold_days", HOLD_DAYS),
        ("printlog", False),
    )

    def __init__(self):
        signal_line_map = {
            # "XL3": "xl3",
            # "CTD6": "ctd6",
            "XL3+CTD6": "xl3_ctd6",
            # "启动点": "launch",
            # "见底": "bottom",
        }
        line_name = signal_line_map[self.params.signal_name]
        self.signal_line = getattr(self.datas[0], line_name)

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
                self.log("卖出 价格={:.2f} 收益={:+.2f}%".format(
                    order.executed.price, profit_pct))

        elif order.status == order.Canceled:
            pass
        elif order.status == order.Margin:
            pass
        elif order.status == order.Rejected:
            pass

        self.order = None

    def next(self):
        if self.order:
            return

        # ---- 持仓中：每日记录 + 到期卖出 ----
        if self.position:
            self.bars_held += 1
            current_close = self.data.close[0]
            daily_ret = (current_close - self.entry_price) / self.entry_price * 100
            self._current_daily_rets.append(round(daily_ret, 2))

            if self.bars_held >= self.params.hold_days:
                self.order = self.close()
            return

        # ---- 空仓：执行上一 bar 积累的买入指令 ----
        if self._pending_buy:
            self._pending_buy = False
            self.order = self.buy()
            self.entry_bar = len(self)
            self.bars_held = 0
            self._current_daily_rets = []
            return

        # ---- 空仓：检测信号（当前 bar 发现信号 → 下个 bar 开盘买入） ----
        raw = self.signal_line[0]
        if isinstance(raw, np.generic):
            raw = raw.item()
        signal_on = raw > 0 if not isinstance(raw, bool) else raw

        if signal_on:
            self._pending_buy = True
            self.log("信号触发 signal={}".format(self.params.signal_name))

    def stop(self):
        """策略结束时，将累计的逐日收益写入 ratio_map"""
        if self.trade_count == 0:
            return
        if self.ratio_map is None:
            return
        for d in range(1, self.params.hold_days + 1):
            arr = self.ratio_map[d]
            if not arr:
                continue
            self.ratio_map[d] = arr


def prepare_dataframe(df):
    """对原始 df 计算指标，添加信号列，返回可用于 backtrader 的 DataFrame"""
    ndf = calculate_oversold_indicators(df)
    if ndf is None:
        return None

    out = ndf[["open", "high", "low", "close", "volume", "amount"]].copy()

    # 标准化信号列为 0/1
    out["xl3"] = ndf["XL3"].fillna(False).astype(int)
    out["ctd6"] = ndf["CTD6"].fillna(False).astype(int)
    out["xl3_ctd6"] = (out["xl3"] | out["ctd6"]).astype(int)
    out["launch"] = (ndf["启动点"].fillna(0) > 0).astype(int)
    out["bottom"] = ndf["见底"].fillna(False).astype(int)

    out["datetime"] = pd.to_datetime(ndf["date"])
    out.set_index("datetime", inplace=True)
    out.sort_index(inplace=True)
    return out


def run_single_backtest(df_bt, signal_name, cash=1000000, commission=0.0003):
    """运行单个信号的回测，返回统计结果 dict"""
    cerebro = bt.Cerebro()
    data = SignalPandasData(dataname=df_bt)
    cerebro.adddata(data)
    cerebro.addstrategy(OversoldReboundStrategy, signal_name=signal_name, printlog=False)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    results = cerebro.run()
    strat = results[0]
    return strat


def _merge_stats(stats_dict, strat, signal_name):
    """将单次回测的策略统计合并到总字典"""
    s = stats_dict[signal_name]
    s["trade_count"] += strat.trade_count
    s["win_count"] += strat.win_count
    s["loss_count"] += strat.loss_count
    s["total_profit"] += strat.total_profit
    s["returns"].extend(strat.returns)
    for d in range(1, HOLD_DAYS + 1):
        s["ratio_map"][d].extend(strat.ratio_map.get(d, []))


def print_signal_comparison(stats_dict, signal_keys):
    """打印各信号对比表格"""
    print()
    print("=" * 100)
    print("  超跌反弹策略 — Backtrader 回测对比（全市场）")
    print("=" * 100)
    header = "{:<14} {:>8} {:>8} {:>10} {:>10} {:>10} {:>10} {:>10}".format(
        "信号", "交易数", "胜率%", "平均收益%", "总收益%", "最大%", "最小%", "中位数%")
    print(header)
    print("-" * 100)

    for key in signal_keys:
        s = stats_dict[key]
        total = s["trade_count"]
        if total == 0:
            print("{:<14} {:>8}  {:>8}  {:>10}  {:>10}  {:>10}  {:>10}  {:>10}".format(
                key, 0, "-", "-", "-", "-", "-", "-"))
            continue
        win_rate = s["win_count"] / total * 100
        avg_ret = s["total_profit"] / total
        all_ret = np.array(s["returns"])
        print("{:<14} {:>8}  {:>7.1f}%  {:>+9.2f}%  {:>+9.2f}%  {:>+9.2f}%  {:>+9.2f}%  {:>+9.2f}%".format(
            key, total, win_rate, avg_ret, s["total_profit"],
            np.max(all_ret), np.min(all_ret), np.median(all_ret)))

    print("=" * 100)

    # 逐日收益明细
    print()
    print("-" * 100)
    print("  逐日收益明细")
    print("-" * 100)
    day_header = "{:<14}".format("信号")
    for d in range(1, HOLD_DAYS + 1):
        day_header += " {:>12}".format("第{}天".format(d))
    day_header += " {:>12}".format("最大回撤")
    print(day_header)
    print("-" * 100)

    for key in signal_keys:
        s = stats_dict[key]
        total = s["trade_count"]
        if total == 0:
            continue
        line = "{:<14}".format(key)
        max_drawdown = 0.0
        for d in range(1, HOLD_DAYS + 1):
            arr = np.array(s["ratio_map"].get(d, []))
            if len(arr) == 0:
                line += " {:>12}".format("-")
                continue
            val = np.mean(arr)
            line += " {:>+11.2f}%".format(val)

        # 计算逐日累计最大回撤（简化：取所有 day_offset 的最小均值）
        cum_means = []
        for d in range(1, HOLD_DAYS + 1):
            arr = np.array(s["ratio_map"].get(d, []))
            if len(arr) == 0:
                continue
            cum_means.append(np.mean(arr))
        if cum_means:
            max_dd = 0.0
            peak = cum_means[0]
            for v in cum_means:
                if v > peak:
                    peak = v
                dd = (peak - v) / (1 + peak / 100) if peak > 0 else 0
                max_dd = min(max_dd, dd)
            line += " {:>+11.2f}%".format(max_dd)
        print(line)
    print("-" * 100)


if __name__ == "__main__":
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)

    bt_stats = {k: _new_bt_stats() for k in SIGNAL_KEYS}

    for i, symbol in enumerate(all_symbols):
        print("[{}] 进度：{} / {}".format(
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), i + 1, total))
        try:
            df = get_local_stock_data(symbol, start_date)
            df_bt = prepare_dataframe(df)
            if df_bt is None or len(df_bt) < 120:
                continue
        except Exception:
            continue

        for sig in SIGNAL_KEYS:
            try:
                strat = run_single_backtest(df_bt, sig, cash=1000000, commission=0.0003)
                _merge_stats(bt_stats, strat, sig)
            except Exception:
                continue

        if (i + 1) % 100 == 0:
            print_signal_comparison(bt_stats, SIGNAL_KEYS)

    print_signal_comparison(bt_stats, SIGNAL_KEYS)

'''
====================================================================================================
  超跌反弹策略 — Backtrader 回测对比（全市场）
====================================================================================================
信号                  交易数      胜率%      平均收益%       总收益%        最大%        最小%       中位数%
----------------------------------------------------------------------------------------------------
XL3                   0         -           -           -           -           -           -
CTD6                  0         -           -           -           -           -           -
XL3+CTD6          33943     54.6%      +1.08%  +36644.19%    +122.61%     -41.66%      +0.76%
启动点                   0         -           -           -           -           -           -
见底                    0         -           -           -           -           -           -
====================================================================================================

----------------------------------------------------------------------------------------------------
  逐日收益明细
----------------------------------------------------------------------------------------------------
信号                      第1天          第2天          第3天          第4天          第5天         最大回撤
----------------------------------------------------------------------------------------------------
XL3+CTD6                  -            -            -            -            -
----------------------------------------------------------------------------------------------------
'''