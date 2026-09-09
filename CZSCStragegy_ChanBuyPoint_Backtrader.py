# coding: utf-8
"""
缠论一二三买点策略 - Backtrader 回测版本

策略核心：
1. 参考 czsc_daily_util.get_chan_buy_point_type 使用 CChan 识别一二三买点（T1/T1P/T2/T2S/T3A/T3B）
2. 出现买点信号后，第二天开盘价买入
3. 持有周期最长 5 天
4. 收益率达到 5% 止盈卖出
"""
import os
import sys
import pandas as pd
import numpy as np
import backtrader as bt
from collections import defaultdict
from datetime import datetime as dt, timedelta

from czsc_daily_util import get_kl_data, get_daily_symbols, get_latest_trade_date, czsc_logger
from czsc_sqlite import get_local_stock_data
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import BSP_TYPE, KL_TYPE, AUTYPE

# 买点类型名称映射
buy_type_config = {
    '1': '一买',
    '1p': '一买(强)',
    '2': '二买',
    '2s': '二买(强)',
    '3a': '三买',
    '3b': '三买',
}

# 买点类型优先级（与 get_chan_buy_point_type 一致）
BUY_TYPE_PRIORITY = [BSP_TYPE.T3B, BSP_TYPE.T3A, BSP_TYPE.T2S, BSP_TYPE.T2, BSP_TYPE.T1P, BSP_TYPE.T1]


def precompute_signals(symbol, df):
    """参考 czsc_daily_util.get_chan_buy_point_type 使用 CChan 预计算所有一二三买点信号

    返回: {信号日期('YYYY-MM-DD'): 买点类型('1'/'1p'/'2'/'2s'/'3a'/'3b')}
    """
    if df is None or len(df) < 70:
        return {}

    # 本地数据库存在重复日期的行，去重保证K线唯一
    df = df.drop_duplicates(subset='date', keep='first')

    # 缠论分析配置
    config = CChanConfig({
        "trigger_step": True,
        "divergence_rate": 0.8,
        "min_zs_cnt": 1,
    })

    # 缠论分析（trigger_load 方式喂数据，不依赖数据源）
    chan = CChan(
        code=symbol,
        lv_list=[KL_TYPE.K_DAY],
        config=config,
        autype=AUTYPE.QFQ,
    )

    signals = {}
    trade_date_list = []

    try:
        for klu in get_kl_data(df):  # 获取单根K线
            chan.trigger_load({KL_TYPE.K_DAY: [klu]})  # 喂给CChan新增k线
            bsp_list = chan.get_bsp()
            if not bsp_list:
                continue
            last_bsp = bsp_list[-1]
            if not last_bsp.is_buy:
                continue
            trade_date = last_bsp.klu.time.toDateStr("-")
            if trade_date in trade_date_list:
                continue
            trade_date_list.append(trade_date)

            # 买卖点类型（优先级与 get_chan_buy_point_type 一致）
            buy_type = None
            for btype in BUY_TYPE_PRIORITY:
                if btype in last_bsp.type:
                    buy_type = btype
                    break
            if buy_type is None:
                continue

            signals[trade_date] = buy_type.value.lower()

    except Exception as e:
        czsc_logger().info(f'{symbol} 缠论信号计算异常: {e}')

    return signals


class ChanBuyPointBacktraderStrategy(bt.Strategy):
    """
    缠论一二三买点策略

    参数:
        symbol: 股票代码
        signal_dict: 预计算的买点信号 {日期: 买点类型}
        take_profit_pct: 止盈百分比，默认5（%）
        max_hold_days: 最大持有天数，默认5
        stake: 每次买入金额，默认40000元
        printlog: 是否打印日志，默认True
    """

    params = (
        ('symbol', ''),
        ('signal_dict', {}),
        ('take_profit_pct', 5.0),
        ('max_hold_days', 5),
        ('stake', 40000),
        ('printlog', True),
    )

    def __init__(self):
        self.order = None
        self.position_open = False

        # 买入信息
        self.buy_type = None
        self.buy_signal_date = None
        self.buy_date = None
        self.buy_price = 0
        self.buy_size = 0
        self.buy_bar = 0
        self.sell_reason = None

        # 统计变量
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.total_profit = 0
        self.total_loss = 0
        self.take_profit_count = 0
        self.timeout_count = 0
        self.all_returns = []

        # 交易记录
        self.trade_records = []
        self.current_trade = None

        # 买点类型统计
        self.buy_type_stats = defaultdict(lambda: {'total': 0, 'win': 0, 'loss': 0, 'returns': [], 'profit': 0, 'loss_amt': 0})

    def get_type_name(self, buy_type):
        return buy_type_config.get(buy_type, buy_type)

    def _log(self, msg):
        if self.params.printlog:
            print(f'{dt.now().strftime("%Y-%m-%d %H:%M:%S")} - {msg}')

    def next(self):
        """主逻辑：每个bar执行"""
        if self.order:
            return

        if self.position:
            self._check_exit()
        else:
            self._check_buy_signal()

    def _check_buy_signal(self):
        """检查买点信号"""
        current_date = self.data.datetime.date(0).strftime("%Y-%m-%d")
        buy_type = self.params.signal_dict.get(current_date)
        if not buy_type:
            return

        price = self.data.close[0]
        size = self._calculate_size(price)
        if size <= 0:
            return

        if self.broker.getcash() < price * size * 1.003:
            self._log(f'资金不足: 可用{self.broker.getcash():.2f}, 需要{price * size:.2f}')
            return

        self.buy_type = buy_type
        self.buy_signal_date = current_date
        self.sell_reason = None

        self._log(f'【买入信号-{self.get_type_name(buy_type)}】日期: {current_date}, '
                  f'参考价: {price:.2f}, 数量: {size}')
        self.order = self.buy(size=size)

    def _check_exit(self):
        """检查止盈/持有期满卖出条件"""
        current_price = self.data.close[0]
        profit_pct = (current_price - self.buy_price) / self.buy_price * 100 if self.buy_price > 0 else 0
        bars_held = len(self) - self.buy_bar

        # 止盈：收益率 >= take_profit_pct
        if profit_pct >= self.params.take_profit_pct:
            self.sell_reason = f'止盈_{profit_pct:.2f}%'
            self._log(f'【止盈信号】收益: {profit_pct:.2f}%, 达到止盈线 {self.params.take_profit_pct}%')
            self.order = self.close()
            return

        # 持有期满：持有 max_hold_days 天
        if bars_held >= self.params.max_hold_days:
            self.sell_reason = f'持有期满_{bars_held}天'
            self._log(f'【超时卖出】持有: {bars_held}天, 超过 {self.params.max_hold_days} 天')
            self.order = self.close()
            return

    def _calculate_size(self, price):
        """根据金额计算可买数量（按100股取整）"""
        if price <= 0:
            return 0
        size = int(self.params.stake / price / 100) * 100
        if size == 0 and self.params.stake >= price:
            size = 100
        return size

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                exec_price = order.executed.price
                exec_size = order.executed.size
                exec_date = self.data.datetime.date(0)

                self.buy_price = exec_price
                self.buy_size = exec_size
                self.buy_date = str(exec_date)
                self.buy_bar = len(self)
                self.position_open = True
                self.trade_count += 1

                self._log(f'【买入成交】日期: {self.buy_date}, '
                          f'价格: {exec_price:.2f}, 数量: {exec_size}, 类型: {self.get_type_name(self.buy_type)}')

                # 记录交易
                self.current_trade = {
                    'signal_date': self.buy_signal_date,
                    'buy_date': self.buy_date,
                    'buy_price': exec_price,
                    'buy_size': exec_size,
                    'buy_type': self.buy_type,
                    'sell_date': None,
                    'sell_price': None,
                    'profit_pct': None,
                    'profit_amount': None,
                    'hold_days': None,
                    'sell_reason': None,
                }

                # 买点类型统计
                self.buy_type_stats[self.buy_type]['total'] += 1

            else:
                # 卖出成交
                sell_price = order.executed.price
                sell_size = abs(order.size)
                sell_date = self.data.datetime.date(0)

                # 计算收益
                profit_amount = (sell_price - self.buy_price) * sell_size
                profit_pct = (sell_price - self.buy_price) / self.buy_price * 100 if self.buy_price > 0 else 0
                bars_held = len(self) - self.buy_bar

                # 更新统计
                if profit_amount > 0:
                    self.win_count += 1
                    self.total_profit += profit_amount
                else:
                    self.loss_count += 1
                    self.total_loss += abs(profit_amount)

                # 买点类型统计
                stats = self.buy_type_stats[self.buy_type]
                stats['returns'].append(profit_pct)
                if profit_amount > 0:
                    stats['win'] += 1
                    stats['profit'] += profit_amount
                else:
                    stats['loss'] += 1
                    stats['loss_amt'] += abs(profit_amount)

                self.all_returns.append(profit_pct)

                # 卖出原因统计
                if self.sell_reason and self.sell_reason.startswith('止盈'):
                    self.take_profit_count += 1
                elif self.sell_reason and self.sell_reason.startswith('持有期满'):
                    self.timeout_count += 1

                self._log(f'【卖出成交】日期: {sell_date}, 卖出价: {sell_price:.2f}, 成本: {self.buy_price:.2f}, '
                          f'收益: {profit_pct:+.2f}% ({profit_amount:+.2f}元), 持有: {bars_held}天, '
                          f'原因: {self.sell_reason}')

                # 保存交易记录
                if self.current_trade:
                    self.current_trade['sell_date'] = str(sell_date)
                    self.current_trade['sell_price'] = sell_price
                    self.current_trade['profit_pct'] = profit_pct
                    self.current_trade['profit_amount'] = profit_amount
                    self.current_trade['hold_days'] = bars_held
                    self.current_trade['sell_reason'] = self.sell_reason
                    self.trade_records.append(self.current_trade.copy())

                self.current_trade = None
                self.position_open = False
                self.buy_price = 0
                self.buy_size = 0
                self.buy_type = None
                self.buy_signal_date = None

        elif order.status in [order.Rejected, order.Margin, order.Canceled]:
            self._log(f'订单失败: {order.getstatusname()}')

        if not order.alive():
            self.order = None

    def stop(self):
        """策略结束时的统计"""
        if self.params.printlog:
            self._print_statistics()

    def _print_statistics(self):
        """打印统计信息"""
        print('\n' + '=' * 80)
        print(f'缠论一二三买点策略 - 回测统计 ({self.params.symbol})')
        print('=' * 80)

        print(f'\n【交易统计】')
        print(f'  总交易次数: {self.trade_count}')
        if self.trade_count > 0:
            win_rate = self.win_count / self.trade_count * 100
            print(f'  胜率: {win_rate:.2f}% ({self.win_count}/{self.trade_count})')
            print(f'  止盈次数: {self.take_profit_count}')
            print(f'  持有期满次数: {self.timeout_count}')
            print(f'  总盈利: {self.total_profit:.2f}')
            print(f'  总亏损: {self.total_loss:.2f}')
            net_profit = self.total_profit - self.total_loss
            print(f'  净收益: {net_profit:.2f}')
            if len(self.all_returns) > 0:
                print(f'  平均每笔收益: {np.mean(self.all_returns):.2f}%')

        print(f'\n【买点类型统计】')
        for buy_type in buy_type_config.keys():
            stats = self.buy_type_stats.get(buy_type, {'total': 0, 'win': 0, 'returns': [], 'profit': 0, 'loss_amt': 0})
            if stats['total'] > 0:
                type_name = buy_type_config[buy_type]
                win_rate = stats['win'] / stats['total'] * 100
                avg_return = np.mean(stats['returns']) if stats['returns'] else 0
                net_profit = stats['profit'] - stats['loss_amt']
                print(f'  {type_name}: 次数={stats["total"]}, 胜率={win_rate:.2f}%, '
                      f'平均收益={avg_return:.2f}%, 盈利={stats["profit"]:.2f}, '
                      f'亏损={stats["loss_amt"]:.2f}, 净收益={net_profit:.2f}')

        self._print_trade_details()
        print('=' * 80)

    def _print_trade_details(self):
        """打印交易明细"""
        if not self.trade_records:
            print('\n暂无交易记录')
            return

        print('\n' + '=' * 120)
        print('交易明细')
        print('=' * 120)

        header = f"{'序号':<4} {'买入日期':<12} {'买入价':<8} {'买点':<8} {'卖出日期':<12} {'卖出价':<8} {'收益率':<10} {'持有天数':<6} {'卖出原因':<18}"
        print(header)
        print('-' * 130)

        for idx, trade in enumerate(self.trade_records, 1):
            buy_date = trade.get('buy_date', '')
            buy_price = f"{trade.get('buy_price', 0):.2f}"
            buy_type_name = buy_type_config.get(trade.get('buy_type'), '')
            sell_date = trade.get('sell_date', '')
            sell_price = f"{trade.get('sell_price', 0):.2f}"
            profit_pct = f"{trade.get('profit_pct', 0):+.2f}%"
            hold_days = trade.get('hold_days', 0)
            sell_reason = trade.get('sell_reason', '')[:16]

            row = f"{idx:<4} {str(buy_date):<12} {buy_price:<8} {buy_type_name:<8} {str(sell_date):<12} {sell_price:<8} {profit_pct:<10} {hold_days:<6} {sell_reason:<18}"
            print(row)

        print('=' * 120)


def run_backtest(symbol, df, start_date=None, end_date=None,
                 initial_cash=1000000, stake=40000, take_profit_pct=5.0,
                 max_hold_days=5, printlog=True):
    """运行Backtrader回测（单只股票）"""
    if df is None or len(df) < 70:
        print(f"{symbol} 数据不足，跳过")
        return None

    # 预计算缠论一二三买点信号
    signals = precompute_signals(symbol, df)
    if not signals:
        print(f"{symbol} 未检测到买点信号，跳过")
        return None

    # 数据预处理（去重保证K线唯一）
    df_copy = df.copy()
    df_copy = df_copy.drop_duplicates(subset='date', keep='first')
    df_copy['datetime'] = pd.to_datetime(df_copy['date'])
    df_copy.set_index('datetime', inplace=True)
    df_copy.sort_index(inplace=True)

    # 过滤回测日期范围（信号基于全量历史计算，仅交易限制在回测区间）
    df_filtered = df_copy
    if start_date:
        df_filtered = df_filtered[df_filtered.index >= start_date]
    if end_date:
        df_filtered = df_filtered[df_filtered.index <= end_date]

    if len(df_filtered) < 50:
        print(f"{symbol} 回测区间数据不足（{len(df_filtered)}条），跳过")
        return None

    # 只保留回测区间内的信号，避免暖机阶段的信号提前触发
    trade_signals = {d: t for d, t in signals.items()
                     if (start_date is None or d >= start_date) and (end_date is None or d <= end_date)}

    if not trade_signals:
        print(f"{symbol} 回测区间内未检测到买点信号，跳过")
        return None

    # 创建Cerebro
    cerebro = bt.Cerebro()

    # 添加数据
    data = bt.feeds.PandasData(
        dataname=df_filtered[['open', 'high', 'low', 'close', 'volume']],
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
        ChanBuyPointBacktraderStrategy,
        symbol=symbol,
        signal_dict=trade_signals,
        take_profit_pct=take_profit_pct,
        max_hold_days=max_hold_days,
        stake=stake,
        printlog=printlog,
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

    print(f'{symbol} 回测完成 | 初始化资金: {initial_cash:,.2f} | '
          f'最终资金: {final_value:,.2f} | 收益率: {total_return:.2f}% | '
          f'交易次数: {strategy.trade_count} | 信号数: {len(trade_signals)}')

    return {
        'symbol': symbol,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': total_return,
        'trade_count': strategy.trade_count,
        'win_count': strategy.win_count,
        'loss_count': strategy.loss_count,
        'total_profit': strategy.total_profit,
        'total_loss': strategy.total_loss,
        'take_profit_count': strategy.take_profit_count,
        'timeout_count': strategy.timeout_count,
        'signal_count': len(trade_signals),
        'buy_type_stats': dict(strategy.buy_type_stats),
        'strategy': strategy,
    }


def batch_backtest(all_symbols, start_date='2022-01-01', end_date='2023-01-01',
                   initial_cash=1000000, stake=40000, take_profit_pct=5.0,
                   max_hold_days=5, printlog=False, warmup_days=400):
    """批量回测（使用本地数据，带暖机历史用于缠论信号计算）"""
    results = []

    for idx, symbol in enumerate(all_symbols):
        print(f"\n[{dt.now().strftime('%Y-%m-%d %H:%M:%S')}] "
              f"进度: {idx + 1} / {len(all_symbols)} - {symbol}")

        try:
            # 本地数据（包含暖机区间，信号基于全量历史计算，交易限制在回测区间）
            data_start = (dt.strptime(start_date, "%Y-%m-%d") - timedelta(days=warmup_days)).strftime("%Y-%m-%d")
            df = get_local_stock_data(symbol, data_start, end_date)

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
                take_profit_pct=take_profit_pct,
                max_hold_days=max_hold_days,
                printlog=printlog,
            )

            if result:
                results.append(result)

            # 每50只打印一次汇总
            if (idx + 1) % 50 == 0:
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
    total_profit = sum(r.get('total_profit', 0) for r in results)
    total_loss = sum(r.get('total_loss', 0) for r in results)
    total_signals = sum(r.get('signal_count', 0) for r in results)

    print("\n" + "=" * 80)
    if final:
        print("【最终汇总】批量回测统计")
    else:
        print("【阶段性汇总】")
    print("=" * 80)

    print(f"\n股票统计:")
    print(f"  成功回测股票数: {len(results)}")
    print(f"  平均收益率: {np.mean(all_returns):.2f}%")
    print(f"  中位数收益率: {np.median(all_returns):.2f}%")
    print(f"  最大收益率: {np.max(all_returns):.2f}%")
    print(f"  最小收益率: {np.min(all_returns):.2f}%")
    print(f"  正收益股票占比: {sum(1 for r in all_returns if r > 0) / len(results) * 100:.2f}%")

    print(f"\n信号/交易统计:")
    print(f"  总信号数: {total_signals}")
    print(f"  总交易次数: {total_trades}")
    if total_trades > 0:
        print(f"  总胜率: {total_wins / total_trades * 100:.2f}%")
    print(f"  总盈利金额: {total_profit:,.2f} 元")
    print(f"  总亏损金额: {total_loss:,.2f} 元")
    print(f"  净收益: {total_profit - total_loss:,.2f} 元")

    # 买点类型统计
    buy_type_stats = {k: {'total': 0, 'win': 0, 'profit': 0, 'loss_amt': 0} for k in buy_type_config}
    for r in results:
        for bt_type, stats in r.get('buy_type_stats', {}).items():
            if bt_type in buy_type_stats:
                buy_type_stats[bt_type]['total'] += stats.get('total', 0)
                buy_type_stats[bt_type]['win'] += stats.get('win', 0)
                buy_type_stats[bt_type]['profit'] += stats.get('profit', 0)
                buy_type_stats[bt_type]['loss_amt'] += stats.get('loss_amt', 0)

    print(f"\n买点类型统计:")
    for bt_type, stats in buy_type_stats.items():
        if stats['total'] > 0:
            type_name = buy_type_config[bt_type]
            win_rate = stats['win'] / stats['total'] * 100
            net_profit = stats['profit'] - stats['loss_amt']
            print(f"  {type_name}: 次数={stats['total']}, 胜率={win_rate:.2f}%, "
                  f"盈利={stats['profit']:,.2f}, 亏损={stats['loss_amt']:,.2f}, 净收益={net_profit:,.2f}")

    print("=" * 80 + "\n")


def main():
    """主函数"""
    print("=" * 80)
    print("缠论一二三买点策略 - Backtrader 批量回测")
    print("=" * 80)

    # 配置参数
    START_DATE = "2020-01-01"
    END_DATE = "2026-01-01"
    INITIAL_CASH = 1000000
    STAKE = 40000
    TAKE_PROFIT_PCT = 10.0
    MAX_HOLD_DAYS = 20
    PRINTLOG = False
    WARMUP_DAYS = 400

    # 支持单只股票测试: python CZSCStragegy_ChanBuyPoint_Backtrader.py sh.600036
    if len(sys.argv) > 1:
        symbol = sys.argv[1]
        end_date = get_latest_trade_date()
        start_date = "2022-01-01"
        data_start = (dt.strptime(start_date, "%Y-%m-%d") - timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
        df = get_local_stock_data(symbol, data_start, end_date)
        run_backtest(
            symbol=symbol,
            df=df,
            start_date=start_date,
            end_date=end_date,
            initial_cash=INITIAL_CASH,
            stake=STAKE,
            take_profit_pct=TAKE_PROFIT_PCT,
            max_hold_days=MAX_HOLD_DAYS,
            printlog=True,
        )
        return

    try:
        # 获取股票列表
        all_symbols = get_daily_symbols()
        print(f"获取到 {len(all_symbols)} 只股票")
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        # 使用测试列表
        all_symbols = ['sh.600000', 'sh.600036', 'sz.000001', 'sz.000002']

    # 运行批量回测
    batch_backtest(
        all_symbols=all_symbols,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_cash=INITIAL_CASH,
        stake=STAKE,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_hold_days=MAX_HOLD_DAYS,
        printlog=PRINTLOG,
        warmup_days=WARMUP_DAYS,
    )


if __name__ == '__main__':
    main()