# coding: utf-8
"""
九转拐点 + 趋势中枢 组合策略 - Backtrader 回测版本

基于通达信公式实现，包含：
1. 九转序列模块（TD Sequential）- 低9买入/高9卖出
2. 趋势中枢模块（简化PEAK/TROUGH）- 高低点买卖信号
3. 黄金分割参考线（仅供分析参考）

策略买入条件（任一）：
1. 九转低9：连续9日 C < REF(C,4) 成立
2. 趋势中枢低点：局部低点确认

策略卖出条件（任一）：
1. 九转高9：连续9日 C > REF(C,4) 成立
2. 趋势中枢高点：局部高点确认
"""
import os
import sys
import pandas as pd
import numpy as np
import backtrader as bt
from datetime import datetime
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data


def REFXV(X, N, M=0):
    """通达信REFXV函数：引用X在N周期前的数值，M为偏移偏移（默认为0）
    等同于 REF(X, N+M) 或 REF(REF(X, N), M) 用于序列运算
    """
    return REF(X, N + M)


class SignalPandasData(bt.feeds.PandasData):
    """扩展 PandasData，支持九转序列和趋势中枢信号列"""
    params = (
        ('low9', 'low9'),
        ('high9', 'high9'),
        ('pivot_buy', 'pivot_buy'),
        ('pivot_sell', 'pivot_sell'),
        ('down_count', 'down_count'),
        ('up_count', 'up_count'),
        ('qj_buy', 'qj_buy'),
        ('qj_sell', 'qj_sell'),
    )
    lines = ('low9', 'high9', 'pivot_buy', 'pivot_sell',
             'down_count', 'up_count', 'qj_buy', 'qj_sell')


def calculate_nine_turn(c):
    """
    九转序列模块（TD Sequential）
    
    参数:
        c: close价格数组
    
    返回:
        low9, high9, down_count, up_count
    """
    n = len(c)
    down_cond = c < REF(c, 4)
    up_cond = c > REF(c, 4)

    down_count = BARSLASTCOUNT(down_cond)
    up_count = BARSLASTCOUNT(up_cond)

    count_down_9 = COUNT(down_cond, 9)
    count_up_9 = COUNT(up_cond, 9)

    low9 = np.zeros(n, dtype=int)
    high9 = np.zeros(n, dtype=int)

    for i in range(9, n):
        # 低位9 = COUNT(下跌条件,9)=9
        if count_down_9[i] == 9:
            ref_down_9 = not (down_cond[i - 9]) if i >= 9 else True
            # 九转低9 = (下跌连数>9) AND MOD(下跌连数,9)=0
            nine_turn_low9 = (down_count[i] > 9) and (down_count[i] % 9 == 0)
            if ref_down_9 or nine_turn_low9:
                low9[i] = 1

        # 高位9 = COUNT(上涨条件,9)=9
        if count_up_9[i] == 9:
            ref_up_9 = not (up_cond[i - 9]) if i >= 9 else True
            nine_turn_high9 = (up_count[i] > 9) and (up_count[i] % 9 == 0)
            if ref_up_9 or nine_turn_high9:
                high9[i] = 1

    return low9, high9, down_count.astype(int), up_count.astype(int)


def calculate_pivot(h, l, lookback=3):
    """
    趋势中枢模块（简化版）
    使用摆动高低点检测替代PEAK/TROUGH
    
    参数:
        h: high价格数组
        l: low价格数组
        lookback: 检测半径
    
    返回:
        pivot_buy, pivot_sell
    """
    n = len(h)
    pivot_buy = np.zeros(n, dtype=int)
    pivot_sell = np.zeros(n, dtype=int)

    for i in range(lookback, n - lookback):
        if l[i] == min(l[i - lookback:i + lookback + 1]):
            pivot_buy[i] = 1
        if h[i] == max(h[i - lookback:i + lookback + 1]):
            pivot_sell[i] = 1

    # 过滤相邻信号，避免连续重复
    for i in range(1, n):
        if pivot_buy[i] == 1 and pivot_buy[i - 1] == 1:
            pivot_buy[i] = 0
        if pivot_sell[i] == 1 and pivot_sell[i - 1] == 1:
            pivot_sell[i] = 0

    return pivot_buy, pivot_sell


def calculate_zig_qj(c):
    """
    简化ZIG趋势识别，模拟行情极点信号
    
    参数:
        c: close价格数组
    
    返回:
        qj_buy（底）、qj_sell（顶）
    """
    n = len(c)
    qj_buy = np.zeros(n, dtype=int)
    qj_sell = np.zeros(n, dtype=int)

    percent = 5.0
    trend = 0
    turn_idx = 0
    turn_price = c[0]

    for i in range(1, n):
        chg = (c[i] - turn_price) / turn_price * 100
        if trend >= 0:
            if chg > 0:
                if c[i] > turn_price:
                    turn_price = c[i]
                    turn_idx = i
                trend = 1
            elif chg <= -percent:
                if trend == 1:
                    qj_sell[turn_idx] = 1
                trend = -1
                turn_price = c[i]
                turn_idx = i
        if trend <= 0:
            if chg < 0:
                if c[i] < turn_price:
                    turn_price = c[i]
                    turn_idx = i
                trend = -1
            elif chg >= percent:
                if trend == -1:
                    qj_buy[turn_idx] = 1
                trend = 1
                turn_price = c[i]
                turn_idx = i

    return qj_buy, qj_sell


def calculate_tdx_signals(df):
    """
    计算通达信公式中的完整交易信号
    
    参数:
        df: OHLCV DataFrame（需包含 open, high, low, close, volume）
    
    返回:
        添加信号列的 DataFrame
    """
    data = df.copy()
    c = data['close'].values.astype(float)
    h = data['high'].values.astype(float)
    l = data['low'].values.astype(float)

    # 九转序列信号
    low9, high9, down_count, up_count = calculate_nine_turn(c)

    # 趋势中枢信号（简化摆动高低点）
    pivot_buy, pivot_sell = calculate_pivot(h, l, lookback=3)

    # ZIG趋势识别（行情极点模拟）
    qj_buy, qj_sell = calculate_zig_qj(c)

    data['low9'] = low9
    data['high9'] = high9
    data['down_count'] = down_count
    data['up_count'] = up_count
    data['pivot_buy'] = pivot_buy
    data['pivot_sell'] = pivot_sell
    data['qj_buy'] = qj_buy
    data['qj_sell'] = qj_sell

    return data


class NineTurnPivotStrategy(bt.Strategy):
    """
    九转拐点 + 趋势中枢 组合策略
    
    参数:
        use_nine_turn: 启用九转序列信号（默认True）
        use_pivot: 启用趋势中枢信号（默认True）
        use_zig: 启用ZIG趋势信号（默认False）
        min_hold_days: 最小持有天数（默认3）
        stake: 每次买入股数（默认1000）
        printlog: 是否打印日志（默认True）
    """
    params = (
        ('use_nine_turn', True),
        ('use_pivot', True),
        ('use_zig', False),
        ('min_hold_days', 3),
        ('stake', 1000),
        ('printlog', True),
    )

    def __init__(self):
        self.order = None
        self.buy_price = 0
        self.buy_bar = 0

        # 统计变量
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_pnl = 0
        self.total_profit = 0
        self.total_loss = 0

    def _check_buy(self):
        """检查买入信号"""
        if self.params.use_nine_turn and self.data.low9[0] > 0:
            return True
        if self.params.use_pivot and self.data.pivot_buy[0] > 0:
            return True
        if self.params.use_zig and self.data.qj_buy[0] > 0:
            return True
        return False

    def _check_sell(self):
        """检查卖出信号"""
        if len(self) - self.buy_bar < self.params.min_hold_days:
            return False
        if self.params.use_nine_turn and self.data.high9[0] > 0:
            return True
        if self.params.use_pivot and self.data.pivot_sell[0] > 0:
            return True
        if self.params.use_zig and self.data.qj_sell[0] > 0:
            return True
        return False

    def next(self):
        if self.order:
            return

        if self.position:
            if self._check_sell():
                self.order = self.close()
        else:
            if self._check_buy():
                cash = self.broker.getcash()
                price = self.data.close[0]
                size = min(self.params.stake, max(0, int(cash / price / 100) * 100))
                if size >= 100:
                    self.order = self.buy(size=size)

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                self.buy_price = order.executed.price
                self.buy_bar = len(self)
                self.trade_count += 1
                if self.params.printlog:
                    sig = []
                    if self.data.low9[0] > 0:
                        sig.append('低9')
                    if self.data.pivot_buy[0] > 0:
                        sig.append('中枢')
                    if self.data.qj_buy[0] > 0:
                        sig.append('ZIG')
                    print(f'【买入】{self.data.datetime.date(0)} '
                          f'@{order.executed.price:.2f} '
                          f'信号:{"+".join(sig)}')
            else:
                pnl = order.executed.price - self.buy_price
                pnl_pct = (pnl / self.buy_price) * 100
                if pnl > 0:
                    self.win_count += 1
                    self.total_profit += pnl
                else:
                    self.loss_count += 1
                    self.total_loss += abs(pnl)
                self.total_pnl += pnl
                if self.params.printlog:
                    sig = []
                    if self.data.high9[0] > 0:
                        sig.append('高9')
                    if self.data.pivot_sell[0] > 0:
                        sig.append('中枢')
                    if self.data.qj_sell[0] > 0:
                        sig.append('ZIG')
                    print(f'【卖出】{self.data.datetime.date(0)} '
                          f'@{order.executed.price:.2f} '
                          f'收益:{pnl_pct:+.2f}% '
                          f'信号:{"+".join(sig)}')
            self.order = None

    def stop(self):
        print('\n' + '=' * 80)
        print('九转拐点+趋势中枢策略 - 回测总结')
        print('=' * 80)
        print(f'总交易次数：{self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'胜率：{win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'总盈利：{self.total_profit:.2f}')
            print(f'总亏损：{self.total_loss:.2f}')
            print(f'净收益：{self.total_pnl:.2f}')
            print(f'平均每笔收益：{self.total_pnl / self.trade_count:.2f}')
        print('=' * 80)


def run_backtest(symbol, df, start_date='2020-01-01', end_date='2025-12-31',
                 initial_cash=100000, stake=1000, printlog=True):
    """
    运行 Backtrader 回测

    参数:
        symbol: 股票代码
        df: 股票数据
        start_date: 开始日期
        end_date: 结束日期
        initial_cash: 初始资金
        stake: 每次买入股数
        printlog: 是否打印日志
    """
    print(f"\n{'=' * 80}")
    print(f"开始回测 {symbol}")
    print(f"{'=' * 80}")

    # 计算信号
    print("计算九转序列和趋势中枢信号...")
    df_signals = calculate_tdx_signals(df)

    # 准备数据
    df_copy = df_signals.copy()
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_filtered = df_copy[start_date:end_date]

    if len(df_filtered) < 50:
        print(f"{symbol} 数据不足({len(df_filtered)}条)，跳过")
        return None

    cerebro = bt.Cerebro()

    data = SignalPandasData(
        dataname=df_filtered,
        datetime=None,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1,
        low9='low9',
        high9='high9',
        pivot_buy='pivot_buy',
        pivot_sell='pivot_sell',
        down_count='down_count',
        up_count='up_count',
        qj_buy='qj_buy',
        qj_sell='qj_sell',
    )
    cerebro.adddata(data)

    cerebro.addstrategy(
        NineTurnPivotStrategy,
        use_nine_turn=True,
        use_pivot=True,
        use_zig=False,
        min_hold_days=3,
        stake=stake,
        printlog=printlog,
    )

    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0003)

    print(f'初始资金：{initial_cash:,.2f}')
    print(f'回测区间：{start_date} 至 {end_date}')
    print(f'数据条数：{len(df_filtered)}')

    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()

    total_return = (final_value - initial_value) / initial_value * 100

    print(f'\n最终资金：{final_value:,.2f}')
    print(f'总收益率：{total_return:.2f}%')

    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'strategy': results[0],
    }


def main():
    """主函数：批量回测"""
    print("=" * 80)
    print("九转拐点 + 趋势中枢 组合策略 - Backtrader 批量回测")
    print("=" * 80)
    print("策略说明：")
    print("  买入信号：九转低9 / 趋势中枢低点 / ZIG底")
    print("  卖出信号：九转高9 / 趋势中枢高点 / ZIG顶")
    print("=" * 80)

    all_symbols = get_daily_symbols()
    start_date = "2020-01-01"

    results = []
    symbol_count = 0

    for idx, symbol in enumerate(all_symbols):
        symbol_count += 1
        print(f"\n[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度：{symbol_count} / {len(all_symbols)}")
        print("-" * 80)

        try:
            df = get_local_stock_data(symbol, start_date)
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue

            result = run_backtest(
                symbol=symbol,
                df=df,
                start_date=start_date,
                end_date='2025-12-31',
                initial_cash=100000,
                stake=1000,
                printlog=False,
            )

            if result:
                results.append(result)

            if symbol_count % 100 == 0:
                print(f"\n已处理 {symbol_count} 只股票")
                if results:
                    avg_return = np.mean([r['total_return'] for r in results])
                    print(f'平均收益率：{avg_return:.2f}%')

        except Exception as e:
            print(f"处理 {symbol} 时出错：{e}")
            continue

    print("\n" + "=" * 80)
    print("全部回测完成 - 总体统计")
    print("=" * 80)

    if results:
        print(f"回测股票数量：{len(results)}")

        all_returns = [r['total_return'] for r in results]
        print(f"\n收益率统计:")
        print(f"  平均值：{np.mean(all_returns):.2f}%")
        print(f"  中位数：{np.median(all_returns):.2f}%")
        print(f"  最大值：{np.max(all_returns):.2f}%")
        print(f"  最小值：{np.min(all_returns):.2f}%")
        print(f"  标准差：{np.std(all_returns):.2f}%")

        positive_count = sum(1 for r in all_returns if r > 0)
        print(f"\n正收益股票占比：{positive_count / len(results) * 100:.2f}%")

        print(f"\n收益最高的 10 只股票:")
        top_10 = sorted(results, key=lambda x: x['total_return'], reverse=True)[:10]
        for i, r in enumerate(top_10, 1):
            print(f"  {i}. {r['symbol']}: {r['total_return']:.2f}%")

        print(f"\n收益最低的 10 只股票:")
        bottom_10 = sorted(results, key=lambda x: x['total_return'])[:10]
        for i, r in enumerate(bottom_10, 1):
            print(f"  {i}. {r['symbol']}: {r['total_return']:.2f}%")

    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
