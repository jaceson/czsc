# coding: utf-8
"""
黄金分割线策略 - Backtrader 回测版本（支持多次补仓+止盈卖出）
基于 CZSCStragegy_Goldenline.py 重新实现

策略核心：
1. 使用缠论笔划分识别上涨线段
2. 计算黄金分割点位（0.5和0.618）
3. 在黄金分割点附近买入
4. 低于黄金分割线出现底分型时补仓（最多补仓2次）
5. 卖出条件：
   - 止损：亏损达到8%立即止损
   - 止盈：涨幅达到3%立即止盈
   - 形成上涨一笔时卖出
   - 超过最大持有天数卖出
"""
import os
import sys
import pandas as pd
import numpy as np
import backtrader as bt
from datetime import datetime
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data


class GoldenLineStrategy(bt.Strategy):
    """
    黄金分割线策略 - 支持多次补仓+止盈卖出
    
    参数:
        threshold: 涨幅阈值，默认 1.7（上涨需超过 70%）
        klines: 最小上涨 K 线数，默认 10
        min_angle: 最小角度，默认 15
        max_hold_days: 最大持有天数，默认 60（防止无限持有）
        stake: 每次买入最大金额，默认 40000
        take_profit_pct: 止盈百分比，默认 3（%）
        stop_loss_pct: 止损百分比，默认 8（%）
        max_add_count: 最大补仓次数，默认 2
        avg_op: 是否价格优先，默认 False
    """
    
    params = (
        ('symbol', ''),
        ('threshold', 1.7),
        ('klines', 10),
        ('min_angle', 15),
        ('max_hold_days', 60),
        ('stake', 40000),
        ('take_profit_pct', 3.0),   # 止盈百分比
        ('stop_loss_pct', 8.0),     # 止损百分比（新增）
        ('max_add_count', 2),       # 最大补仓次数（新增，默认2次）
        ('avg_op', False),
        ('printlog', True),
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
    )
    
    def __init__(self):
        # 状态变量
        self.order = None
        self.buy_price = 0
        self.buy_bar = 0
        self.buy_date = None
        self.in_position = False
        
        # 补仓相关变量
        self.first_buy_price = 0
        self.first_buy_bar = 0
        self.add_count = 0           # 当前补仓次数
        
        # 止盈/止损相关
        self.max_price_since_buy = 0   # 买入后的最高价
        self.has_checked_exit = False   # 是否已触发退出检查
        
        # 缠论相关变量
        self.bars = []
        self.bi_list = []
        self.zs_list = []
        self.current_bar_index = 0
        
        # 黄金分割点相关
        self.golden_min_val = None
        self.valid_setup = False
        self.start_fx_a = None
        self.end_fx_b = None
        
        # 卖出相关
        self.bought_bi_count = None
        self.waiting_for_up_bi = False
        
        # 底分型检测
        self.lowest_price = None
        
        # MACD 指标
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.params.macd_fast,
            period_me2=self.params.macd_slow,
            period_signal=self.params.macd_signal,
            plot=True
        )
        
        # 统计变量
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0
        self.total_loss = 0
        
        # 收益统计
        self.all_returns = []
        self.hold_days_returns = {x: [] for x in range(1, self.params.max_hold_days + 1)}
        self.plus_list = []
        self.minus_list = []
        
        # 记录所有买入点
        self.buy_points = []
        
        # 补仓统计
        self.add_trade_count = 0
        self.add_win_count = 0
        
        # 交易记录明细
        self.trade_records = []
        self.current_trade = None
        self.last_sell_reason = None
        
        # MACD 绿柱跟踪
        self.last_macd_hist = None
    
    def next(self):
        """主逻辑：每个 bar 执行"""
        if self.order:
            return
        
        self.current_bar_index = len(self)
        
        # 收集 K 线数据
        bar = {
            'date': self.data.datetime.date(0),
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': self.data.close[0],
            'volume': self.data.volume[0],
            'index': self.current_bar_index
        }
        self.bars.append(bar)
        
        # 限制 bars 内存使用
        if len(self.bars) > 500:
            self.bars = self.bars[-500:]
        
        # 更新缠论笔划分
        if len(self.bars) >= 5:
            self._update_czsc()
        
        # 如果持有仓位，检查卖出条件
        if self.position:
            bars_held = self.current_bar_index - self.buy_bar
            current_price = self.data.close[0]
            current_low = self.data.low[0]
            
            # 更新买入后的最高价（用于止盈判断）
            if current_price > self.max_price_since_buy:
                self.max_price_since_buy = current_price
            
            # 计算从买入价到当前价的涨幅
            profit_from_buy = (current_price - self.buy_price) / self.buy_price * 100
            
            # 卖出条件1：止损（亏损达到8%）
            if profit_from_buy <= -self.params.stop_loss_pct and self.add_count == self.params.max_add_count:
                self._sell_order(reason=f"止损 {profit_from_buy:.2f}%")
                return
            
            # 卖出条件2：止盈（涨幅达到3%立即卖出）
            if profit_from_buy >= self.params.take_profit_pct and not self.has_checked_exit:
                self._sell_order(reason=f"止盈 {profit_from_buy:.2f}%")
                self.has_checked_exit = True
                return
            
            # 卖出条件3：形成上涨一笔
            if self.waiting_for_up_bi and self._check_up_bi_formed():
                self._sell_order(reason="上涨一笔形成")
                return
            
            # 卖出条件4：超过最大持有天数
            elif bars_held >= self.params.max_hold_days:
                self._sell_order(reason=f"达到最大持有天数{self.params.max_hold_days}")
                return
            
            # 持仓中，检查补仓条件（未超过最大补仓次数时才检查）
            if self.valid_setup and self.first_buy_price > 0 and self.add_count < self.params.max_add_count:
                self._check_add_position()
        else:
            # 重置状态
            self._reset_position_state()
            
            # 检查是否有有效的买入信号
            if self._check_buy_signal() and self._check_macd_green_bar_decreasing():
                self._buy_order()
    
    def _reset_position_state(self):
        """重置持仓状态"""
        self.first_buy_price = 0
        self.first_buy_bar = 0
        self.add_count = 0
        self.lowest_price = None
        self.waiting_for_up_bi = False
        self.bought_bi_count = None
        self.valid_setup = False
        self.golden_min_val = None
        self.start_fx_a = None
        self.end_fx_b = None
        self.max_price_since_buy = 0
        self.has_checked_exit = False
        self.current_trade = None
        self.last_sell_reason = None
    
    def _update_czsc(self):
        """更新缠论笔划分"""
        try:
            df = pd.DataFrame(self.bars)
            df['date'] = pd.to_datetime(df['date'])
            
            bars = [RawBar(symbol=self.params.symbol, id=i, freq=Freq.D, open=row['open'], dt=row['date'],
                    close=row['close'], high=row['high'], low=row['low'], vol=row['volume'], amount=1)
                for i, row in df.iterrows()]
            c = CZSC(bars, get_signals=None)
            if c and c.bi_list:
                self.bi_list = c.bi_list
                self.zs_list = get_zs_seq(self.bi_list)
        except Exception as e:
            if self.params.printlog:
                print(f"CZSC analysis error: {e}")
    
    def _get_last_up_bi(self):
        """获取最后一笔上涨笔"""
        if len(self.bi_list) < 3:
            return None
        last_bi = self.bi_list[-1]
        if last_bi.fx_a.fx > last_bi.fx_b.fx:
            last_bi = self.bi_list[-2]
        return last_bi
    
    def _check_up_bi_formed(self):
        """检查是否形成了新的上涨一笔"""
        if self.bought_bi_count is None:
            return False
        
        if len(self.bi_list) <= self.bought_bi_count:
            return False
        
        for i in range(self.bought_bi_count, len(self.bi_list)):
            bi = self.bi_list[i]
            if bi.fx_a.fx < bi.fx_b.fx:
                if self.params.printlog:
                    print(f'检测到上涨一笔形成: {bi.fx_a.dt} -> {bi.fx_b.dt}, '
                          f'价格: {bi.fx_a.fx:.2f} -> {bi.fx_b.fx:.2f}')

                # 如果macd刚变红，需要持续三个红柱
                current_hist = self.macd.macd[0] - self.macd.signal[0]
                prev_hist1 = self.macd.macd[-1] - self.macd.signal[-1]
                prev_hist2 = self.macd.macd[-2] - self.macd.signal[-2]
                if current_hist > 0:
                    if prev_hist1 > 0 and prev_hist2 > 0:
                        return True
                else:
                    return True
        return False

    def _check_macd_green_bar_decreasing(self):
        """检查 MACD 条件：最后一个绿柱长度小于前一个绿柱"""
        if len(self.macd.macd) < 2:
            return False
        
        current_hist = self.macd.macd[0] - self.macd.signal[0]
        prev_hist = self.macd.macd[-1] - self.macd.signal[-1]
        
        if current_hist < 0 and prev_hist < 0:
            if current_hist > prev_hist:
                if self.params.printlog:
                    print(f'MACD绿柱缩短: {prev_hist:.4f} -> {current_hist:.4f}')
                return True
        
        return False

    def _check_buy_signal(self):
        """检查黄金分割买入信号"""
        last_up_bi = self._get_last_up_bi()
        if not last_up_bi:
            return False

        up_start_fx = last_up_bi.fx_a
        up_end_fx = last_up_bi.fx_b
        pre_bi = last_up_bi
        for i in range(self.bi_list.index(last_up_bi) - 1, -1, -1):
            current_bi = self.bi_list[i]
            if current_bi.fx_a.fx > current_bi.fx_b.fx:
                if current_bi.fx_a.fx > up_end_fx.fx:
                    return False
                continue
            
            if current_bi.fx_b.fx > up_end_fx.fx:
                return False
            
            if current_bi.fx_a.fx < pre_bi.fx_a.fx and current_bi.fx_b.fx < pre_bi.fx_b.fx:
                pre_bi = current_bi
                up_start_fx = current_bi.fx_a
            else:
                break
        
        pre_idx = self.bi_list.index(pre_bi)
        pre_down_bi = self.bi_list[pre_idx - 1] if pre_idx > 0 else None 

        if len(self.zs_list) > 0:
            last_zs = self.zs_list[-1]
            if last_zs.is_valid:
                if self.params.printlog:
                    print('zs:[{},{}], bi:[{},{}]'.format(last_zs.sdt, last_zs.edt, pre_bi.fx_a.dt, pre_bi.fx_b.dt))
                in_zs = (last_zs.sdt <= pre_bi.fx_a.dt and pre_bi.fx_a.dt <= last_zs.edt) or \
                        (pre_down_bi and last_zs.sdt <= pre_down_bi.fx_a.dt and pre_down_bi.fx_a.dt <= last_zs.edt)
                
                if in_zs:
                    for z_bi in last_zs.bis:
                        for fx in [z_bi.fx_a, z_bi.fx_b]:
                            if fx.fx < up_start_fx.fx and fx.dt < up_start_fx.dt:
                                up_start_fx = fx
                                if self.params.printlog:
                                    print('{}: 使用中枢最低点{}'.format(
                                        self.params.symbol, up_start_fx.dt))
        
        return self._check_golden_setup(up_start_fx, up_end_fx)

    def _check_golden_setup(self, fx_a, fx_b):
        """检查黄金分割买入条件"""
        fx_a_date = fx_a.dt.strftime("%Y-%m-%d")
        fx_b_date = fx_b.dt.strftime("%Y-%m-%d")
        if fx_a.fx * self.params.threshold > fx_b.fx:
            if self.params.printlog:
                print('{}上涨一笔[{}, {}]涨幅{}'.format(
                    self.params.symbol, fx_a_date, fx_b_date, fx_b.fx/fx_a.fx))
            return False
        
        df = pd.DataFrame(self.bars)
        df['date'] = pd.to_datetime(df['date'])
        
        up_kline_num = days_trade_delta(df, fx_a_date, fx_b_date)
        if up_kline_num < self.params.klines:
            if self.params.printlog:
                print('{}上涨一笔[{}, {}]K线不足！！'.format(
                    self.params.symbol, fx_a_date, fx_b_date))
            return False
        
        angle = bi_angle(df, fx_a, fx_b)
        if angle < self.params.min_angle:
            if self.params.printlog:
                print('{}上涨一笔[{}, {}]角度{}'.format(
                    self.params.symbol, fx_a_date, fx_b_date, angle))
            return False
        
        self.golden_min_val = gold_val_low(fx_a.fx, fx_b.fx)
        
        self.start_fx_a = fx_a
        self.end_fx_b = fx_b
        
        close_price = df['close'].iloc[-1]
        if close_price <= self.golden_min_val:
            self.valid_setup = True
            if self.params.printlog:
                print('{}上涨一笔[{}, {}]到黄金点位{}'.format(
                    self.params.symbol, fx_a_date, fx_b_date, angle))
            return True
        
        self.valid_setup = False
        return False
    
    def _check_add_position(self):
        """
        检查补仓条件：
        1. 未超过最大补仓次数
        2. 价格在黄金分割位之下
        3. 形成底分型
        """
        # 条件0：检查是否超过最大补仓次数
        if self.add_count >= self.params.max_add_count:
            return False
        
        current_price = self.data.close[0]
        current_low = self.data.low[0]
        
        # 条件1：价格在黄金分割位之下
        if current_price > self.golden_min_val:
            return False
        
        # 更新最低价
        if self.lowest_price is None or current_low < self.lowest_price:
            self.lowest_price = current_low
        
        # 条件2：检测底分型
        if self._check_bottom_fractal():
            add_size = self._calculate_add_size()
            
            if add_size > 0:
                self.add_count += 1
                if self.params.printlog:
                    print(f'【补仓信号 #{self.add_count}/{self.params.max_add_count}】日期: {self.data.datetime.date(0)}, '
                          f'价格: {current_price:.2f}, 首次买入价: {self.first_buy_price:.2f}')
                
                self._add_order()
                return True
        
        return False
    
    def _check_bottom_fractal(self):
        """检测底分型"""
        if len(self.bars) < 3:
            return False
        
        bar_2 = self.bars[-3]
        bar_1 = self.bars[-2]
        bar_0 = self.bars[-1]
        
        is_bottom = (bar_1['low'] <= bar_2['low'] and 
                    bar_1['low'] <= bar_0['low'] and
                    bar_1['high'] <= bar_2['high'] and 
                    bar_1['high'] <= bar_0['high'])
        
        if is_bottom and self.params.printlog:
            print(f'检测到底分型: 日期={bar_1["date"]}, 低点={bar_1["low"]:.2f}')
        
        return is_bottom
    
    def _calculate_size_by_amount(self, amount, price):
        """根据金额计算可买数量（按100股取整）"""
        if amount <= 0 or price <= 0:
            return 0
        size = int(amount / price / 100) * 100
        if size == 0 and amount >= price:
            size = 100
        return size
    
    def _calculate_initial_size(self):
        """计算首次买入数量"""
        current_price = self.data.close[0]
        return self._calculate_size_by_amount(self.params.stake, current_price)
    
    def _calculate_add_size(self):
        """计算补仓数量（每次补仓固定金额）"""
        cash_available = self.broker.getcash()
        current_price = self.data.close[0]
        
        target_amount = self.params.stake
        
        if cash_available < target_amount * 1.003:
            if self.params.printlog:
                print(f'补仓资金不足: 可用 {cash_available:.2f}')
            target_amount = cash_available * 0.8
        
        return self._calculate_size_by_amount(target_amount, current_price)
    
    def _buy_order(self):
        """执行第一次买入"""
        size = self._calculate_initial_size()
        
        if size == 0:
            return
        
        cash_available = self.broker.getcash()
        price = self.data.close[0]
        
        if cash_available < price * size * 1.003:
            if self.params.printlog:
                print(f'资金不足: 可用 {cash_available:.2f}')
            return
        
        self.buy_points.append({
            'date': self.data.datetime.date(0),
            'price': price,
            'golden_val': self.golden_min_val,
            'type': 'first'
        })
        
        self.order = self.buy(size=size)
        
        if self.params.printlog:
            print(f'【买入信号】日期: {self.data.datetime.date(0)}, '
                  f'价格: {price:.2f}, 数量: {size}, 上涨一段：[{self.start_fx_a.dt},{self.end_fx_b.dt}]')
            
    def _add_order(self):
        """执行补仓"""
        size = self._calculate_add_size()
        
        if size == 0:
            return
        
        cash_available = self.broker.getcash()
        price = self.data.close[0]
        
        if cash_available < price * size * 1.003:
            if self.params.printlog:
                print(f'补仓资金不足: 可用 {cash_available:.2f}')
            return
        
        self.buy_points.append({
            'date': self.data.datetime.date(0),
            'price': price,
            'golden_val': self.golden_min_val,
            'type': f'add_{self.add_count}'
        })
        
        self.order = self.buy(size=size)
        
        if self.params.printlog:
            print(f'【补仓执行 #{self.add_count}/{self.params.max_add_count}】日期: {self.data.datetime.date(0)}, '
                  f'价格: {price:.2f}, 数量: {size}')
    
    def _set_last_sell_reason(self, reason):
        """记录卖出原因"""
        self.last_sell_reason = reason
    
    def _sell_order(self, reason=""):
        """执行卖出"""
        if self.position:
            self._set_last_sell_reason(reason)
            if self.params.printlog:
                print(f'【卖出信号】日期: {self.data.datetime.date(0)}, '
                      f'价格: {self.data.close[0]:.2f}, 持仓: {self.position.size}, 原因: {reason}')
            self.order = self.close()
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                if self.first_buy_price == 0:
                    # 第一次买入
                    self.first_buy_price = order.executed.price
                    self.first_buy_bar = self.current_bar_index
                    self.buy_price = order.executed.price
                    self.buy_bar = self.current_bar_index
                    self.buy_date = self.data.datetime.date(0)
                    self.in_position = True
                    self.trade_count += 1
                    self.bought_bi_count = len(self.bi_list)
                    self.waiting_for_up_bi = True
                    self.max_price_since_buy = order.executed.price
                    self.has_checked_exit = False
                
                    if self.params.printlog:
                        print(f'【买入成交】日期: {self.buy_date}, '
                              f'价格: {self.buy_price:.2f}, 数量: {order.executed.size}')
                    
                    self.current_trade = {
                        'buy_date': self.buy_date,
                        'buy_price': self.buy_price,
                        'buy_size': order.executed.size,
                        'add_count': 0,
                        'add_details': [],
                        'sell_date': None,
                        'sell_price': None,
                        'profit_pct': None,
                        'profit_amount': None,
                        'hold_days': None,
                        'sell_reason': None
                    }
                else:
                    # 补仓成交
                    self.add_trade_count += 1
                    self.buy_price = self.position.price
                
                    if self.params.printlog:
                        print(f'【补仓成交 #{self.add_count}/{self.params.max_add_count}】日期: {self.data.datetime.date(0)}, '
                              f'价格: {order.executed.price:.2f}, 平均成本: {self.buy_price:.2f}')
                    
                    if self.current_trade is not None:
                        self.current_trade['add_count'] = self.add_count
                        self.current_trade['add_details'].append({
                            'date': self.data.datetime.date(0),
                            'price': order.executed.price,
                            'size': order.executed.size
                        })
            else:
                # 卖出成交
                sell_price = order.executed.price
                position_size = abs(order.size)
                sell_date = self.data.datetime.date(0)
                
                profit_amount = (sell_price - self.buy_price) * position_size
                profit_pct = (sell_price - self.buy_price) / self.buy_price * 100 if self.buy_price > 0 else 0
                bars_held = self.current_bar_index - self.buy_bar
                
                if profit_amount > 0:
                    self.win_count += 1
                    self.total_profit += profit_amount
                    self.plus_list.append(profit_pct)
                else:
                    self.loss_count += 1
                    self.total_loss += abs(profit_amount)
                    self.minus_list.append(profit_pct)
                
                # 统计补仓交易的胜率
                if self.add_count > 0:
                    if profit_amount > 0:
                        self.add_win_count += 1

                actual_days = min(bars_held, self.params.max_hold_days)
                if actual_days in self.hold_days_returns:
                    self.hold_days_returns[actual_days].append(profit_pct)

                self.all_returns.append(profit_pct)

                if self.params.printlog:
                    print(f'【卖出成交】卖出价：{sell_price:+.2f}, 买入价：{self.buy_price:+.2f}, 持仓量：{position_size:+.2f}, 收益: {profit_pct:+.2f}% ({profit_amount:+.2f}元), 持有: {bars_held}天')
                
                if self.current_trade is not None:
                    self.current_trade['sell_date'] = sell_date
                    self.current_trade['sell_price'] = sell_price
                    self.current_trade['profit_pct'] = profit_pct
                    self.current_trade['profit_amount'] = profit_amount
                    self.current_trade['hold_days'] = bars_held
                    self.current_trade['sell_reason'] = self.last_sell_reason or 'unknown'
                    self.trade_records.append(self.current_trade.copy())
                
                self.in_position = False
    
        elif order.status in [order.Rejected, order.Margin, order.Canceled]:
            if self.params.printlog:
                print(f'订单失败: {order.getstatusname()}')
            
            if order.isbuy() and self.first_buy_price == 0:
                self.valid_setup = False
                self.golden_min_val = None
        
        if not order.alive():
            self.order = None
    
    def stop(self):
        """策略结束时打印统计"""
        self._print_statistics()
    
    def _print_trade_details(self):
        """打印交易明细"""
        if not self.trade_records:
            print('\n暂无交易记录')
            return
        
        print('\n' + '='*100)
        print('交易明细')
        print('='*100)
        
        header = f"{'序号':<4} {'买入日期':<12} {'买入价':<8} {'补仓次数':<8} {'卖出日期':<12} {'卖出价':<8} {'收益率':<10} {'盈利金额':<12} {'卖出原因':<20}"
        print(header)
        print('-' * 120)
        
        for idx, trade in enumerate(self.trade_records, 1):
            buy_date = trade.get('buy_date', '')
            buy_price = f"{trade.get('buy_price', 0):.2f}"
            add_count = trade.get('add_count', 0)
            sell_date = trade.get('sell_date', '')
            sell_price = f"{trade.get('sell_price', 0):.2f}"
            profit_pct = f"{trade.get('profit_pct', 0):+.2f}%"
            profit_amount = f"{trade.get('profit_amount', 0):+.2f}"
            sell_reason = trade.get('sell_reason', '')[:18]
            
            row = f"{idx:<4} {str(buy_date):<12} {buy_price:<8} {add_count:<8} {str(sell_date):<12} {sell_price:<8} {profit_pct:<10} {profit_amount:<12} {sell_reason:<20}"
            print(row)
        
        print('='*100)
        
        # 统计补仓交易
        add_trades = [t for t in self.trade_records if t.get('add_count', 0) > 0]
        if add_trades:
            add_win = sum(1 for t in add_trades if t.get('profit_amount', 0) > 0)
            print(f'\n📊 补仓交易统计: 次数={len(add_trades)}, 盈利={add_win}, 胜率={add_win/len(add_trades)*100:.2f}%')
        
        # 统计止盈交易
        take_profit_trades = [t for t in self.trade_records if '止盈' in t.get('sell_reason', '')]
        if take_profit_trades:
            print(f'\n📊 止盈交易统计: 次数={len(take_profit_trades)}')
        
        # 统计止损交易
        stop_loss_trades = [t for t in self.trade_records if '止损' in t.get('sell_reason', '')]
        if stop_loss_trades:
            print(f'\n📊 止损交易统计: 次数={len(stop_loss_trades)}')
    
    def _print_statistics(self):
        """打印统计信息"""
        print('\n' + '='*80)
        print(f'黄金分割线策略 - 回测统计 ({self.params.symbol})')
        print('='*80)
        
        print(f'总交易次数: {self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'胜率: {win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'总盈利: {self.total_profit:.2f}')
            print(f'总亏损: {self.total_loss:.2f}')
            net_profit = self.total_profit - self.total_loss
            print(f'净收益: {net_profit:.2f}')
            if self.trade_count > 0:
                print(f'平均每笔收益: {net_profit/self.trade_count:.2f}')
        
        print(f'\n按持有天数统计收益:')
        for days in sorted(self.hold_days_returns.keys()):
            returns = self.hold_days_returns[days]
            if returns:
                plus_num = sum(1 for r in returns if r > 0)
                avg_return = np.mean(returns)
                print(f'  第 {days} 天: 正收益{plus_num}/{len(returns)}, 平均收益: {avg_return:.2f}%')
        
        if self.add_trade_count > 0:
            add_win_rate = self.add_win_count / self.add_trade_count * 100 if self.add_trade_count > 0 else 0
            print(f'\n补仓统计: 次数={self.add_trade_count}, 胜率={add_win_rate:.2f}%')
        
        self._print_trade_details()
        
        print('='*80)


def run_backtest(symbol, df, start_date='2020-01-01', end_date='2025-12-31',
                 initial_cash=1000000, stake=40000, printlog=True, 
                 max_hold_days=60, take_profit_pct=3.0, stop_loss_pct=8.0, max_add_count=2):
    """运行 Backtrader 回测"""
    print(f"\n开始回测 {symbol}")
    
    required_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
    for col in required_columns:
        if col not in df.columns:
            print(f"{symbol} 数据缺少 {col} 列，跳过")
            return None
    
    df_copy = df.copy()
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_copy.sort_index(inplace=True)
    
    df_filtered = df_copy[start_date:end_date]
    
    if len(df_filtered) < 70:
        print(f"{symbol} 数据不足（{len(df_filtered)}条），跳过")
        return None
    
    cerebro = bt.Cerebro()
    
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
    
    cerebro.addstrategy(
        GoldenLineStrategy,
        symbol=symbol,
        stake=stake,
        max_hold_days=max_hold_days,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_add_count=max_add_count,
        threshold=1.7,
        klines=10,
        min_angle=12,
        printlog=printlog
    )
    
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0003)
    
    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    
    total_return = (final_value - initial_value) / initial_value * 100
    
    print(f'{symbol} 回测完成 | 初始资金: {initial_cash:,.2f} | '
          f'最终资金: {final_value:,.2f} | 收益率: {total_return:.2f}%')
    
    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': results[0].trade_count,
        'win_count': results[0].win_count,
        'total_profit': results[0].total_profit,
        'total_loss': results[0].total_loss,
        'strategy': results[0]
    }


def print_interim_results(results, processed_count):
    """打印阶段性回测结果（每100只股票）"""
    if not results:
        return
    
    print("\n" + "=" * 80)
    print(f"阶段性回测结果 - 已处理 {processed_count} 只股票")
    print("=" * 80)
    
    all_returns = [r['total_return'] for r in results]
    total_trades = sum(r.get('trade_count', 0) for r in results)
    total_wins = sum(r.get('win_count', 0) for r in results)
    total_profit = sum(r.get('total_profit', 0) for r in results)
    total_loss = sum(r.get('total_loss', 0) for r in results)
    
    print(f"\n股票统计:")
    print(f"  成功回测股票数: {len(results)}")
    print(f"  平均收益率: {np.mean(all_returns):.2f}%")
    print(f"  中位数收益率: {np.median(all_returns):.2f}%")
    print(f"  最大收益率: {np.max(all_returns):.2f}%")
    print(f"  最小收益率: {np.min(all_returns):.2f}%")
    print(f"  标准差: {np.std(all_returns):.2f}%")
    
    positive_count = sum(1 for r in all_returns if r > 0)
    print(f"  正收益股票占比: {positive_count/len(results)*100:.2f}%")
    
    print(f"\n交易统计:")
    print(f"  总交易次数: {total_trades}")
    if total_trades > 0:
        print(f"  总胜率: {total_wins/total_trades*100:.2f}%")
    print(f"  总盈利金额: {total_profit:,.2f} 元")
    print(f"  总亏损金额: {total_loss:,.2f} 元")
    print(f"  净收益: {total_profit - total_loss:,.2f} 元")
    
    print("=" * 80)


def get_daily_symbols_from_file():
    """从数据库获取股票列表的替代函数"""
    try:
        from czsc_sqlite import get_daily_symbols
        return get_daily_symbols()
    except:
        # 如果无法导入，使用默认列表
        return ['sh.600000', 'sh.600004', 'sh.600006', 'sh.600007', 'sh.600008']


def main():
    """主函数：批量回测"""
    print("="*80)
    print("黄金分割线策略 - Backtrader 批量回测（支持多次补仓+止盈+止损）")
    print("="*80)
    print("\n策略参数配置:")
    print("  - 止盈: 3%")
    print("  - 止损: 8%")
    print("  - 最大补仓次数: 2次")
    print("  - 最大持有天数: 60天")
    print("  - 每次买入金额: 40,000元")
    print("="*80)
    
    try:
        all_symbols = get_daily_symbols_from_file()
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        print("使用测试列表...")
        all_symbols = ['sh.600000', 'sh.600004', 'sh.600006']
    
    start_date = "2020-01-01"
    end_date = "2021-01-01"
    results = []
    symbol_count = 0
    
    # 策略参数
    MAX_HOLD_DAYS = 60      # 最大持有天数
    TAKE_PROFIT_PCT = 3.0   # 止盈百分比
    STOP_LOSS_PCT = 8.0     # 止损百分比（新增）
    MAX_ADD_COUNT = 2       # 最大补仓次数（修改为2次）
    
    for idx, symbol in enumerate(all_symbols):
        symbol_count += 1
        # if symbol_count != 845:
        #     continue
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度: {symbol_count} / {len(all_symbols)}")
        
        try:
            # 使用优化后的数据获取函数，支持end_date
            df = get_local_stock_data(symbol, start_date=start_date, end_date=end_date)
            
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue
            
            result = run_backtest(
                symbol=symbol,
                df=df,
                start_date=start_date,
                end_date=end_date,
                initial_cash=1000000,
                stake=40000,
                printlog=False,  # 批量运行时关闭详细日志
                max_hold_days=MAX_HOLD_DAYS,
                take_profit_pct=TAKE_PROFIT_PCT,
                stop_loss_pct=STOP_LOSS_PCT,
                max_add_count=MAX_ADD_COUNT
            )
            
            if result:
                results.append(result)
            
            # 每处理100只股票打印一次阶段性结果
            if symbol_count % 100 == 0:
                print_interim_results(results, symbol_count)
        
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            continue
    
    # 最终结果统计
    print("\n" + "="*80)
    print("全部回测完成 - 总体统计")
    print("="*80)
    
    if results:
        all_returns = [r['total_return'] for r in results]
        total_trades = sum(r.get('trade_count', 0) for r in results)
        total_wins = sum(r.get('win_count', 0) for r in results)
        total_profit = sum(r.get('total_profit', 0) for r in results)
        total_loss = sum(r.get('total_loss', 0) for r in results)
        
        print(f"\n股票统计:")
        print(f"  回测股票数量: {len(results)}")
        print(f"  平均收益率: {np.mean(all_returns):.2f}%")
        print(f"  中位数收益率: {np.median(all_returns):.2f}%")
        print(f"  最大收益率: {np.max(all_returns):.2f}%")
        print(f"  最小收益率: {np.min(all_returns):.2f}%")
        print(f"  标准差: {np.std(all_returns):.2f}%")
        
        positive_count = sum(1 for r in all_returns if r > 0)
        print(f"  正收益股票占比: {positive_count/len(results)*100:.2f}%")
        
        print(f"\n交易统计:")
        print(f"  总交易次数: {total_trades}")
        if total_trades > 0:
            print(f"  总胜率: {total_wins/total_trades*100:.2f}%")
        print(f"  总盈利金额: {total_profit:,.2f} 元")
        print(f"  总亏损金额: {total_loss:,.2f} 元")
        print(f"  净收益: {total_profit - total_loss:,.2f} 元")
        
        # 导出结果到CSV
        results_df = pd.DataFrame(results)
        results_df.to_csv('backtest_results.csv', index=False, encoding='utf-8-sig')
        print(f"\n详细结果已保存到: backtest_results.csv")
    else:
        print("没有成功回测的股票数据")
    
    print("\n" + "="*80)


if __name__ == '__main__':
    main()

"""
2020-01-01到2021-01-01
交易统计:
  总交易次数: 123
  总胜率: 64.23%
  总盈利金额: 242,354.93 元
  总亏损金额: 169,661.04 元
  净收益: 72,693.89 元
"""