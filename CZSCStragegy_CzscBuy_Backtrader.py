# coding: utf-8
"""
中枢一二三买点策略 - Backtrader 回测版本
基于黄金分割线策略框架重构

策略核心：
1. 使用缠论识别一二三买点
2. 在买点形成时买入
3. 买入后持有到形成新的上涨一笔
4. 支持补仓操作（新底分型且价格低于成本）
5. 支持止损（整体亏损8%）
"""
import os
import sys
import pandas as pd
import numpy as np
import backtrader as bt
import baostock as bs
from datetime import datetime
from collections import defaultdict
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

g_output_picker_res = []
class ZhongshuBuyStrategy(bt.Strategy):
    """
    中枢一二三买点策略
    
    参数:
        max_hold_days: 最大持有天数，默认60
        stake: 每次买入最大金额，默认40000
        take_profit_pct: 止盈百分比，默认3（%）
        stop_loss_pct: 止损百分比，默认8（%）
        max_add_count: 最大补仓次数，默认2
        use_macd_filter: 是否使用MACD过滤，默认True
        printlog: 是否打印日志，默认True
    """
    
    params = (
        ('symbol', ''),
        ('max_hold_days', 60),
        ('stake', 40000),
        ('take_profit_pct', 3.0),
        ('stop_loss_pct', 8.0),
        ('max_add_count', 2),
        ('use_macd_filter', True),
        ('printlog', True),
        ('output_picker', False),
        ('macd_fast', 12),
        ('macd_slow', 26),
        ('macd_signal', 9),
    )
    
    def __init__(self):
        # 状态变量
        self.order = None
        self.in_position = False
        
        # 买入信息
        self.first_buy_price = 0
        self.first_buy_bar = 0
        self.buy_price = 0  # 平均成本
        self.buy_bar = 0
        self.buy_date = None
        self.buy_type = None  # 1:一买, 2:二买, 3:三买
        
        # 补仓相关
        self.add_count = 0
        self.add_prices = []
        
        # 止盈止损标志
        self.has_taken_profit = False
        self.has_checked_stop_loss = False
        
        # 缠论相关数据
        self.bars = []
        self.ubi_fxs = []
        self.bi_list = []
        self.zs_list = []
        self.current_bar_index = 0
        
        # 卖出条件跟踪
        self.bought_bi_count = None
        self.waiting_for_up_bi = False
        
        # MACD指标
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
        self.stop_loss_count = 0
        self.take_profit_count = 0
        
        # 收益统计
        self.all_returns = []
        self.hold_days_returns = {x: [] for x in range(1, self.params.max_hold_days + 1)}
        self.plus_list = []
        self.minus_list = []
        
        # 交易记录
        self.trade_records = []
        self.current_trade = None
        
        # 买点统计
        self.buy_type_stats = defaultdict(lambda: {'total': 0, 'win': 0, 'returns': []})
        
        # 补仓统计
        self.add_trade_count = 0
        self.add_win_count = 0
        
        # 最近卖出原因
        self._last_sell_reason = ""
        
        # 最后信号日期（避免重复）
        self.last_buy_signal_date = None
        
        # 缓存DataFrame
        self.cached_df = None
        
    def next(self):
        """主逻辑：每个bar执行"""
        if self.order:
            return
        
        self.current_bar_index = len(self)
        
        # 收集K线数据
        bar = {
            'date': self.data.datetime.date(0),
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': self.data.close[0],
            'volume': self.data.volume[0],
            'amount': self.data.close[0] * self.data.volume[0],  # 估算成交额
            'index': self.current_bar_index
        }
        self.bars.append(bar)
        
        # 优化性能
        if self.params.output_picker:
            buy_date = self.data.datetime.date(0)
            last_trade_date = datetime.strptime(get_latest_trade_date(), "%Y-%m-%d").date()
            if (last_trade_date-buy_date).days>100:
                return

        # 限制bars内存使用
        # if len(self.bars) > 500:
        #     self.bars = self.bars[-500:]
        
        # 更新缠论笔划分
        if len(self.bars) >= 5:
            self._update_czsc()
        
        # 如果持有仓位，检查卖出条件
        if self.position:
            bars_held = self.current_bar_index - self.buy_bar
            current_price = self.data.close[0]
            
            # 计算整体收益率
            avg_cost = self.buy_price
            total_profit_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0
            
            # 卖出条件1：止损（亏损达到8%且已达到最大补仓次数）
            if total_profit_pct <= -self.params.stop_loss_pct and self.add_count >= self.params.max_add_count:
                if not self.has_checked_stop_loss:
                    self._log(f'【止损信号】整体亏损: {total_profit_pct:.2f}%, 达到止损线')
                    self._sell_order(reason=f"止损_{total_profit_pct:.2f}%")
                    self.stop_loss_count += 1
                    self.has_checked_stop_loss = True
                    return
            
            # 卖出条件2：止盈（首次买入后涨幅达到3%）
            profit_from_first = (current_price - self.first_buy_price) / self.first_buy_price * 100 if self.first_buy_price > 0 else 0
            if profit_from_first >= self.params.take_profit_pct and not self.has_taken_profit and self.add_count == 0:
                self._log(f'【止盈信号】从首次买入涨幅: {profit_from_first:.2f}%, 达到止盈线')
                self._sell_order(reason=f"止盈_{profit_from_first:.2f}%")
                self.take_profit_count += 1
                self.has_taken_profit = True
                return
            
            # 卖出条件3：形成新的上涨一笔
            if self.waiting_for_up_bi and self._check_new_up_bi_formed():
                self._sell_order(reason="新上涨一笔形成")
                return
            
            # 卖出条件4：超过最大持有天数
            if bars_held >= self.params.max_hold_days:
                self._sell_order(reason=f"超时_{self.params.max_hold_days}天")
                return
            
            # 持仓中，检查补仓条件
            if self.first_buy_price > 0 and self.add_count < self.params.max_add_count:
                self._check_add_position()
                
        else:
            # 无持仓，重置状态
            self._reset_position_state()
            
            # 检查买点信号
            buy_type = self._check_buy_signal()
            if buy_type:
                # MACD过滤（可选）
                if not self.params.use_macd_filter or self._check_macd_condition():
                    self._buy_order(buy_type)
    
    def _reset_position_state(self):
        """重置持仓状态"""
        self.first_buy_price = 0
        self.first_buy_bar = 0
        self.buy_price = 0
        self.buy_bar = 0
        self.buy_date = None
        self.buy_type = None
        self.add_count = 0
        self.add_prices = []
        self.waiting_for_up_bi = False
        self.bought_bi_count = None
        self.has_taken_profit = False
        self.has_checked_stop_loss = False
        self.last_buy_signal_date = None
        self.current_trade = None
        
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
                self.ubi_fxs = c.ubi_fxs
                self.bi_list = c.bi_list
                self.zs_list = get_zs_seq(self.bi_list)
                
        except Exception as e:
            if self.params.printlog:
                print(f"CZSC分析错误: {e}")
    
    def _check_buy_signal(self):
        """检查一二三买点信号"""
        if len(self.bars) < 50:
            return None
            
        # 避免同一日期重复信号
        current_date = self.bars[-1]['date']
        if self.last_buy_signal_date == current_date:
            return None
            
        try:
            df = pd.DataFrame(self.bars)
            df['date'] = pd.to_datetime(df['date'])
            
            # 调用原有买点检测函数
            buy_type = get_buy_point_type(
                symbol=self.params.symbol, 
                df=df,
                c_bi_list=self.bi_list,
                c_zs_list=self.zs_list
            )
            
            if buy_type and buy_type in [1, 2, 3]:
                self.last_buy_signal_date = current_date
                self._log(f'检测到{buy_type}买点信号')
                return buy_type
                
        except Exception as e:
            if self.params.printlog:
                print(f"买点检测错误: {e}")
                
        return None
    
    def _check_new_up_bi_formed(self):
        """检查是否形成了新的上涨一笔"""
        if self.bought_bi_count is None:
            return False
            
        if len(self.bi_list) <= self.bought_bi_count:
            return False
            
        # 检查从买入后是否有新的上涨笔形成
        for i in range(self.bought_bi_count, len(self.bi_list)):
            bi = self.bi_list[i]
            if bi.fx_a.fx < bi.fx_b.fx:  # 上涨笔
                # 可选：MACD红柱确认
                current_hist = self.macd.macd[0] - self.macd.signal[0]
                if current_hist > 0:
                    self._log(f'检测到新上涨一笔: {bi.fx_a.dt.date()} -> {bi.fx_b.dt.date()}')
                    return True
                else:
                    # 即使MACD不红，也卖出
                    self._log(f'检测到新上涨一笔(无MACD确认): {bi.fx_a.dt.date()} -> {bi.fx_b.dt.date()}')
                    return True
                    
        return False
    
    def _check_bottom_fractal(self):
        """检测底分型"""
        if len(self.ubi_fxs) <= 0:
            return False, None
            
        # 最后一个分型
        last_fx = self.ubi_fxs[-1]
        if last_fx.mark == Mark.G:  # 顶分型跳过
            return False, None
            
        # 检查分型日期是否为当前日期
        current_date = self.bars[-1]['date']
        fx_date = last_fx.dt.date() if hasattr(last_fx.dt, 'date') else last_fx.dt
        
        if fx_date == current_date:
            self._log(f'检测到底分型: 日期={fx_date}, 价格={last_fx.fx:.2f}')
            return True, last_fx
            
        return False, None
    
    def _check_add_position(self):
        """检查补仓条件"""
        current_price = self.data.close[0]
        current_date = self.bars[-1]['date']
        
        # 条件1：价格低于首次买入价
        if current_price >= self.first_buy_price:
            return False
            
        # 条件2：检测底分型
        is_bottom, last_fx = self._check_bottom_fractal()
        if not is_bottom:
            return False
            
        # 条件3：分型价格低于当前平均成本
        if last_fx and last_fx.fx >= self.buy_price:
            self._log(f'补仓跳过: 分型价{last_fx.fx:.2f} >= 成本{self.buy_price:.2f}')
            return False
            
        # 条件4：当天没有补仓过
        if self.add_prices and self.add_prices[-1].get('date') == current_date:
            return False
            
        # 执行补仓
        self.add_count += 1
        size = self._calculate_add_size()
        
        if size > 0:
            self._log(f'【补仓信号 #{self.add_count}/{self.params.max_add_count}】'
                      f'日期: {current_date}, 价格: {current_price:.2f}, 均价: {self.buy_price:.2f}')
            self._add_order(size)
            return True
            
        return False
    
    def _check_macd_condition(self):
        """检查MACD条件"""
        if len(self.macd.macd) < 2:
            return True
            
        current_hist = self.macd.macd[0] - self.macd.signal[0]
        prev_hist = self.macd.macd[-1] - self.macd.signal[-1]
        
        # 绿柱缩短或即将金叉
        if current_hist < 0:
            # 绿柱缩短
            if current_hist > prev_hist:
                return True
        else:
            # 红柱出现
            return True
            
        return False
    
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
        """计算补仓数量"""
        cash_available = self.broker.getcash()
        current_price = self.data.close[0]
        
        target_amount = self.params.stake * 0.8  # 补仓使用80%的初始金额
        
        if cash_available < target_amount * 1.003:
            target_amount = cash_available * 0.8
            
        return self._calculate_size_by_amount(target_amount, current_price)
    
    def _buy_order(self, buy_type):
        buy_type_name = {1: '一买', 2: '二买', 3: '三买'}.get(buy_type, f'{buy_type}买')

        """选股"""
        if self.params.output_picker:
            buy_date = self.data.datetime.date(0)
            last_trade_date = datetime.strptime(get_latest_trade_date(), "%Y-%m-%d").date()
            if (last_trade_date-buy_date).days < 1:
                g_output_picker_res.append({
                    'symbol':self.params.symbol,
                    'action':buy_type_name,
                    'date':buy_date.strftime("%Y-%m-%d")
                })
        
        """执行买入"""
        size = self._calculate_initial_size()
        
        if size == 0:
            return
            
        cash_available = self.broker.getcash()
        price = self.data.close[0]
        
        if cash_available < price * size * 1.003:
            self._log(f'资金不足: 可用{cash_available:.2f}, 需要{price * size:.2f}')
            return
            
        self.order = self.buy(size=size)
        self.buy_type = buy_type
        
        buy_type_name = {1: '一买', 2: '二买', 3: '三买'}.get(buy_type, f'{buy_type}买')
        self._log(f'【买入信号-{buy_type_name}】日期: {self.data.datetime.date(0)}, '
                  f'价格: {price:.2f}, 数量: {size}')
    
    def _add_order(self, size):
        """选股"""
        if self.params.output_picker:
            buy_date = self.data.datetime.date(0)
            last_trade_date = datetime.strptime(get_latest_trade_date(), "%Y-%m-%d").date()
            if (last_trade_date-buy_date).days < 1:
                g_output_picker_res.append({
                    'symbol':self.params.symbol,
                    'action':'补仓',
                    'date':buy_date.strftime("%Y-%m-%d")
                })
        
        """执行补仓"""
        price = self.data.close[0]
        self.order = self.buy(size=size)
        
    def _sell_order(self, reason=""):
        """选股"""
        if self.params.output_picker:
            buy_date = self.data.datetime.date(0)
            last_trade_date = datetime.strptime(get_latest_trade_date(), "%Y-%m-%d").date()
            if (last_trade_date-buy_date).days < 1:
                g_output_picker_res.append({
                    'symbol':self.params.symbol,
                    'action':reason,
                    'date':buy_date.strftime("%Y-%m-%d")
                })
        
        """执行卖出"""
        if self.position:
            self._last_sell_reason = reason
            self._log(f'【卖出信号】日期: {self.data.datetime.date(0)}, '
                      f'价格: {self.data.close[0]:.2f}, 持仓: {self.position.size}, 原因: {reason}')
            self.order = self.close()
    
    def _log(self, msg):
        """日志输出"""
        if self.params.printlog:
            print(f'{datetime.now().strftime("%Y-%m-%d %H:%M:%S")} - {msg}')
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                exec_price = order.executed.price
                exec_size = order.executed.size
                exec_date = self.data.datetime.date(0)
                
                if self.first_buy_price == 0:
                    # 首次买入
                    self.first_buy_price = exec_price
                    self.first_buy_bar = self.current_bar_index
                    self.buy_price = exec_price
                    self.buy_bar = self.current_bar_index
                    self.buy_date = exec_date
                    self.in_position = True
                    self.trade_count += 1
                    self.bought_bi_count = len(self.bi_list)
                    self.waiting_for_up_bi = True
                    self.has_taken_profit = False
                    self.has_checked_stop_loss = False
                    
                    self._log(f'【买入成交】日期: {exec_date}, '
                              f'价格: {exec_price:.2f}, 数量: {exec_size}, 类型: {self.buy_type}买')
                    
                    # 记录交易
                    self.current_trade = {
                        'buy_date': exec_date,
                        'buy_price': exec_price,
                        'buy_size': exec_size,
                        'buy_type': self.buy_type,
                        'add_count': 0,
                        'add_details': [],
                        'sell_date': None,
                        'sell_price': None,
                        'profit_pct': None,
                        'profit_amount': None,
                        'hold_days': None,
                        'sell_reason': None
                    }
                    
                    # 统计买点类型
                    self.buy_type_stats[self.buy_type]['total'] += 1
                    
                else:
                    # 补仓成交
                    self.add_trade_count += 1
                    self.add_prices.append({'date': exec_date, 'price': exec_price, 'size': exec_size})
                    self.buy_price = self.position.price  # 更新平均成本
                    
                    self._log(f'【补仓成交 #{self.add_count}/{self.params.max_add_count}】'
                              f'日期: {exec_date}, 价格: {exec_price:.2f}, 数量: {exec_size}')
                    
                    if self.current_trade:
                        self.current_trade['add_count'] = self.add_count
                        self.current_trade['add_details'].append({
                            'date': exec_date,
                            'price': exec_price,
                            'size': exec_size
                        })
                        
            else:
                # 卖出成交
                sell_price = order.executed.price
                sell_size = abs(order.size)
                sell_date = self.data.datetime.date(0)
                
                # 计算收益
                profit_amount = (sell_price - self.buy_price) * sell_size
                profit_pct = (sell_price - self.buy_price) / self.buy_price * 100 if self.buy_price > 0 else 0
                bars_held = self.current_bar_index - self.buy_bar
                
                # 更新统计
                if profit_amount > 0:
                    self.win_count += 1
                    self.total_profit += profit_amount
                    self.plus_list.append(profit_pct)
                    
                    # 买点类型胜率统计
                    if self.buy_type:
                        self.buy_type_stats[self.buy_type]['win'] += 1
                        self.buy_type_stats[self.buy_type]['returns'].append(profit_pct)
                else:
                    self.loss_count += 1
                    self.total_loss += abs(profit_amount)
                    self.minus_list.append(profit_pct)
                
                # 补仓交易胜率
                if self.add_count > 0 and profit_amount > 0:
                    self.add_win_count += 1
                
                # 持有天数收益统计
                actual_days = min(bars_held, self.params.max_hold_days)
                if actual_days in self.hold_days_returns:
                    self.hold_days_returns[actual_days].append(profit_pct)
                
                self.all_returns.append(profit_pct)
                
                self._log(f'【卖出成交】卖出价: {sell_price:.2f}, 成本: {self.buy_price:.2f}, '
                          f'收益: {profit_pct:+.2f}% ({profit_amount:+.2f}元), 持有: {bars_held}天, '
                          f'原因: {self._last_sell_reason}')
                
                # 保存交易记录
                if self.current_trade:
                    self.current_trade['sell_date'] = sell_date
                    self.current_trade['sell_price'] = sell_price
                    self.current_trade['profit_pct'] = profit_pct
                    self.current_trade['profit_amount'] = profit_amount
                    self.current_trade['hold_days'] = bars_held
                    self.current_trade['sell_reason'] = self._last_sell_reason
                    self.trade_records.append(self.current_trade.copy())
                
                self.in_position = False
                
        elif order.status in [order.Rejected, order.Margin, order.Canceled]:
            self._log(f'订单失败: {order.getstatusname()}')
            
        if not order.alive():
            self.order = None
    
    def stop(self):
        """策略结束时的统计"""
        self._print_statistics()
    
    def _print_statistics(self):
        """打印统计信息"""
        print('\n' + '='*80)
        print(f'中枢一二三买点策略 - 回测统计 ({self.params.symbol})')
        print('='*80)
        
        print(f'\n【交易统计】')
        print(f'  总交易次数: {self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'  胜率: {win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'  止损次数: {self.stop_loss_count}')
            print(f'  止盈次数: {self.take_profit_count}')
            print(f'  总盈利: {self.total_profit:.2f}')
            print(f'  总亏损: {self.total_loss:.2f}')
            net_profit = self.total_profit - self.total_loss
            print(f'  净收益: {net_profit:.2f}')
            if self.trade_count > 0:
                print(f'  平均每笔收益: {net_profit/self.trade_count:.2f}')
        
        print(f'\n【买点类型统计】')
        for buy_type in [1, 2, 3]:
            stats = self.buy_type_stats.get(buy_type, {'total': 0, 'win': 0, 'returns': []})
            if stats['total'] > 0:
                type_name = {1: '一买', 2: '二买', 3: '三买'}[buy_type]
                win_rate = stats['win'] / stats['total'] * 100
                avg_return = np.mean(stats['returns']) if stats['returns'] else 0
                print(f'  {type_name}: 次数={stats["total"]}, 胜率={win_rate:.2f}%, 平均收益={avg_return:.2f}%')
        
        if self.add_trade_count > 0:
            add_win_rate = self.add_win_count / self.add_trade_count * 100
            print(f'\n【补仓统计】')
            print(f'  补仓次数: {self.add_trade_count}, 胜率: {add_win_rate:.2f}%')
        
        print(f'\n【持有天数收益】')
        for days in sorted([d for d in self.hold_days_returns.keys() if self.hold_days_returns[d]]):
            returns = self.hold_days_returns[days]
            if returns:
                plus_num = sum(1 for r in returns if r > 0)
                avg_return = np.mean(returns)
                print(f'  第{days}天: 正收益{plus_num}/{len(returns)}, 平均收益: {avg_return:.2f}%')
        
        self._print_trade_details()
        print('='*80)
    
    def _print_trade_details(self):
        """打印交易明细"""
        if not self.trade_records:
            print('\n暂无交易记录')
            return
        
        print('\n' + '='*120)
        print('交易明细')
        print('='*120)
        
        header = f"{'序号':<4} {'买入日期':<12} {'买入价':<8} {'买点':<6} {'补仓':<6} {'卖出日期':<12} {'卖出价':<8} {'收益率':<10} {'盈利金额':<14} {'卖出原因':<20}"
        print(header)
        print('-'*130)
        
        for idx, trade in enumerate(self.trade_records, 1):
            buy_date = trade.get('buy_date', '')
            buy_price = f"{trade.get('buy_price', 0):.2f}"
            buy_type = {1: '一买', 2: '二买', 3: '三买'}.get(trade.get('buy_type'), '')
            add_count = trade.get('add_count', 0)
            sell_date = trade.get('sell_date', '')
            sell_price = f"{trade.get('sell_price', 0):.2f}"
            profit_pct = f"{trade.get('profit_pct', 0):+.2f}%"
            profit_amount = f"{trade.get('profit_amount', 0):+.2f}"
            sell_reason = trade.get('sell_reason', '')[:18]
            
            row = f"{idx:<4} {str(buy_date):<12} {buy_price:<8} {buy_type:<6} {add_count:<6} {str(sell_date):<12} {sell_price:<8} {profit_pct:<10} {profit_amount:<14} {sell_reason:<20}"
            print(row)
        
        print('='*120)


def run_backtest(symbol, df, start_date='2020-01-01', end_date='2025-12-31',
                 initial_cash=1000000, stake=40000, printlog=True,
                 max_hold_days=60, take_profit_pct=3.0, stop_loss_pct=8.0,
                 max_add_count=2, use_macd_filter=True, output_picker=False):
    """运行Backtrader回测"""
    
    if df is None or len(df) < 70:
        print(f"{symbol} 数据不足，跳过")
        return None
    
    # 数据预处理
    df_copy = df.copy()
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_copy.sort_index(inplace=True)
    
    # 过滤日期范围
    df_filtered = df_copy[start_date:end_date]
    
    if len(df_filtered) < 50:
        print(f"{symbol} 回测区间数据不足（{len(df_filtered)}条），跳过")
        return None
    
    # 创建Cerebro
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
        ZhongshuBuyStrategy,
        symbol=symbol,
        stake=stake,
        max_hold_days=max_hold_days,
        take_profit_pct=take_profit_pct,
        stop_loss_pct=stop_loss_pct,
        max_add_count=max_add_count,
        use_macd_filter=use_macd_filter,
        printlog=printlog,
        output_picker=output_picker
    )
    
    # 设置初始资金和佣金
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0003)
    
    # 运行回测
    initial_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    
    total_return = (final_value - initial_value) / initial_value * 100
    
    strategy = results[0]
    
    print(f'{symbol} 回测完成 | 初始资金: {initial_cash:,.2f} | '
          f'最终资金: {final_value:,.2f} | 收益率: {total_return:.2f}%')
    
    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': strategy.trade_count,
        'win_count': strategy.win_count,
        'total_profit': strategy.total_profit,
        'total_loss': strategy.total_loss,
        'buy_type_stats': dict(strategy.buy_type_stats),
        'strategy': strategy
    }


def batch_backtest(all_symbols, start_date='2022-01-01', end_date='2023-01-01',
                   initial_cash=1000000, stake=40000, max_hold_days=60,
                   take_profit_pct=3.0, stop_loss_pct=8.0, max_add_count=2,
                   use_macd_filter=True, output_picker=False):
    """批量回测"""
    
    results = []
    
    for idx, symbol in enumerate(all_symbols):
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度: {idx+1} / {len(all_symbols)} - {symbol}")
        
        try:
            # 获取本地数据
            if output_picker:
                df = get_stock_pd(symbol, start_date, end_date, 'd')
            else:
                df = get_local_stock_data(symbol, start_date, end_date)
            
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue
            
            result = run_backtest(
                symbol=symbol,
                df=df,
                start_date=start_date,
                end_date=end_date,
                initial_cash=initial_cash,
                stake=stake,
                printlog=False,
                max_hold_days=max_hold_days,
                take_profit_pct=take_profit_pct,
                stop_loss_pct=stop_loss_pct,
                max_add_count=max_add_count,
                use_macd_filter=use_macd_filter,
                output_picker=output_picker
            )
            
            if result:
                results.append(result)
                
            # 每100只打印一次汇总
            if (idx + 1) % 10 == 0:
                _print_batch_summary(results)
                
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            continue
    
    # 最终汇总
    _print_batch_summary(results, final=True)
    
    return results


def _print_batch_summary(results, final=False):
    """打印批量回测汇总"""
    if not results:
        print("暂无回测结果")
        return
    
    all_returns = [r['total_return'] for r in results]
    total_trades = sum(r.get('trade_count', 0) for r in results)
    total_wins = sum(r.get('win_count', 0) for r in results)
    
    print("\n" + "="*80)
    if final:
        print("【最终汇总】批量回测统计")
    else:
        print("【阶段性汇总】")
    print("="*80)
    
    print(f"\n股票统计:")
    print(f"  成功回测股票数: {len(results)}")
    print(f"  平均收益率: {np.mean(all_returns):.2f}%")
    print(f"  中位数收益率: {np.median(all_returns):.2f}%")
    print(f"  最大收益率: {np.max(all_returns):.2f}%")
    print(f"  最小收益率: {np.min(all_returns):.2f}%")
    print(f"  正收益股票占比: {sum(1 for r in all_returns if r > 0) / len(results) * 100:.2f}%")
    
    print(f"\n交易统计:")
    print(f"  总交易次数: {total_trades}")
    if total_trades > 0:
        print(f"  总胜率: {total_wins / total_trades * 100:.2f}%")
    
    # 买点类型统计
    buy_type_stats = {1: {'total': 0, 'win': 0}, 2: {'total': 0, 'win': 0}, 3: {'total': 0, 'win': 0}}
    for r in results:
        for bt_type, stats in r.get('buy_type_stats', {}).items():
            if bt_type in buy_type_stats:
                buy_type_stats[bt_type]['total'] += stats.get('total', 0)
                buy_type_stats[bt_type]['win'] += stats.get('win', 0)
    
    print(f"\n买点类型统计:")
    for bt_type, stats in buy_type_stats.items():
        if stats['total'] > 0:
            type_name = {1: '一买', 2: '二买', 3: '三买'}[bt_type]
            win_rate = stats['win'] / stats['total'] * 100
            print(f"  {type_name}: 次数={stats['total']}, 胜率={win_rate:.2f}%")
    
    print("="*80 + "\n")


def main():
    """主函数"""
    print("="*80)
    print("中枢一二三买点策略 - Backtrader 批量回测")
    print("="*80)

    # 配置参数
    START_DATE = "2020-01-01"
    END_DATE = "2023-01-01"
    INITIAL_CASH = 1000000
    STAKE = 40000
    MAX_HOLD_DAYS = 60
    TAKE_PROFIT_PCT = 5.0
    STOP_LOSS_PCT = 8.0
    MAX_ADD_COUNT = 2
    USE_MACD_FILTER = True
    OUTPUT_PICKER = False
    if len(sys.argv) > 1:
        OUTPUT_PICKER = True
        lg = bs.login()
        # 登录baostock
        czsc_logger().info('login respond error_code:' + lg.error_code)
        czsc_logger().info('login respond  error_msg:' + lg.error_msg)
        INITIAL_CASH = 100000000
        START_DATE = "2024-01-01"
        END_DATE = get_latest_trade_date()
        write_json(g_output_picker_res, os.path.join(get_data_dir(), 'czsc_zs_buy_stock.json'))
    
    try:
        # 获取股票列表
        from czsc_daily_util import get_daily_symbols
        all_symbols = get_daily_symbols()
        print(f"获取到 {len(all_symbols)} 只股票")
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        # 使用测试列表
        all_symbols = ['sh.600000', 'sh.600036', 'sz.000001', 'sz.000002']
    
    # 运行批量回测
    results = batch_backtest(
        all_symbols=all_symbols,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_cash=INITIAL_CASH,
        stake=STAKE,
        max_hold_days=MAX_HOLD_DAYS,
        take_profit_pct=TAKE_PROFIT_PCT,
        stop_loss_pct=STOP_LOSS_PCT,
        max_add_count=MAX_ADD_COUNT,
        use_macd_filter=USE_MACD_FILTER,
        output_picker=OUTPUT_PICKER
    )
    
    # 登出系统
    if OUTPUT_PICKER:
        print(g_output_picker_res)
        write_json(g_output_picker_res, os.path.join(get_data_dir(), 'czsc_zs_buy_stock.json'))
        bs.logout()

if __name__ == '__main__':
    main()