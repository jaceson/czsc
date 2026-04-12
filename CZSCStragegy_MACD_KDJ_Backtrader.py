# coding: utf-8
"""
MACD + KDJ 组合策略 - Backtrader 回测版本

策略核心：
买入条件：
1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0
2. KDJ 超卖金叉：K < 30 且 K 上穿 D

卖出条件：
1. MACD 趋势向下：DIF < DEA（死叉状态）
2. KDJ 超买死叉：K > 80 且 K 下穿 D
满足任一条件即可卖出
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


class MACDKDJStrategy(bt.Strategy):
    """
    MACD + KDJ 组合策略
    
    参数:
        macd_fast: MACD 快线周期，默认 12
        macd_slow: MACD 慢线周期，默认 26
        macd_signal: MACD 信号线周期，默认 9
        kdj_period: KDJ 周期，默认 9
        kdj_oversold: KDJ 超卖阈值，默认 30
        kdj_overbought: KDJ 超买阈值，默认 80
        hold_days: 最小持有天数，默认 5
        stake: 每次买入股数，默认 1000
    """
    
    params = (
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
        ('kdj_period', 9),
        ('kdj_oversold', 30),
        ('kdj_overbought', 80),
        ('hold_days', 5),
        ('stake', 1000),
        ('printlog', True),
    )
    
    def __init__(self):
        # 计算 MACD 指标
        self.macd = bt.ind.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal
        )
        self.dif = self.macd.lines.macd
        self.dea = self.macd.lines.signal
        
        # 计算 KDJ 指标
        # KDJ = bt.ind.StochasticFull
        self.kdj = bt.ind.StochasticFull(
            self.data.high,
            self.data.low,
            self.data.close,
            period=self.params.kdj_period
        )
        self.k = self.kdj.lines.percK
        self.d = self.kdj.lines.percD
        
        # 状态变量
        self.order = None
        self.buy_price = 0
        self.buy_bar = 0
        self.in_position = False
        
        # 统计变量
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0
        self.total_loss = 0
        
        # 按持有天数统计收益
        self.hold_days_returns = {x: [] for x in range(1, self.params.hold_days + 1)}
    
    def next(self):
        """主逻辑：每个 bar 执行"""
        if self.order:
            return  # 等待订单完成
        
        current_bar = len(self)
        
        # 如果持有仓位，检查卖出条件
        if self.position:
            bars_held = current_bar - self.buy_bar
            
            # 最少持有 hold_days 天
            if bars_held >= self.params.hold_days:
                # 检查卖出条件
                if self._check_sell_signal():
                    self._sell_order()
        else:
            # 空仓时检查买入条件
            if self._check_buy_signal():
                self._buy_order()
    
    def _check_buy_signal(self):
        """
        检查买入信号
        买入条件：
        1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0
        2. KDJ 超卖金叉：K < 30 且 K 上穿 D
        """
        # 确保有足够的数据
        if len(self) < 2:
            return False
        
        try:
            # 1. MACD 趋势向上
            # DIF > DEA（金叉状态）或 DIF > 0
            trend_up = (self.dif[0] > self.dea[0]) or (self.dif[0] > 0)
            
            # 2. KDJ 超卖金叉
            # K < 30 且 K 上穿 D（当前 K>D，前一天 K<=D）
            kdj_oversold = (self.k[0] < self.params.kdj_oversold) and \
                          (self.k[0] > self.d[0]) and \
                          (self.k[-1] <= self.d[-1])
            
            # 双条件同时满足
            buy_signal = trend_up and kdj_oversold
            
            if buy_signal and self.params.printlog:
                print(f'【买入信号】MACD: DIF={self.dif[0]:.4f}, DEA={self.dea[0]:.4f} | '
                      f'KDJ: K={self.k[0]:.2f}, D={self.d[0]:.2f}')
            
            return buy_signal
            
        except (IndexError, TypeError):
            return False
    
    def _check_sell_signal(self):
        """
        检查卖出信号
        卖出条件：
        1. MACD 趋势向下：DIF < DEA（死叉状态）
        2. KDJ 超买死叉：K > 80 且 K 下穿 D
        满足任一条件即可卖出
        """
        # 确保有足够的数据
        if len(self) < 2:
            return False
        
        try:
            # 1. MACD 趋势向下：DIF < DEA（死叉状态）
            trend_down = self.dif[0] < self.dea[0]
            
            # 2. KDJ 超买死叉：K > 80 且 K 下穿 D（当前 K<D，前一天 K>=D）
            kdj_overbought = (self.k[0] > self.params.kdj_overbought) and \
                            (self.k[0] < self.d[0]) and \
                            (self.k[-1] >= self.d[-1])
            
            # 满足任一条件即可卖出
            sell_signal = trend_down or kdj_overbought
            
            if sell_signal and self.params.printlog:
                print(f'【卖出信号】MACD: DIF={self.dif[0]:.4f}, DEA={self.dea[0]:.4f} | '
                      f'KDJ: K={self.k[0]:.2f}, D={self.d[0]:.2f}')
            
            return sell_signal
            
        except (IndexError, TypeError):
            return False
    
    def _buy_order(self):
        """执行买入订单"""
        size = self.params.stake
        cash_available = self.broker.getcash()
        price = self.data.close[0]
        
        # 检查资金是否足够
        if cash_available < price * size * 1.003:
            if self.params.printlog:
                print(f'资金不足，跳过买入。可用：{cash_available:.2f}, 需要：{price*size*1.003:.2f}')
            return
        
        # 直接下单
        self.order = self.buy(size=size)
    
    def _sell_order(self):
        """执行卖出订单"""
        # 直接平仓
        self.order = self.close()
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            # 订单完成，处理交易
            if order.isbuy():
                # 买入成交
                self.buy_price = order.executed.price
                self.buy_bar = len(self)
                self.in_position = True
                self.trade_count += 1
                
                buy_date = self.data.datetime.date(0).strftime('%Y-%m-%d')
                
                if self.params.printlog:
                    print(f'【买入】日期：{buy_date}, '
                          f'价格：{order.executed.price:.2f}, '
                          f'MACD: DIF={self.dif[0]:.4f}, DEA={self.dea[0]:.4f}, '
                          f'KDJ: K={self.k[0]:.2f}, D={self.d[0]:.2f}')
            else:
                # 卖出成交
                sell_price = order.executed.price
                profit = sell_price - self.buy_price
                profit_pct = (profit / self.buy_price) * 100
                bars_held = len(self) - self.buy_bar
                
                # 更新统计
                if profit > 0:
                    self.win_count += 1
                    self.total_profit += profit
                    status = "✓ 盈利"
                else:
                    self.loss_count += 1
                    self.total_loss += abs(profit)
                    status = "✗ 亏损"
                
                # 记录到对应持有天数的收益列表
                actual_days = min(bars_held, self.params.hold_days)
                if actual_days in self.hold_days_returns:
                    self.hold_days_returns[actual_days].append(profit_pct)
                
                sell_date = self.data.datetime.date(0).strftime('%Y-%m-%d')
                buy_date = datetime.fromordinal(self.buy_bar).strftime('%Y-%m-%d')
                
                if self.params.printlog:
                    print(f'【卖出】{status} | '
                          f'买入：{buy_date}@{self.buy_price:.2f} → '
                          f'卖出：{sell_date}@{sell_price:.2f} | '
                          f'收益：{profit_pct:+.2f}% | '
                          f'持有：{bars_held}天')
                
                # 重置状态
                self.buy_price = 0
                self.buy_bar = 0
                self.in_position = False
        
        elif order.status in [order.Rejected, order.Margin, order.Canceled]:
            if self.params.printlog:
                print(f'订单失败：{order.getstatusname()}')
        
        self.order = None
    
    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            if self.params.printlog:
                print(f'交易完成 | 毛利润：{trade.pnl:.2f}, 收益率：{trade.pnlpercent:.2f}%\n')
    
    def stop(self):
        """策略结束时调用"""
        print('\n' + '='*80)
        print('MACD + KDJ 组合策略 - 回测总结')
        print('='*80)
        print(f'总交易次数：{self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'胜率：{win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'总盈利：{self.total_profit:.2f}')
            print(f'总亏损：{self.total_loss:.2f}')
            net_profit = self.total_profit - self.total_loss
            print(f'净收益：{net_profit:.2f}')
            print(f'平均每笔收益：{net_profit/self.trade_count:.2f}')
            
            # 按持有天数统计
            print(f'\n按持有天数统计收益:')
            for days in sorted(self.hold_days_returns.keys()):
                returns = self.hold_days_returns[days]
                if returns:
                    plus_num = sum(1 for r in returns if r > 0)
                    plus_val = sum(r for r in returns if r > 0)
                    minus_val = sum(r for r in returns if r <= 0)
                    plus_ratio = plus_num / len(returns) * 100 if returns else 0
                    
                    print(f'  第 {days} 天:')
                    print(f'    正收益次数：{plus_num}')
                    print(f'    正收益占比：{plus_ratio:.2f}%')
                    print(f'    总的正收益：{plus_val:.2f}')
                    print(f'    总的负收益：{minus_val:.2f}')
                    
                    avg_return = np.mean(returns)
                    print(f'    平均收益：{avg_return:.2f}%')
        print('='*80)


def run_backtest(symbol, df, start_date='2020-01-01', end_date='2025-12-31',
                 initial_cash=100000, stake=1000, printlog=True):
    """
    运行 Backtrader 回测
    
    参数:
        symbol: 股票代码
        df: 股票数据 DataFrame
        start_date: 开始日期
        end_date: 结束日期
        initial_cash: 初始资金
        stake: 每次买入股数
        printlog: 是否打印日志
    """
    print(f"\n{'='*80}")
    print(f"开始回测 {symbol}")
    print(f"{'='*80}")
    
    # 准备数据
    df_copy = df.copy()
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_filtered = df_copy[start_date:end_date]
    
    if len(df_filtered) < 50:
        print(f"{symbol} 数据不足，跳过")
        return None
    
    # 创建 Cerebro 引擎
    cerebro = bt.Cerebro()
    
    # 添加数据
    data = bt.feeds.PandasData(
        dataname=df_filtered,
        datetime=None,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1
    )
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(
        MACDKDJStrategy,
        stake=stake,
        hold_days=5,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        kdj_period=9,
        kdj_oversold=30,
        kdj_overbought=80,
        printlog=printlog
    )
    
    # 设置资金和手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0003)
    
    # 打印初始信息
    print(f'初始资金：{initial_cash:,.2f}')
    print(f'回测区间：{start_date} 至 {end_date}')
    print(f'数据条数：{len(df_filtered)}')
    
    # 运行回测
    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    
    # 计算收益
    total_return = (final_value - initial_value) / initial_value * 100
    
    print(f'\n最终资金：{final_value:,.2f}')
    print(f'总收益率：{total_return:.2f}%')
    
    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'strategy': results[0]
    }


def main():
    """主函数：批量回测所有股票"""
    print("="*80)
    print("MACD + KDJ 组合策略 - Backtrader 批量回测")
    print("="*80)
    print("策略说明：")
    print("买入条件：")
    print("  1. MACD 趋势向上：DIF > DEA（金叉状态）或 DIF > 0")
    print("  2. KDJ 超卖金叉：K < 30 且 K 上穿 D")
    print("卖出条件：")
    print("  1. MACD 趋势向下：DIF < DEA（死叉状态）")
    print("  2. KDJ 超买死叉：K > 80 且 K 下穿 D")
    print("="*80)
    
    # 获取所有股票代码
    all_symbols = get_daily_symbols()
    start_date = "2020-01-01"
    
    results = []
    symbol_count = 0
    
    for idx, symbol in enumerate(all_symbols):
        symbol_count += 1
        print(f"\n[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度：{symbol_count} / {len(all_symbols)}")
        print("-"*80)
        
        try:
            # 获取股票数据
            df = get_local_stock_data(symbol, start_date)
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue
            
            # 运行回测（关闭详细日志，只在最后显示统计）
            result = run_backtest(
                symbol=symbol,
                df=df,
                start_date=start_date,
                end_date='2025-12-31',
                initial_cash=100000,
                stake=1000,
                printlog=False  # 关闭单只股票的详细日志
            )
            
            if result:
                results.append(result)
            
            # 每 100 只股票打印一次汇总
            if symbol_count % 100 == 0:
                print(f"\n已处理 {symbol_count} 只股票")
                if results:
                    avg_return = np.mean([r['total_return'] for r in results])
                    print(f'平均收益率：{avg_return:.2f}%')
        
        except Exception as e:
            print(f"处理 {symbol} 时出错：{e}")
            continue
    
    # 最终汇总统计
    print("\n" + "="*80)
    print("全部回测完成 - 总体统计")
    print("="*80)
    
    if results:
        print(f"回测股票数量：{len(results)}")
        
        # 收益率统计
        all_returns = [r['total_return'] for r in results]
        print(f"\n收益率统计:")
        print(f"  平均值：{np.mean(all_returns):.2f}%")
        print(f"  中位数：{np.median(all_returns):.2f}%")
        print(f"  最大值：{np.max(all_returns):.2f}%")
        print(f"  最小值：{np.min(all_returns):.2f}%")
        print(f"  标准差：{np.std(all_returns):.2f}%")
        
        # 正收益占比
        positive_count = sum(1 for r in all_returns if r > 0)
        print(f"\n正收益股票占比：{positive_count/len(results)*100:.2f}%")
        
        # Top 10 收益股票
        print(f"\n收益最高的 10 只股票:")
        top_10 = sorted(results, key=lambda x: x['total_return'], reverse=True)[:10]
        for i, r in enumerate(top_10, 1):
            print(f"  {i}. {r['symbol']}: {r['total_return']:.2f}%")
        
        # Bottom 10 收益股票
        print(f"\n收益最低的 10 只股票:")
        bottom_10 = sorted(results, key=lambda x: x['total_return'])[:10]
        for i, r in enumerate(bottom_10, 1):
            print(f"  {i}. {r['symbol']}: {r['total_return']:.2f}%")
    
    print("\n" + "="*80)


if __name__ == '__main__':
    main()
