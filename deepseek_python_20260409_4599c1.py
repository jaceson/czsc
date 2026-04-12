import backtrader as bt
import backtrader.indicators as btind
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# ==================== 导入自定义模块 ====================
try:
    from czsc_daily_util import *
    from lib.MyTT import *
    from czsc_sqlite import get_local_stock_data
except ImportError:
    print("注意：部分模块未找到，将使用基础函数")

class BollingerBands(bt.Indicator):
    """布林带指标"""
    lines = ('mid', 'upper', 'lower', 'mid1', 'lower1')
    params = (('period', 20), ('devfactor', 2))
    
    def __init__(self):
        self.lines.mid = btind.SimpleMovingAverage(self.data.close, period=self.p.period)
        std = btind.StandardDeviation(self.data.close, period=self.p.period)
        self.lines.upper = self.lines.mid + self.p.devfactor * std
        self.lines.lower = self.lines.mid - self.p.devfactor * std
        self.lines.lower1 = self.lines.mid - std  # 1倍标准差下轨


class WaveBottomStrategy(bt.Strategy):
    """
    波段抄底策略 - 完整版（已修复）
    """
    
    def __init__(self):
        # 基础数据
        self.close = self.data.close
        self.low = self.data.low
        self.high = self.data.high
        
        # 参数
        self.period_6 = 6
        self.period_12 = 12
        self.period_24 = 24
        self.period_36 = 36
        self.period_30 = 30
        self.period_27 = 27
        self.period_34 = 34
        
        # 记录信号和持仓
        self.entry_price = 0
        
        # 计算指标
        self.calculate_indicators()
    
    def calculate_indicators(self):
        """计算所有指标"""
        
        # 1. 乖离率计算
        ma6 = btind.SimpleMovingAverage(self.close, period=self.period_6)
        ma12 = btind.SimpleMovingAverage(self.close, period=self.period_12)
        ma24 = btind.SimpleMovingAverage(self.close, period=self.period_24)
        
        bias1 = (self.close - ma6) / ma6 * 100
        bias2 = (self.close - ma12) / ma12 * 100
        bias3 = (self.close - ma24) / ma24 * 100
        
        # 加权平均乖离率
        self.mm = (bias1 + 2 * bias2 + 3 * bias3) / 6
        self.mn = btind.SimpleMovingAverage(self.mm, period=3)
        
        # 2. 价格位置指标
        var24 = btind.Lowest(self.low, period=self.period_36)
        var25 = btind.Highest(self.high, period=self.period_30)
        
        # 避免除零
        range_diff = var25 - var24
        range_diff = btind.Max(0.001, range_diff)
        
        var26_raw = (self.close - var24) / range_diff * 4
        var26_ema = btind.ExponentialMovingAverage(var26_raw, period=4)
        self.var26 = var26_ema * 25
        
        # 3. 布林带指标
        self.boll = BollingerBands(self.data, period=20, devfactor=2)
        
        # 前一周期值
        self.mid_prev = self.boll.mid(-1)
        self.upper_prev = self.boll.upper(-1)
        self.lower_prev = self.boll.lower(-1)
        self.lower1_prev = self.boll.lower1(-1)
        
        # 股价线
        denominator = self.upper_prev - self.lower_prev
        denominator = btind.Max(0.001, denominator)
        self.price_line = (self.close - self.lower1_prev) / denominator * 100
        self.trend_line = btind.SimpleMovingAverage(self.price_line, period=6)
        
        # 4. 准备建仓指标
        abs_l_minus_ref = abs(self.low - self.low(-1))
        max_l_minus_ref = btind.Max(self.low - self.low(-1), 0)
        
        sma_abs = btind.SimpleMovingAverage(abs_l_minus_ref, period=3)
        sma_max = btind.SimpleMovingAverage(max_l_minus_ref, period=3)
        sma_max = btind.Max(0.001, sma_max)
        
        self.varc = sma_abs / sma_max
        
        # 30日最低价条件
        low_30 = btind.Lowest(self.low, period=30)
        condition = self.low <= low_30
        self.varc_condition = btind.If(condition, self.varc, 0)
        self.ready_build = btind.ExponentialMovingAverage(self.varc_condition, period=3)
        
        # 5. 建仓区指标
        var05 = btind.Lowest(self.low, period=27)
        var06 = btind.Highest(self.high, period=34)
        
        range_diff2 = var06 - var05
        range_diff2 = btind.Max(0.001, range_diff2)
        
        var07_raw = (self.close - var05) / range_diff2 * 4
        var07_ema = btind.ExponentialMovingAverage(var07_raw, period=4)
        self.var07 = var07_ema * 25
        
        # 建仓区条件
        self.build_zone = self.var07 < 10
        
        # 6. 乖离金叉信号（修复关键点）
        bias_raw = (bias1 + 2 * bias2 + 3 * bias3) / 6
        bias_ma = btind.SimpleMovingAverage(bias_raw, period=3)
        
        # 金叉条件 - 使用 bt.And 和 btind.CrossOver
        cross_over = btind.CrossOver(bias_raw, bias_ma)
        # 修复：使用 bt.And 来组合条件
        self.buy_signal_condition = bt.And(cross_over == 1, bias_ma < -9)
    
    def next(self):
        """每个bar执行"""
        
        # 获取当前信号值
        mn_value = self.mn[0] if len(self.mn) > 0 else 0
        var26_value = self.var26[0] if len(self.var26) > 0 else 0
        trend_line = self.trend_line[0] if len(self.trend_line) > 0 else 0
        ready_build = self.ready_build[0] if len(self.ready_build) > 0 else 0
        bias_signal = self.buy_signal_condition[0] if len(self.buy_signal_condition) > 0 else 0
        
        # 综合买入条件
        condition1 = mn_value < -4
        condition2 = var26_value < 10
        condition3 = bias_signal == 1  # 修复：确保比较正确
        condition4 = trend_line < 30
        condition5 = ready_build > 0.5
        
        # 计算满足的条件数
        conditions_list = [condition1, condition2, condition3, condition4, condition5]
        buy_conditions = sum(conditions_list)
        
        # 卖出条件
        sell_condition1 = var26_value > 90
        sell_condition2 = trend_line > 80
        sell_condition3 = mn_value > 0
        
        # 仓位管理
        if not self.position:
            if buy_conditions >= 2:
                # 使用30%仓位
                cash = self.broker.getcash()
                size = cash * 0.3 / self.data.close[0]
                self.buy(size=size)
                self.entry_price = self.data.close[0]
                print(f"{self.data.datetime.date(0)} 买入 - 价格: {self.entry_price:.2f}, "
                      f"条件数: {buy_conditions}")
        
        elif self.position:
            if sell_condition1 or sell_condition2 or sell_condition3:
                self.close()
                sell_price = self.data.close[0]
                pnl = (sell_price - self.entry_price) / self.entry_price * 100
                print(f"{self.data.datetime.date(0)} 卖出 - 价格: {sell_price:.2f}, "
                      f"收益率: {pnl:.2f}%")


class WaveBottomStrategyV2(bt.Strategy):
    """
    简化版策略 - 只使用核心买入信号（已修复）
    """
    
    def __init__(self):
        self.close = self.data.close
        self.low = self.data.low
        self.high = self.data.high
        
        # 计算乖离率
        ma6 = btind.SimpleMovingAverage(self.close, period=6)
        ma12 = btind.SimpleMovingAverage(self.close, period=12)
        ma24 = btind.SimpleMovingAverage(self.close, period=24)
        
        bias1 = (self.close - ma6) / ma6 * 100
        bias2 = (self.close - ma12) / ma12 * 100
        bias3 = (self.close - ma24) / ma24 * 100
        
        bias_raw = (bias1 + 2 * bias2 + 3 * bias3) / 6
        bias_ma = btind.SimpleMovingAverage(bias_raw, period=3)
        
        # 修复：使用 bt.And 来组合条件，而不是直接用 &
        cross_up = btind.CrossOver(bias_raw, bias_ma)
        self.buy_signal = bt.And(cross_up == 1, bias_ma < -9)
        
        # 布林带位置
        boll = BollingerBands(self.data, period=20, devfactor=2)
        lower1_prev = boll.lower1(-1)
        upper_prev = boll.upper(-1)
        
        denominator = upper_prev - lower1_prev
        denominator = btind.Max(0.001, denominator)
        price_line = (self.close - lower1_prev) / denominator * 100
        trend_line = btind.SimpleMovingAverage(price_line, period=6)
        
        # 卖出信号
        self.sell_signal = trend_line > 80
        
        # 记录买入价格
        self.entry_price = 0
        
    def next(self):
        # 买入逻辑
        if not self.position and self.buy_signal[0] == 1:
            cash = self.broker.getcash()
            size = cash * 0.3 / self.data.close[0]
            if size > 0:
                self.buy(size=size)
                self.entry_price = self.data.close[0]
                print(f"{self.data.datetime.date(0)} 买入 - 价格: {self.data.close[0]:.2f}")
        
        # 卖出逻辑
        elif self.position and self.sell_signal[0] == 1:
            self.close()
            sell_price = self.data.close[0]
            pnl = (sell_price - self.entry_price) / self.entry_price * 100
            print(f"{self.data.datetime.date(0)} 卖出 - 价格: {sell_price:.2f}, 收益率: {pnl:.2f}%")


def run_backtest(symbol='sh.600000', start_date='2020-01-01', 
                 end_date='2024-12-31', strategy=WaveBottomStrategyV2, 
                 initial_cash=100000, commission=0.0003):
    """
    运行回测
    
    参数:
    - symbol: 股票代码 (如 'sh.600000')
    - start_date: 开始日期
    - end_date: 结束日期
    - strategy: 策略类
    - initial_cash: 初始资金
    - commission: 手续费率
    """
    
    # 从本地数据库获取数据
    print(f"正在从本地数据库获取 {symbol} 的数据...")
    try:
        # 尝试导入并获取数据
        from czsc_sqlite import get_local_stock_data
        df = get_local_stock_data(symbol, start_date)
        
        if df is None or len(df) == 0:
            print(f"警告：无法获取 {symbol} 的数据，生成模拟数据...")
            raise Exception("No data")
        
        # 确保列名正确
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        df_columns = [col.lower() for col in df.columns]
        
        # 检查并重命名列
        if 'date' not in df_columns:
            if 'trade_date' in df_columns:
                df.rename(columns={'trade_date': 'date'}, inplace=True)
            elif 'datetime' in df_columns:
                df.rename(columns={'datetime': 'date'}, inplace=True)
        
        # 设置日期为索引
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
        
        df = df.sort_index()
        
        # 过滤日期范围
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        
        print(f"成功获取数据: {len(df)} 条记录 ({start_date} 至 {end_date})")
        
    except Exception as e:
        print(f"获取数据失败: {e}")
        print("生成模拟数据...")
        dates = pd.date_range(start=start_date, end=end_date, freq='B')  # 工作日
        np.random.seed(42)
        price = 10  # 起始价格设为10元
        prices = [price]
        for i in range(1, len(dates)):
            change = np.random.randn() * 2
            price = price * (1 + change / 100)
            prices.append(price)
        
        df = pd.DataFrame({
            'open': prices,
            'high': np.array(prices) * (1 + np.abs(np.random.randn(len(prices)) * 0.01)),
            'low': np.array(prices) * (1 - np.abs(np.random.randn(len(prices)) * 0.01)),
            'close': prices,
            'volume': np.random.randint(100000, 1000000, len(dates))
        }, index=dates)
    
    # 确保数据完整
    df = df.sort_index()
    df = df[(df.index >= start_date) & (df.index <= end_date)]
    
    if len(df) == 0:
        print("错误：没有有效的回测数据")
        return None
    
    # 创建Cerebro引擎
    cerebro = bt.Cerebro()
    
    # 添加数据
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(strategy)
    
    # 设置初始资金
    cerebro.broker.setcash(initial_cash)
    
    # 设置手续费
    cerebro.broker.setcommission(commission=commission)
    
    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', riskfreerate=0.03)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # 打印初始资金
    print(f'初始资金: {cerebro.broker.getvalue():.2f}')
    
    # 运行回测
    try:
        results = cerebro.run()
    except Exception as e:
        print(f"回测运行出错: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # 获取分析结果
    strat = results[0]
    
    # 打印详细结果
    print('\n' + '='*50)
    print('回测结果统计')
    print('='*50)
    
    # 最终资金
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100
    print(f"最终资金: {final_value:.2f}")
    print(f"总收益: {final_value - initial_cash:.2f}")
    print(f"总收益率: {total_return:.2f}%")
    
    # 收益率
    try:
        returns = strat.analyzers.returns.get_analysis()
        print(f"年化收益率: {returns.get('rnorm100', 0):.2f}%")
    except:
        print("年化收益率: 无法计算")
    
    # 夏普比率
    try:
        sharpe = strat.analyzers.sharpe.get_analysis()
        print(f"夏普比率: {sharpe.get('sharperatio', 0):.2f}")
    except:
        print("夏普比率: 无法计算")
    
    # 最大回撤
    try:
        drawdown = strat.analyzers.drawdown.get_analysis()
        print(f"最大回撤: {drawdown.max.drawdown:.2f}%")
    except:
        print("最大回撤: 无法计算")
    
    # 交易统计
    try:
        trades = strat.analyzers.trades.get_analysis()
        total_trades = getattr(trades.total, 'total', 0) if hasattr(trades, 'total') else 0
        won_trades = getattr(trades.won, 'total', 0) if hasattr(trades, 'won') else 0
        lost_trades = getattr(trades.lost, 'total', 0) if hasattr(trades, 'lost') else 0
        
        print(f"\n交易统计:")
        print(f"总交易次数: {total_trades}")
        print(f"盈利次数: {won_trades}")
        print(f"亏损次数: {lost_trades}")
        if total_trades > 0:
            print(f"胜率: {won_trades/total_trades*100:.2f}%")
    except:
        print("\n交易统计: 无法计算")
    
    # 尝试绘制结果
    try:
        cerebro.plot(style='candlestick', volume=False)
    except:
        print("图表绘制失败")
    
    return results


if __name__ == "__main__":
    # 运行回测
    print("="*60)
    print("波段抄底策略回测系统")
    print("="*60)
    
    # 使用简化版策略（已修复）
    run_backtest(
        symbol='sh.600000',  # 浦发银行
        start_date='2020-01-01',
        end_date='2024-12-31',
        strategy=WaveBottomStrategyV2,  # 使用简化版
        initial_cash=100000,
        commission=0.0003
    )