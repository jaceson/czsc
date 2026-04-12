#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
神奇九转策略回测脚本
功能：实现TD序列的买入/卖出信号识别，并进行策略回测
作者：AI Assistant
日期：2026-04-11
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# ==================== 导入自定义模块 ====================
try:
    from czsc_daily_util import *
    from lib.MyTT import *
    from czsc_sqlite import get_local_stock_data
except ImportError:
    print("注意：部分模块未找到，将使用基础函数")

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def get_data_from_local(symbol='sh.600000', start_date='2020-01-01', end_date='2023-12-31'):
    """
    从本地数据库获取股票数据
    
    参数：
        symbol: 股票代码 (如 'sh.600000')
        start_date: 开始日期
        end_date: 结束日期
    """
    try:
        print(f"正在从本地数据库获取 {symbol} 的数据...")
        df = get_local_stock_data(symbol, start_date)
        
        if df is None or len(df) == 0:
            print(f"警告：无法获取 {symbol} 的数据，生成模拟数据...")
            raise Exception("No data")
        
        # 确保列名正确
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        if not all(col in df.columns for col in required_columns):
            print(f"警告：数据列不完整，当前列: {df.columns.tolist()}")
            raise Exception("Invalid columns")
        
        # 设置日期为索引
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        df = df.sort_index()
        
        # 过滤日期范围
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        
        # 重命名列以匹配后续代码
        df.rename(columns={'volume': 'vol'}, inplace=True)
        
        print(f"成功获取数据: {len(df)} 条记录 ({start_date} 至 {end_date})")
        return df
        
    except Exception as e:
        print(f"获取数据失败: {e}")
        print("将使用模拟数据进行演示...")
        return generate_sample_data(start_date, end_date)


def generate_sample_data(start_date='2020-01-01', end_date='2023-12-31'):
    """
    生成模拟数据（当无法获取真实数据时使用）
    """
    date_range = pd.date_range(start=start_date, end=end_date, freq='D')
    # 过滤掉周末（简单处理，只保留工作日）
    date_range = date_range[date_range.weekday < 5]
    
    n = len(date_range)
    
    # 生成模拟价格数据（带趋势和波动）
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.015, n)  # 日均收益0.05%，波动1.5%
    price = 3000 * np.exp(np.cumsum(returns))
    
    # 生成OHLC数据
    df = pd.DataFrame({
        'open': price * (1 + np.random.normal(0, 0.005, n)),
        'high': price * (1 + np.abs(np.random.normal(0.01, 0.005, n))),
        'low': price * (1 - np.abs(np.random.normal(0.01, 0.005, n))),
        'close': price,
        'vol': np.random.randint(1000000, 10000000, n)
    }, index=date_range)
    
    # 确保high是最高价，low是最低价
    df['high'] = df[['open', 'high', 'close']].max(axis=1)
    df['low'] = df[['open', 'low', 'close']].min(axis=1)
    
    print(f"生成模拟数据完成，共{len(df)}条记录")
    return df


def calculate_nine_turn(df):
    """
    计算神奇九转序列（TD序列）
    
    买入结构：收盘价 < 4天前的收盘价
    卖出结构：收盘价 > 4天前的收盘价
    """
    # 初始化列
    df['buy_count'] = 0      # 买入结构计数 (1-9)
    df['sell_count'] = 0     # 卖出结构计数 (1-9)
    df['buy_signal'] = False  # 低9买入信号
    df['sell_signal'] = False # 高9卖出信号
    df['td_setup'] = 0       # TD序列状态：-1下跌结构，1上涨结构，0无结构
    
    # 需要从第5根K线开始，因为需要对比前第4根的价格
    for i in range(4, len(df)):
        # 买入结构（下跌结构）: 收盘价 < 4天前的收盘价
        if df['close'].iloc[i] < df['close'].iloc[i-4]:
            # 如果前一天也在计数中，则递增；否则重新开始计数
            if df['buy_count'].iloc[i-1] > 0:
                df.loc[df.index[i], 'buy_count'] = df['buy_count'].iloc[i-1] + 1
            else:
                df.loc[df.index[i], 'buy_count'] = 1
            df.loc[df.index[i], 'td_setup'] = -1
        else:
            df.loc[df.index[i], 'buy_count'] = 0  # 中断，计数归零
        
        # 卖出结构（上涨结构）: 收盘价 > 4天前的收盘价
        if df['close'].iloc[i] > df['close'].iloc[i-4]:
            if df['sell_count'].iloc[i-1] > 0:
                df.loc[df.index[i], 'sell_count'] = df['sell_count'].iloc[i-1] + 1
            else:
                df.loc[df.index[i], 'sell_count'] = 1
            df.loc[df.index[i], 'td_setup'] = 1
        else:
            df.loc[df.index[i], 'sell_count'] = 0
        
        # 标记完整的9转信号 (计数达到9)
        if df['buy_count'].iloc[i] == 9:
            df.loc[df.index[i], 'buy_signal'] = True
        if df['sell_count'].iloc[i] == 9:
            df.loc[df.index[i], 'sell_signal'] = True
    
    return df


def run_backtest(df, commission_rate=0.00025, slippage=0.001):
    """
    执行回测逻辑
    
    参数：
        commission_rate: 佣金费率（默认万分之2.5）
        slippage: 滑点（默认0.1%）
    """
    df['position'] = 0      # 持仓标记，1表示持有，0表示空仓
    df['returns'] = 0.0     # 策略日收益率
    df['trade_log'] = ''    # 交易记录
    
    position = 0            # 当前持仓状态
    buy_price = 0           # 买入价格
    trade_count = 0         # 交易次数
    
    for i in range(1, len(df)):
        # 买入逻辑：有买入信号 且 当前无持仓
        if df['buy_signal'].iloc[i-1] and position == 0:
            position = 1
            buy_price = df['open'].iloc[i] * (1 + slippage)  # 考虑滑点
            df.loc[df.index[i], 'position'] = position
            df.loc[df.index[i], 'trade_log'] = f"买入 @ {buy_price:.2f}"
            trade_count += 1
        
        # 卖出逻辑：有卖出信号 且 当前有持仓
        elif df['sell_signal'].iloc[i-1] and position == 1:
            position = 0
            sell_price = df['open'].iloc[i] * (1 - slippage)  # 考虑滑点
            # 计算这次交易的收益率（扣除佣金）
            ret = (sell_price - buy_price) / buy_price - commission_rate * 2
            df.loc[df.index[i], 'returns'] = ret
            df.loc[df.index[i], 'position'] = position
            df.loc[df.index[i], 'trade_log'] = f"卖出 @ {sell_price:.2f}, 收益率: {ret:.2%}"
        
        # 持仓中，每日收益率跟随标的涨跌
        elif position == 1:
            df.loc[df.index[i], 'position'] = 1
            # 当日持有收益
            daily_ret = (df['close'].iloc[i] - df['close'].iloc[i-1]) / df['close'].iloc[i-1]
            df.loc[df.index[i], 'returns'] = daily_ret
    
    # 计算策略的累计收益率
    df['cum_strategy_ret'] = (1 + df['returns']).cumprod()
    # 计算买入持有策略的累计收益率作为基准
    df['cum_benchmark_ret'] = df['close'] / df['close'].iloc[0]
    
    # 计算策略净值曲线
    df['strategy_nav'] = df['cum_strategy_ret'] * 100  # 初始净值100
    
    print(f"交易次数: {trade_count}")
    
    return df, trade_count


def calculate_performance_metrics(df, trade_count):
    """
    计算绩效指标
    """
    # 总收益率
    total_return = df['cum_strategy_ret'].iloc[-1] - 1
    benchmark_return = df['cum_benchmark_ret'].iloc[-1] - 1
    
    # 年化收益率（按252个交易日计算）
    trading_days = len(df)
    years = trading_days / 252
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    benchmark_annual_return = (1 + benchmark_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 最大回撤
    cumulative = df['cum_strategy_ret']
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = drawdown.min()
    
    # 夏普比率（假设无风险利率为3%）
    risk_free_rate = 0.03
    excess_returns = df['returns'] - risk_free_rate / 252
    sharpe_ratio = np.sqrt(252) * excess_returns.mean() / excess_returns.std() if excess_returns.std() > 0 else 0
    
    # 胜率（正收益交易占比）
    trade_returns = df[df['trade_log'].str.contains('卖出', na=False)]['returns']
    win_rate = (trade_returns > 0).sum() / len(trade_returns) if len(trade_returns) > 0 else 0
    
    metrics = {
        '策略总收益率': f"{total_return:.2%}",
        '基准总收益率': f"{benchmark_return:.2%}",
        '超额收益': f"{(total_return - benchmark_return):.2%}",
        '年化收益率': f"{annual_return:.2%}",
        '基准年化收益率': f"{benchmark_annual_return:.2%}",
        '最大回撤': f"{max_drawdown:.2%}",
        '夏普比率': f"{sharpe_ratio:.2f}",
        '胜率': f"{win_rate:.2%}",
        '交易次数': trade_count
    }
    
    return metrics


def plot_results(df):
    """
    绘制回测结果图表
    """
    fig, axes = plt.subplots(3, 1, figsize=(14, 10))
    
    # 图1：收益曲线对比
    ax1 = axes[0]
    ax1.plot(df.index, df['cum_benchmark_ret'], label='买入持有策略 (基准)', 
             color='blue', alpha=0.6, linewidth=1.5)
    ax1.plot(df.index, df['cum_strategy_ret'], label='神奇九转策略', 
             color='red', linewidth=1.5)
    
    # 标记买入点
    buy_points = df[df['buy_signal'] == True]
    if len(buy_points) > 0:
        ax1.scatter(buy_points.index, df.loc[buy_points.index, 'cum_strategy_ret'], 
                   marker='^', color='green', s=80, label=f'买入信号 ({len(buy_points)}次)', zorder=5)
    
    # 标记卖出点
    sell_points = df[df['sell_signal'] == True]
    if len(sell_points) > 0:
        ax1.scatter(sell_points.index, df.loc[sell_points.index, 'cum_strategy_ret'], 
                   marker='v', color='orange', s=80, label=f'卖出信号 ({len(sell_points)}次)', zorder=5)
    
    ax1.set_title('神奇九转策略回测绩效对比', fontsize=14, fontweight='bold')
    ax1.set_xlabel('日期')
    ax1.set_ylabel('累计收益率')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # 图2：价格与九转信号
    ax2 = axes[1]
    ax2.plot(df.index, df['close'], label='收盘价', color='black', linewidth=1, alpha=0.7)
    
    # 标记低9信号位置
    low9 = df[df['buy_signal'] == True]
    if len(low9) > 0:
        ax2.scatter(low9.index, low9['close'], marker='^', color='green', 
                   s=100, label='低9买入信号', zorder=5)
    
    # 标记高9信号位置
    high9 = df[df['sell_signal'] == True]
    if len(high9) > 0:
        ax2.scatter(high9.index, high9['close'], marker='v', color='red', 
                   s=100, label='高9卖出信号', zorder=5)
    
    ax2.set_title('价格走势与九转信号', fontsize=14, fontweight='bold')
    ax2.set_xlabel('日期')
    ax2.set_ylabel('价格')
    ax2.legend(loc='upper left')
    ax2.grid(True, alpha=0.3)
    
    # 图3：九转计数热力图（显示最近200个交易日）
    ax3 = axes[2]
    # 显示最近200个交易日的数据
    plot_df = df.tail(200).copy()
    if len(plot_df) > 0:
        # 创建计数矩阵
        buy_counts = plot_df['buy_count'].values.reshape(1, -1)
        sell_counts = plot_df['sell_count'].values.reshape(1, -1)
        
        # 使用两种颜色显示
        im1 = ax3.imshow(buy_counts, aspect='auto', cmap='RdYlGn_r', vmin=0, vmax=9)
        ax3.set_yticks([0])
        ax3.set_yticklabels(['买入计数'])
        
        # 设置x轴标签（每隔30天显示一个）
        tick_positions = range(0, len(plot_df), 30)
        tick_labels = [plot_df.index[i].strftime('%Y-%m-%d') for i in tick_positions]
        ax3.set_xticks(tick_positions)
        ax3.set_xticklabels(tick_labels, rotation=45, ha='right')
        
        ax3.set_title('九转计数热力图（最近200个交易日）', fontsize=14, fontweight='bold')
        plt.colorbar(im1, ax=ax3, label='计数')
    
    plt.tight_layout()
    plt.savefig('magic_nine_turn_backtest.png', dpi=150, bbox_inches='tight')
    plt.show()
    
    print("\n图表已保存为: magic_nine_turn_backtest.png")


def print_summary(metrics):
    """
    打印回测总结
    """
    print("\n" + "="*60)
    print("神奇九转策略回测总结")
    print("="*60)
    for key, value in metrics.items():
        print(f"{key:15}: {value}")
    print("="*60)


def main():
    """
    主函数：执行完整的回测流程
    """
    print("="*60)
    print("神奇九转策略回测系统启动")
    print("="*60)
    
    # 1. 获取数据
    print("\n[1/5] 正在获取数据...")
    # 从本地数据库获取股票数据
    df = get_data_from_local(symbol='sz.000001',  # 浦发银行
                             start_date='2020-01-01', 
                             end_date='2025-12-31')
    
    if df is None or len(df) == 0:
        print("数据获取失败，程序退出")
        return
    
    # 2. 计算九转信号
    print("\n[2/5] 正在计算神奇九转序列...")
    df = calculate_nine_turn(df)
    
    buy_signals = df[df['buy_signal'] == True].shape[0]
    sell_signals = df[df['sell_signal'] == True].shape[0]
    print(f"检测到买入信号(低9): {buy_signals}次")
    print(f"检测到卖出信号(高9): {sell_signals}次")
    
    # 3. 执行回测
    print("\n[3/5] 正在执行回测...")
    df, trade_count = run_backtest(df, commission_rate=0.00025, slippage=0.001)
    
    # 4. 计算绩效指标
    print("\n[4/5] 正在计算绩效指标...")
    metrics = calculate_performance_metrics(df, trade_count)
    print_summary(metrics)
    
    # 5. 绘制图表
    print("\n[5/5] 正在生成可视化图表...")
    plot_results(df)
    
    # 保存详细结果到CSV
    output_columns = ['close', 'open', 'high', 'low', 'vol', 
                      'buy_count', 'sell_count', 'buy_signal', 'sell_signal',
                      'position', 'returns', 'cum_strategy_ret', 'cum_benchmark_ret', 'trade_log']
    result_df = df[output_columns].copy()
    result_df.to_csv('magic_nine_turn_results.csv', encoding='utf-8-sig')
    print("\n详细结果已保存为: magic_nine_turn_results.csv")
    
    print("\n" + "="*60)
    print("回测完成！")
    print("="*60)


if __name__ == "__main__":
    main()