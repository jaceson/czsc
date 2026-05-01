# coding: utf-8
"""
通达信超跌反弹策略 - Backtrader回测实现

核心信号：
1. CTD6: 超跌反弹主信号（跌幅够深 + 筹码集中 + 有异动）
2. 启动点: 突破启动信号
3. 见底: 止跌见底信号
"""

import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import numpy as np
from datetime import datetime
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data


class UltimateOversoldRebound(bt.Indicator):
    """
    超跌反弹指标 - 通达信公式转换
    
    计算多个子指标：
    - RSI变种 (BCD)
    - 筹码分布指标 (Y3, Y7)
    - 乖离率 (Y6)
    - 超跌条件 (CTD6)
    - 启动点 (Launch Point)
    - 见底信号 (Bottom)
    """
    
    lines = (
        'bcd', 'bcd1',           # RSI平滑指标
        'y6',                    # 乖离率
        'y7',                    # 超跌条件1
        'ctd6',                  # 超跌反弹主信号
        'launch',                # 启动点信号
        'bottom',                # 见底信号
        'oversold_score',        # 超跌综合评分
    )
    
    params = (
        ('rsi_period', 14),
        ('ema_periods', (7, 3, 3)),  # BCD的三重EMA周期
        ('y6_threshold', -10),       # 乖离率阈值
        ('y6_extreme', -16),         # 极端乖离率
    )
    
    def __init__(self):
        # RSI计算 (通达信RS公式)
        # RS:=SMA(MAX(C-REF(C,1),0),14,1)/SMA(ABS(C-REF(C,1)),14,1)*100
        close = self.data.close
        delta = close - close(-1)
        
        # 使用LineBuffer直接计算
        up = btind.Max(delta, 0)
        down = btind.DivByZero(btind.Abs(delta), 1, zero=0)  # 修复: 使用btind.Abs
        
        # 注意: SMA(..., 14, 1) 在Backtrader中是SMA(..., period=14)
        sma_up = btind.SMA(up, period=self.p.rsi_period)
        sma_down = btind.SMA(down, period=self.p.rsi_period)
        
        # 避免除零
        rs = btind.DivByZero(sma_up, sma_down, zero=100) * 100
        
        # BCD: EMA(EMA(EMA(RS,7),3),3)
        e1 = btind.EMA(rs, period=self.p.ema_periods[0])
        e2 = btind.EMA(e1, period=self.p.ema_periods[1])
        self.lines.bcd = btind.EMA(e2, period=self.p.ema_periods[2])
        
        # BCD1: (BCD-REF(BCD,1))/REF(BCD,1)*15
        bcd_prev = self.lines.bcd(-1)
        self.lines.bcd1 = btind.DivByZero(
            self.lines.bcd - bcd_prev, bcd_prev, zero=0
        ) * 15
    
    def next(self):
        """每根K线计算复杂指标"""
        # 获取当前bar的数据
        high = self.data.high[0]
        low = self.data.low[0]
        close = self.data.close[0]
        volume = self.data.volume[0]
        
        # Y1: AMOUNT/V/100 (均价) - 如果没有amount则估算
        if hasattr(self.data, 'amount'):
            amount = self.data.amount[0]
        else:
            amount = close * volume
        y1 = amount / volume / 100 if volume > 0 else close
        
        # Y2: (3*H+L+O+2*C)/7 (加权平均价)
        y2 = (3 * high + low + self.data.open[0] + 2 * close) / 7
        
        # Y3: 100*(WINNER(1.1*C)-WINNER(0.9*C)) (筹码集中度)
        # 简化：使用过去N天的价格区间比例
        period = 20
        lookback = min(period, len(self.data))
        if lookback > 0:
            closes = [self.data.close[-i] for i in range(1, lookback + 1)]
            high_win = sum(1 for c in closes if c <= close * 1.1) / lookback
            low_win = sum(1 for c in closes if c <= close * 0.9) / lookback
        else:
            high_win = low_win = 0
        y3 = 100 * (high_win - low_win)
        
        # Y4: SUM(AMOUNT,13)/Y1/100 (13日资金均值)
        sum_amount = 0
        lookback = min(13, len(self.data))
        for i in range(1, lookback + 1):
            c_amt = getattr(self.data, 'amount', self.data.close[-i] * self.data.volume[-i])
            if hasattr(c_amt, '__getitem__'):
                c_amt = c_amt[0] if len(c_amt) > 0 else 0
            sum_amount += c_amt
        y4 = sum_amount / y1 / 100 if y1 > 0 else 0
        
        # Y5: DMA(Y2,V/Y4)
        if y4 > 0:
            y5_alpha = min(volume / y4 / 10000, 0.3)  # 调整系数并限制范围
            y5_alpha = max(y5_alpha, 0.01)
        else:
            y5_alpha = 0.1
        y5_prev = getattr(self, '_y5_prev', y2)
        y5 = y5_prev * (1 - y5_alpha) + y2 * y5_alpha
        self._y5_prev = y5
        
        # Y6: (C-Y5)/Y5*100 (乖离率)
        self.lines.y6[0] = (close - y5) / y5 * 100 if y5 != 0 else 0
        
        # Y7: (Y3 < 10) AND (Y6 <= -10)
        self.lines.y7[0] = 1.0 if (y3 < 10 and self.lines.y6[0] <= -10) else 0.0
        
        # CTD6超跌信号
        # 简化计算ctd1 (DMA(EMA(C,12), SUM(V,5)/3/CAPITAL))
        ema12 = self._calc_ema(close, 12)
        lookback = min(5, len(self.data))
        sum_vol_5 = sum([self.data.volume[-i] for i in range(1, lookback + 1)]) if lookback > 0 else volume * 5
        capital = 100000000  # 假设流通股本10亿，实际应该从外部获取
        alpha = sum_vol_5 / 3 / capital if capital > 0 else 0.1
        alpha = min(max(alpha, 0.01), 0.2)
        ctd1_prev = getattr(self, '_ctd1_prev', ema12)
        ctd1 = ctd1_prev * (1 - alpha) + ema12 * alpha
        self._ctd1_prev = ctd1
        
        cond1 = (close - ctd1) / ctd1 * 100 < -30
        
        # 条件2: REF(H,10)/C > 1.35 (10日前高点比当前价高35%以上)
        high_10 = self.data.high[-10] if len(self.data) > 10 else high
        cond2 = high_10 / close > 1.35 if close > 0 else False
        
        # 条件3: (COST(20)-C)/C > 0.15 (20日成本高于当前价15%)
        # 简化：用20日均线代替
        lookback = min(20, len(self.data))
        if lookback > 0:
            ma20 = sum([self.data.close[-i] for i in range(1, lookback + 1)]) / lookback
        else:
            ma20 = close
        cond3 = (ma20 - close) / close > 0.15 if close > 0 else False
        
        # 条件4: H > L * 1.051 (有异动)
        cond4 = high > low * 1.051
        
        # 条件5: 5日内有2次以上异动
        cond5 = cond4
        if len(self.data) > 5:
            cond5_count = 0
            for i in range(1, min(6, len(self.data))):
                if self.data.high[-i] > self.data.low[-i] * 1.051:
                    cond5_count += 1
            cond5 = cond5_count > 1
        
        # CTD6 = 条件1&条件2&条件3&条件4&条件5 或 条件2&条件3&条件5
        self.lines.ctd6[0] = 1.0 if ((cond1 or cond2) and cond3 and cond5) else 0.0
        
        # 超跌评分 (综合多个超跌因子)
        score = 0
        if self.lines.y6[0] <= -10:
            score += 20
        if self.lines.y6[0] <= -16:
            score += 20
        if self.lines.y7[0] == 1:
            score += 20
        if self.lines.ctd6[0] == 1:
            score += 30
        if cond1:
            score += 20
        if cond2:
            score += 20
        if cond3:
            score += 20
        if cond4:
            score += 10
        self.lines.oversold_score[0] = min(score, 100)
        
        # 启动点检测
        if len(self.data) > 1:
            close_ratio = close / self.data.close[-1] if self.data.close[-1] > 0 else 1
            var4aa = 1.0 if (close_ratio > 1.05 and high / close < 1.01) else 0.0
            self.lines.launch[0] = 1.0 if (var4aa > 0.5 and self.data.volume[0] > 0) else 0.0
        else:
            self.lines.launch[0] = 0.0
        
        # 见底信号
        if len(self.data) > 1:
            ls = 1.0 if (close / self.data.close[-1] > 1.048 and close == high) else 0.0
            if len(self.data) > 28:
                ls_filtered = 0
                for i in range(1, min(29, len(self.data))):
                    if self.data.close[-i] / self.data.close[-i-1] > 1.048 and \
                       self.data.close[-i] == self.data.high[-i]:
                        ls_filtered += 1
                self.lines.bottom[0] = 1.0 if ls_filtered > 0 else 0.0
            else:
                self.lines.bottom[0] = 0.0
        else:
            self.lines.bottom[0] = 0.0
    
    def _calc_ema(self, value, period):
        """指数移动平均"""
        alpha = 2 / (period + 1)
        attr_name = f'_ema_{period}'
        prev = getattr(self, attr_name, value)
        result = prev * (1 - alpha) + value * alpha
        setattr(self, attr_name, result)
        return result


class OversoldReboundStrategy(bt.Strategy):
    """
    超跌反弹策略
    
    买入信号：
    1. CTD6主信号：超跌反弹确认
    2. 启动点：突破启动
    3. 见底信号：止跌见底
    
    资金管理：
    - 根据超跌评分分批建仓
    - 设定止盈止损
    """
    
    params = (
        # 仓位管理
        ('max_position_pct', 0.95),   # 最大仓位比例
        ('single_position', 0.3),      # 单次开仓比例
        ('max_positions', 3),          # 最大持仓数量
        
        # 止盈止损
        ('take_profit_pct', 10),       # 止盈百分比
        ('stop_loss_pct', 5),          # 止损百分比
        ('max_hold_days', 30),         # 最大持有天数
        
        # 信号过滤
        ('min_score', 50),             # 最低超跌评分
        ('use_ctd6', True),            # 是否使用CTD6信号
        ('use_launch', True),          # 是否使用启动点
        ('use_bottom', True),          # 是否使用见底信号
        
        # 其他
        ('printlog', True),
        ('symbol', ''),
    )
    
    def __init__(self):
        # 添加超跌指标
        self.oversold = UltimateOversoldRebound(self.data)
        
        # 信号记录
        self.signals = []
        self.orders = []
        
        # 持仓记录
        self.open_positions = []  # 每个仓位的开仓信息
        self.trade_count = 0
        self.win_count = 0
        self.total_profit = 0
        
        # 每日检查标志
        self.bought_today = False
        
    def log(self, txt, dt=None):
        if self.params.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'[{dt}] {txt}')
    
    def next(self):
        if len(self) < 30:
            return
        
        # 重置当日买入标志
        self.bought_today = False
        
        current_price = self.data.close[0]
        current_date = self.datas[0].datetime.date(0)
        
        # 1. 检查持仓卖出条件
        self._check_exit_signals()
        
        # 2. 检查买入信号
        if len(self.open_positions) < self.params.max_positions:
            self._check_entry_signals()
    
    def _check_entry_signals(self):
        """检查买入信号"""
        current_price = self.data.close[0]
        score = self.oversold.oversold_score[0]
        
        # 信号强度
        signal_score = 0
        signal_type = []
        
        # CTD6主信号
        if self.params.use_ctd6 and self.oversold.ctd6[0] == 1:
            signal_score += 40
            signal_type.append('CTD6')
        
        # 启动点信号
        if self.params.use_launch and self.oversold.launch[0] == 1:
            signal_score += 30
            signal_type.append('LAUNCH')
        
        # 见底信号
        if self.params.use_bottom and self.oversold.bottom[0] == 1:
            signal_score += 25
            signal_type.append('BOTTOM')
        
        # 综合超跌评分
        if score >= self.params.min_score:
            signal_score += (score - self.params.min_score) / 2
        
        # Y6乖离率加成
        if self.oversold.y6[0] <= -10:
            signal_score += 15
        if self.oversold.y6[0] <= -16:
            signal_score += 15
        
        # 判断是否买入
        if signal_score >= 40 and not self.bought_today:
            # 计算仓位
            position_value = self.broker.getvalue() * self.params.single_position
            size = int(position_value / current_price / 100) * 100
            size = max(size, 100)
            
            # 检查资金
            cash = self.broker.getcash()
            if cash < current_price * size * 1.003:
                size = int(cash / current_price / 100) * 100
            
            if size >= 100:
                self.buy(size=size)
                
                # 记录开仓信息
                self.open_positions.append({
                    'entry_date': self.datas[0].datetime.date(0),
                    'entry_price': current_price,
                    'size': size,
                    'score': score,
                    'signals': signal_type.copy(),
                    'high_price': current_price,
                    'bars_held': 0
                })
                
                self.bought_today = True
                self.signals.append({
                    'date': self.datas[0].datetime.date(0),
                    'price': current_price,
                    'score': score,
                    'signals': str(signal_type)
                })
                
                self.log(f'【买入】价格={current_price:.2f}, 数量={size}, '
                        f'评分={score:.0f}, 信号={signal_type}')
    
    def _check_exit_signals(self):
        """检查卖出条件"""
        current_price = self.data.close[0]
        current_date = self.datas[0].datetime.date(0)
        
        positions_to_close = []
        
        for idx, pos in enumerate(self.open_positions):
            pos['bars_held'] += 1
            pos['high_price'] = max(pos['high_price'], current_price)
            
            # 计算收益率
            profit_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
            
            exit_reason = None
            
            # 止盈
            if profit_pct >= self.params.take_profit_pct:
                exit_reason = f'止盈({profit_pct:.1f}%)'
            
            # 止损
            elif profit_pct <= -self.params.stop_loss_pct:
                exit_reason = f'止损({profit_pct:.1f}%)'
            
            # 最大持有天数
            elif pos['bars_held'] >= self.params.max_hold_days:
                exit_reason = f'超期({pos["bars_held"]}天)'
            
            # 移动止盈（从最高点回撤）
            elif pos['high_price'] > pos['entry_price'] * 1.05:
                drawdown = (pos['high_price'] - current_price) / pos['high_price'] * 100
                if drawdown >= 5:
                    exit_reason = f'回撤止盈(回撤{drawdown:.1f}%)'
            
            if exit_reason:
                positions_to_close.append((idx, pos, profit_pct, exit_reason))
        
        # 执行卖出（从后往前删除）
        for idx, pos, profit_pct, reason in reversed(positions_to_close):
            self.close()
            
            # 统计
            self.trade_count += 1
            if profit_pct > 0:
                self.win_count += 1
            self.total_profit += profit_pct
            
            self.log(f'【卖出】价格={current_price:.2f}, '
                    f'收益={profit_pct:+.2f}%, 原因={reason}')
            
            # 从持仓列表中移除
            self.open_positions.pop(idx)
    
    def notify_order(self, order):
        """订单通知"""
        if order.status in [order.Completed, order.Canceled, order.Margin, order.Rejected]:
            self.orders.append(order)
    
    def stop(self):
        """策略结束统计"""
        if not self.params.printlog:
            return
        
        print('\n' + '='*70)
        print(f'超跌反弹策略回测统计 - {self.params.symbol}')
        print('='*70)
        
        print(f'\n交易统计:')
        print(f'  总交易次数: {self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'  胜率: {win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'  平均每笔收益: {self.total_profit/self.trade_count:.2f}%')
        
        print(f'\n信号统计:')
        print(f'  总信号数: {len(self.signals)}')
        if self.signals:
            ctd6_count = sum(1 for s in self.signals if 'CTD6' in s['signals'])
            launch_count = sum(1 for s in self.signals if 'LAUNCH' in s['signals'])
            bottom_count = sum(1 for s in self.signals if 'BOTTOM' in s['signals'])
            print(f'  CTD6信号: {ctd6_count}')
            print(f'  启动点信号: {launch_count}')
            print(f'  见底信号: {bottom_count}')
        
        print('='*70)


def run_backtest(data, symbol='', initial_cash=100000, commission=0.0003, printlog=True):
    """
    运行超跌反弹策略回测
    
    参数:
        data: DataFrame with columns: date, open, high, low, close, volume, amount
        symbol: 股票代码
        initial_cash: 初始资金
        commission: 手续费率
        printlog: 是否打印日志
    """
    cerebro = bt.Cerebro()
    
    # 添加策略
    cerebro.addstrategy(OversoldReboundStrategy, 
                        symbol=symbol, 
                        printlog=printlog)
    
    # 准备数据
    df = data.copy()
    if 'date' in df.columns:
        df['datetime'] = pd.to_datetime(df['date'])
        df.set_index('datetime', inplace=True)
    
    # 确保amount列存在
    if 'amount' not in df.columns:
        df['amount'] = df['close'] * df['volume']
    
    datafeed = bt.feeds.PandasData(
        dataname=df,
        datetime=None,
        open='open',
        high='high',
        low='low',
        close='close',
        volume='volume',
        openinterest=-1
    )
    
    cerebro.adddata(datafeed)
    
    # 设置资金和手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # 运行回测
    print(f'初始资金: {cerebro.broker.getvalue():,.2f}')
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100
    
    print(f'最终资金: {final_value:,.2f}')
    print(f'总收益率: {total_return:.2f}%')
    
    # 输出分析
    strat = results[0]
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    
    print(f'\n夏普比率: {sharpe.get("sharperatio", sharpe.get("sharperatio", "N/A"))}')
    print(f'最大回撤: {drawdown.get("max", {}).get("drawdown", "N/A")}%')
    
    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': strat.trade_count,
        'win_count': strat.win_count,
        'total_profit': strat.total_profit,
        'signals': strat.signals
    }


def test_with_sample_data():
    """使用示例数据进行测试"""
    symbol_count = 0
    all_symbols = get_daily_symbols()
    for idx, symbol in enumerate(all_symbols):
        symbol_count += 1
        # if symbol_count != 845:
        #     continue
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度: {symbol_count} / {len(all_symbols)}")
        
        try:
            df = get_local_stock_data(symbol, '2020-01-01', '2024-12-31')
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue
            result = run_backtest(df, symbol='000001.SS', printlog=False)
    
            if result:
                print(f"\n回测结果:")
                print(f"  总收益率: {result['total_return']:.2f}%")
                print(f"  交易次数: {result['trade_count']}")
                if result['trade_count'] > 0:
                    print(f"  胜率: {result['win_count']/result['trade_count']*100:.2f}%")
                    print(f"  信号数: {len(result['signals'])}")

        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            continue

if __name__ == '__main__':
    test_with_sample_data()