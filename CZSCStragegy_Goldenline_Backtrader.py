# coding: utf-8
"""
黄金分割线策略 - Backtrader 回测版本
基于 CZSCStragegy_Goldenline.py 重新实现

策略核心：
1. 使用缠论笔划分识别上涨线段
2. 计算黄金分割点位（0.5和0.618）
3. 在黄金分割点附近买入
4. 持有固定天数后卖出并统计收益
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
    黄金分割线策略 - 基于缠论笔划分
    
    参数:
        threshold: 涨幅阈值，默认 1.7（上涨需超过 70%）
        klines: 最小上涨 K 线数，默认 10
        min_angle: 最小角度，默认 20
        hold_days: 持有天数，默认 5
        stake: 每次买入股数，默认 1000
    """
    
    params = (
        ('symbol', ''),
        ('threshold', 1.7),
        ('klines', 10),
        ('min_angle', 20),
        ('hold_days', 5),
        ('stake', 1000),
        ('printlog', False),
    )
    
    def __init__(self):
        # 状态变量
        self.order = None
        self.buy_price = 0
        self.buy_bar = 0
        self.buy_date = None
        self.in_position = False
        self.buy_triggered = False
        
        # 缠论相关变量
        self.bars = []  # K线数据
        self.bi_list = []  # 笔列表
        self.current_bar_index = 0
        
        # 黄金分割点相关
        self.golden_buy_zone = None
        self.valid_setup = False
        
        # 统计变量
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0
        self.total_loss = 0
        
        # 收益统计（对应原始版本的 total_ratio）
        self.all_returns = []
        
        # 按持有天数统计收益（对应原始版本的 ratio_map）
        self.hold_days_returns = {x: [] for x in range(1, self.params.hold_days + 1)}
        
        # 正负收益统计（对应原始版本的 plus_list, minus_list）
        self.plus_list = []
        self.minus_list = []
        
        # 记录所有买入点（用于调试）
        self.buy_points = []
    
    def next(self):
        """主逻辑：每个 bar 执行"""
        if self.order:
            return
        
        # 更新当前 bar 索引
        self.current_bar_index = len(self)
        
        # 收集 K 线数据
        bar = {
            'date': self.data.datetime.date(0),
            'open': self.data.open[0],
            'high': self.data.high[0],
            'low': self.data.low[0],
            'close': self.data.close[0],
            'volume': self.data.volume[0]
        }
        self.bars.append(bar)
        
        # 如果数据足够，更新缠论笔划分
        if len(self.bars) >= 5:
            self._update_czsc()
        
        # 如果持有仓位，检查卖出条件
        if self.position:
            bars_held = self.current_bar_index - self.buy_bar
            
            # 达到持有天数后卖出
            if bars_held >= self.params.hold_days:
                self._sell_order()
        else:
            # 重置买入标记
            self.buy_triggered = False
            
            # 检查是否有有效的买入信号
            if self._check_buy_signal():
                self._buy_order()
    
    def _update_czsc(self):
        """更新缠论笔划分"""
        try:
            # 将 bars 转换为 DataFrame
            df = pd.DataFrame(self.bars)
            df['date'] = pd.to_datetime(df['date'])
            
            # 创建 CZSC 对象获取笔列表
            bars = [RawBar(symbol=self.params.symbol, id=i, freq=Freq.D, open=row['open'], dt=row['date'],
                    close=row['close'], high=row['high'], low=row['low'], vol=row['volume'], amount=1)
                for i, row in df.iterrows()]
            c = CZSC(bars, get_signals=None)
            if c and c.bi_list:
                self.bi_list = c.bi_list
        except Exception as e:
            # 缠论划分出错时忽略
            print(f"CZSC analysis error: {e}")
            pass
    
    def _check_buy_signal(self):
        """
        检查黄金分割买入信号
        对应原始版本的 get_buy_point 函数
        """
        if len(self.bi_list) < 3:
            return False
        
        # 查找上涨线段（对应 find_up_seg）
        start_index = 0
        while start_index < len(self.bi_list):
            fx_a, fx_b, last_bi = self._find_up_seg(start_index)
            if fx_a and fx_b:
                end_index = start_index
                if last_bi:
                    end_index = self.bi_list.index(last_bi)
                start_index = end_index + 1
                
                # 获取下一段上涨笔（用于计算收益）
                next_up_bi = None
                if end_index + 2 < len(self.bi_list):
                    next_up_bi = self.bi_list[end_index + 2]
                
                # 检查是否符合黄金分割买入条件
                if self._check_golden_setup(fx_a, fx_b, next_up_bi):
                    return True
            else:
                break
        
        return False
    
    def _find_up_seg(self, start_index):
        """
        查找上涨线段
        对应原始版本的 find_up_seg 函数
        """
        start_bi = None
        last_bi = None
        
        for index in range(start_index, len(self.bi_list)):
            cur_bi = self.bi_list[index]
            
            # 过滤下降笔
            if cur_bi.fx_a.fx > cur_bi.fx_b.fx:
                if start_bi and start_bi.fx_a.fx >= cur_bi.fx_b.fx:
                    if start_bi.fx_b.dt == cur_bi.fx_a.dt:
                        start_bi = None
                    else:
                        if last_bi:
                            return start_bi.fx_a, last_bi.fx_b, last_bi
                        else:
                            return start_bi.fx_a, start_bi.fx_b, start_bi
                continue
            
            # 开始一笔
            if not start_bi:
                start_bi = cur_bi
                continue
            
            if last_bi:
                if (cur_bi.fx_a.fx > last_bi.fx_a.fx and 
                    cur_bi.fx_b.fx > last_bi.fx_b.fx):
                    last_bi = cur_bi
                else:
                    break
            elif (cur_bi.fx_a.fx > start_bi.fx_a.fx and 
                  cur_bi.fx_b.fx > start_bi.fx_b.fx):
                last_bi = cur_bi
                continue
            else:
                break
        
        if start_bi:
            if last_bi:
                return start_bi.fx_a, last_bi.fx_b, last_bi
            else:
                return start_bi.fx_a, start_bi.fx_b, start_bi
        return None, None, None
    
    def _check_golden_setup(self, fx_a, fx_b, next_up_bi):
        """
        检查黄金分割买入条件
        对应原始版本的 get_buy_point 函数的核心逻辑
        """
        # 检查涨幅阈值
        if fx_a.fx * self.params.threshold < fx_b.fx:
            return False
        
        # 检查上涨 K 线数
        fx_a_date = fx_a.dt.strftime("%Y-%m-%d")
        fx_b_date = fx_b.dt.strftime("%Y-%m-%d")
        
        # 将 bars 转换为 DataFrame 用于计算
        df = pd.DataFrame(self.bars)
        df['date'] = pd.to_datetime(df['date'])
        
        up_kline_num = days_trade_delta(df, fx_a_date, fx_b_date)
        if up_kline_num < self.params.klines:
            return False
        
        # 检查笔的角度
        if bi_angle(df, fx_a, fx_b) < self.params.min_angle:
            return False
        
        # 计算黄金分割位
        sqr_val = sqrt_val(fx_a.fx, fx_b.fx)
        gold_low_val = gold_val_low(fx_a.fx, fx_b.fx)
        min_val = min(sqr_val, gold_low_val)
        
        # 查找黄金分割点买入时机
        start_idx = df[df['date'] == fx_b.dt].index[0]
        end_idx = len(df['date'])
        
        if next_up_bi:
            next_up_date = next_up_bi.fx_a.dt.strftime("%Y-%m-%d")
            end_idx = df[df['date'] == next_up_date].index[0] + 1
        
        # 遍历查找买入点
        for idx in range(start_idx, min(end_idx, len(df))):
            stock_low = df['low'].iloc[idx]
            
            # 价格回调到黄金分割点附近
            if stock_low <= min_val and idx + self.params.hold_days < len(df):
                # 记录黄金买点
                self.golden_buy_zone = {
                    'min_price': min_val * 0.98,
                    'max_price': min_val * 1.02,
                    'fx_a': fx_a.fx,
                    'fx_b': fx_b.fx,
                    'buy_idx': idx,
                    'buy_date': df['date'].iloc[idx]
                }
                
                # 如果存在下一段上涨笔，记录收益
                if next_up_bi:
                    self._record_expected_return(df, idx, next_up_bi)
                
                return True
        
        return False
    
    def _record_expected_return(self, df, buy_idx, next_up_bi):
        """
        记录预期收益（对应原始版本的收益统计）
        """
        buy_close = df['close'].iloc[buy_idx]
        sell_price = next_up_bi.fx_b.fx
        ratio = round(100 * (sell_price - buy_close) / buy_close, 2)
        
        self.all_returns.append(ratio)
        
        if self.params.printlog:
            buy_date = df['date'].iloc[buy_idx]
            sell_date = next_up_bi.fx_b.dt
            print(f"预期收益: {buy_date} 买入 @{buy_close:.2f} -> "
                  f"{sell_date} 卖出 @{sell_price:.2f}, 收益率: {ratio:.2f}%")
    
    def _buy_order(self):
        """执行买入订单"""
        if not self.golden_buy_zone:
            return
        
        size = self.params.stake
        cash_available = self.broker.getcash()
        price = self.data.close[0]
        
        # 检查资金是否足够
        if cash_available < price * size * 1.003:
            if self.params.printlog:
                print(f'资金不足: 可用 {cash_available:.2f}, 需要 {price*size*1.003:.2f}')
            return
        
        # 记录买入点
        self.buy_points.append({
            'date': self.data.datetime.date(0),
            'price': price,
            'zone': self.golden_buy_zone
        })
        
        self.order = self.buy(size=size)
    
    def _sell_order(self):
        """执行卖出订单"""
        self.order = self.close()
    
    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                # 买入成交
                self.buy_price = order.executed.price
                self.buy_bar = self.current_bar_index
                self.buy_date = self.data.datetime.date(0)
                self.in_position = True
                self.trade_count += 1
                
                if self.params.printlog:
                    print(f'【买入】日期: {self.buy_date}, '
                          f'价格: {self.buy_price:.2f}')
            else:
                # 卖出成交
                sell_price = order.executed.price
                profit = sell_price - self.buy_price
                profit_pct = (profit / self.buy_price) * 100
                bars_held = self.current_bar_index - self.buy_bar
                
                # 更新统计
                if profit > 0:
                    self.win_count += 1
                    self.total_profit += profit
                    self.plus_list.append(profit_pct)
                else:
                    self.loss_count += 1
                    self.total_loss += abs(profit)
                    self.minus_list.append(profit_pct)
                
                # 记录到持有天数收益
                actual_days = min(bars_held, self.params.hold_days)
                if actual_days in self.hold_days_returns:
                    self.hold_days_returns[actual_days].append(profit_pct)
                
                if self.params.printlog:
                    print(f'【卖出】收益: {profit_pct:+.2f}%, '
                          f'持有: {bars_held}天')
                
                # 重置状态
                self.buy_price = 0
                self.buy_bar = 0
                self.buy_date = None
                self.in_position = False
                self.golden_buy_zone = None
        
        elif order.status in [order.Rejected, order.Margin, order.Canceled]:
            if self.params.printlog:
                print(f'订单失败: {order.getstatusname()}')
        
        self.order = None
    
    def stop(self):
        """策略结束时打印统计"""
        self._print_statistics()
    
    def _print_statistics(self):
        """打印统计信息，对应原始版本的 print_statistics 函数"""
        print('\n' + '='*80)
        print('黄金分割线策略 - 回测统计')
        print('='*80)
        
        # 基本统计
        print(f'总交易次数: {self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'胜率: {win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'总盈利: {self.total_profit:.2f}')
            print(f'总亏损: {self.total_loss:.2f}')
            net_profit = self.total_profit - self.total_loss
            print(f'净收益: {net_profit:.2f}')
            print(f'平均每笔收益: {net_profit/self.trade_count:.2f}')
        
        # 按持有天数统计（对应原始版本的 ratio_map）
        print(f'\n按持有天数统计收益:')
        for days in sorted(self.hold_days_returns.keys()):
            returns = self.hold_days_returns[days]
            if returns:
                plus_num = sum(1 for r in returns if r > 0)
                plus_val = sum(r for r in returns if r > 0)
                minus_val = sum(r for r in returns if r <= 0)
                plus_ratio = plus_num / len(returns) * 100 if returns else 0
                
                print(f'  第 {days} 天:')
                print(f'    正收益次数: {plus_num}')
                print(f'    正收益占比: {plus_ratio:.2f}%')
                print(f'    总的正收益: {plus_val:.2f}')
                print(f'    总的负收益: {minus_val:.2f}')
                
                avg_return = np.mean(returns)
                print(f'    平均收益: {avg_return:.2f}%')
        
        # 正收益统计（对应原始版本的 plus_list）
        if self.plus_list:
            print(f'\n正收益统计:')
            print(f'  次数: {len(self.plus_list)}')
            print(f'  平均值: {np.mean(self.plus_list):.2f}%')
            print(f'  最大值: {np.max(self.plus_list):.2f}%')
            print(f'  最小值: {np.min(self.plus_list):.2f}%')
            print(f'  中位数: {np.median(self.plus_list):.2f}%')
            print(f'  95%分位数: {np.percentile(self.plus_list, 95):.2f}%')
        
        # 负收益统计（对应原始版本的 minus_list）
        if self.minus_list:
            print(f'\n负收益统计:')
            print(f'  次数: {len(self.minus_list)}')
            print(f'  平均值: {np.mean(self.minus_list):.2f}%')
            print(f'  最大值: {np.max(self.minus_list):.2f}%')
            print(f'  最小值: {np.min(self.minus_list):.2f}%')
            print(f'  中位数: {np.median(self.minus_list):.2f}%')
            print(f'  95%分位数: {np.percentile(self.minus_list, 95):.2f}%')
        
        # 总收益统计（对应原始版本的 total_ratio）
        if self.all_returns:
            print(f'\n总收益统计:')
            print(f'  平均值: {np.mean(self.all_returns):.2f}%')
            print(f'  最大值: {np.max(self.all_returns):.2f}%')
            print(f'  最小值: {np.min(self.all_returns):.2f}%')
            print(f'  中位数: {np.median(self.all_returns):.2f}%')
            print(f'  95%分位数: {np.percentile(self.all_returns, 95):.2f}%')
        
        print('='*80)


def run_backtest(symbol, df, start_date='2020-01-01', end_date='2025-12-31',
                 initial_cash=1000000, stake=1000, printlog=False):
    """
    运行 Backtrader 回测
    """
    print(f"\n开始回测 {symbol}")
    
    # 验证数据
    required_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
    for col in required_columns:
        if col not in df.columns:
            print(f"{symbol} 数据缺少 {col} 列，跳过")
            return None
    
    # 准备数据
    df_copy = df.copy()
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_copy.sort_index(inplace=True)
    
    df_filtered = df_copy[start_date:end_date]
    
    if len(df_filtered) < 70:
        print(f"{symbol} 数据不足（{len(df_filtered)}条），跳过")
        return None
    
    # 创建 Cerebro
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
        GoldenLineStrategy,
        symbol=symbol,
        stake=stake,
        hold_days=5,
        threshold=1.7,
        klines=10,
        min_angle=20,
        printlog=printlog
    )
    
    # 设置资金和手续费
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=0.0003)
    
    # 运行回测
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
        'strategy': results[0]
    }


def main():
    """主函数：批量回测"""
    print("="*80)
    print("黄金分割线策略 - Backtrader 批量回测")
    print("="*80)
    
    # 获取股票列表
    try:
        all_symbols = get_daily_symbols()
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        print("使用测试列表...")
        all_symbols = ['000001', '000002', '600000']
    
    start_date = "2020-01-01"
    results = []
    symbol_count = 0
    
    for idx, symbol in enumerate(all_symbols):
        symbol_count += 1
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度: {symbol_count} / {len(all_symbols)}")
        
        try:
            # 获取数据
            df = get_local_stock_data(symbol, start_date)
            if df is None or len(df) < 70:
                print(f"{symbol} 数据不足，跳过")
                continue
            
            # 运行回测
            result = run_backtest(
                symbol=symbol,
                df=df,
                start_date=start_date,
                end_date='2025-12-31',
                initial_cash=100000,
                stake=1000,
                printlog=False
            )
            
            if result:
                results.append(result)
            
            # 每100只股票打印汇总
            if symbol_count % 100 == 0:
                print(f"\n已处理 {symbol_count} 只股票")
                if results:
                    avg_return = np.mean([r['total_return'] for r in results])
                    print(f'平均收益率: {avg_return:.2f}%')
        
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            continue
    
    # 最终统计
    print("\n" + "="*80)
    print("全部回测完成 - 总体统计")
    print("="*80)
    
    if results:
        all_returns = [r['total_return'] for r in results]
        print(f"回测股票数量: {len(results)}")
        print(f"\n收益率统计:")
        print(f"  平均值: {np.mean(all_returns):.2f}%")
        print(f"  中位数: {np.median(all_returns):.2f}%")
        print(f"  最大值: {np.max(all_returns):.2f}%")
        print(f"  最小值: {np.min(all_returns):.2f}%")
        print(f"  标准差: {np.std(all_returns):.2f}%")
        
        positive_count = sum(1 for r in all_returns if r > 0)
        print(f"\n正收益股票占比: {positive_count/len(results)*100:.2f}%")
    else:
        print("没有成功回测的股票数据")
    
    print("\n" + "="*80)


if __name__ == '__main__':
    main()