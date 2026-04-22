# coding: utf-8
"""
OBV高胜率策略回测系统 - 含完整回测表
生成详细的交易记录、每日持仓、收益统计等报表
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# ==================== 导入自定义模块 ====================
try:
    from czsc_daily_util import *
    from lib.MyTT import *
    from czsc_sqlite import get_local_stock_data
except ImportError:
    print("注意：部分模块未找到，将使用基础函数")
    
    def MA(close, n):
        return close.rolling(window=n).mean()
    
    def EMA(close, n):
        return close.ewm(span=n, adjust=False).mean()
    
    def RSI(close, n=14):
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=n).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=n).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

# ==================== OBV指标计算 ====================

def calc_OBV(df):
    """计算OBV指标"""
    obv = [0]
    for i in range(1, len(df)):
        if df['close'].iloc[i] > df['close'].iloc[i-1]:
            obv.append(obv[-1] + df['volume'].iloc[i])
        elif df['close'].iloc[i] < df['close'].iloc[i-1]:
            obv.append(obv[-1] - df['volume'].iloc[i])
        else:
            obv.append(obv[-1])
    df['OBV'] = obv
    return df

def calc_OBV_MA(df, period=10):
    """计算OBV均线"""
    df['OBV_MA'] = df['OBV'].rolling(window=period).mean()
    return df

def calc_OBV_RSI(df, period=5):
    """计算OBV的RSI指标"""
    delta = df['OBV'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['OBV_RSI'] = 100 - (100 / (1 + rs))
    return df

def find_obv_divergence(df, lookback=20):
    """寻找OBV底背离"""
    if len(df) < lookback + 10:
        return False
    
    recent_df = df.tail(lookback + 10).copy()
    
    price_lows = []
    obv_lows = []
    
    for i in range(5, len(recent_df) - 5):
        if (recent_df['low'].iloc[i] <= recent_df['low'].iloc[i-1] and 
            recent_df['low'].iloc[i] <= recent_df['low'].iloc[i-2] and
            recent_df['low'].iloc[i] <= recent_df['low'].iloc[i+1] and
            recent_df['low'].iloc[i] <= recent_df['low'].iloc[i+2]):
            price_lows.append((i, recent_df['low'].iloc[i]))
            obv_lows.append((i, recent_df['OBV'].iloc[i]))
    
    if len(price_lows) >= 2:
        last_price_low = price_lows[-1]
        prev_price_low = price_lows[-2]
        
        last_obv_low = None
        prev_obv_low = None
        
        for obv_low in obv_lows:
            if obv_low[0] == last_price_low[0]:
                last_obv_low = obv_low
            if obv_low[0] == prev_price_low[0]:
                prev_obv_low = obv_low
        
        if last_obv_low and prev_obv_low:
            if (last_price_low[1] < prev_price_low[1] and 
                last_obv_low[1] > prev_obv_low[1]):
                return True
    
    return False

# ==================== OBV策略类 ====================

class OBVStrategy:
    """OBV高胜率策略"""
    
    def __init__(self, 
                 ma_short=20,
                 obv_ma_period=10,
                 rsi_period=5,
                 rsi_oversold=30,
                 lookback_days=20,
                 hold_days=5,
                 stop_loss=-5,
                 take_profit=15):
        
        self.ma_short = ma_short
        self.obv_ma_period = obv_ma_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.lookback_days = lookback_days
        self.hold_days = hold_days
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        
        # 统计数据容器
        self.all_signals = []           # 所有信号
        self.all_trades = []            # 所有交易
        self.daily_returns = {}         # 每日收益
        self.symbol_results = {}        # 每只股票结果
        
        for i in range(1, hold_days + 1):
            self.daily_returns[i] = []
    
    def prepare_data(self, df):
        """准备技术指标"""
        df = df.copy()
        df = calc_OBV(df)
        df = calc_OBV_MA(df, self.obv_ma_period)
        df = calc_OBV_RSI(df, self.rsi_period)
        df['MA20'] = MA(df['close'], self.ma_short)
        df['MA20_Direction'] = df['MA20'].diff(5) > -0.005 * df['MA20']
        df['Volume_Ratio'] = df['volume'] / df['volume'].shift(1)
        return df
    
    def check_buy_signal(self, df, idx):
        """检查买入信号"""
        if idx < self.lookback_days + 20:
            return False
        
        row = df.iloc[idx]
        prev_row = df.iloc[idx - 1]
        
        # 条件1：价格站上20日均线
        if row['close'] <= row['MA20']:
            return False
        
        # 条件2：OBV > OBV_MA
        if pd.isna(row['OBV']) or pd.isna(row['OBV_MA']):
            return False
        if row['OBV'] <= row['OBV_MA']:
            return False
        
        # 条件3：温和放量
        if row['volume'] <= prev_row['volume']:
            return False
        
        # 条件4：底背离
        recent_df = df.iloc[max(0, idx - self.lookback_days - 10):idx + 1]
        if not find_obv_divergence(recent_df, self.lookback_days):
            return False
        
        return True
    
    def simulate_holding(self, df, idx, buy_date, buy_price):
        """模拟持有期收益"""
        daily_returns = []
        
        for hold in range(1, self.hold_days + 1):
            sell_idx = idx + hold
            if sell_idx >= len(df):
                daily_returns.append(None)
                continue
            
            sell_price = df['close'].iloc[sell_idx]
            ret = (sell_price - buy_price) / buy_price * 100
            daily_returns.append(ret)
            
            # 记录每日收益
            self.daily_returns[hold].append(ret)
            
            # 止损/止盈检查
            if ret <= self.stop_loss:
                # 触发止损，提前卖出
                return ret, hold, True
            if ret >= self.take_profit:
                # 触发止盈，提前卖出
                return ret, hold, True
        
        # 持有到期，取最大收益
        valid_returns = [r for r in daily_returns if r is not None]
        if valid_returns:
            return max(valid_returns), len(valid_returns), False
        return None, 0, False
    
    def run_backtest(self, df, symbol, start_date=None, end_date=None):
        """运行单只股票回测"""
        if start_date:
            df = df[df['date'] >= start_date]
        if end_date:
            df = df[df['date'] <= end_date]
        
        if len(df) < 100:
            return []
        
        df = self.prepare_data(df)
        df = df.reset_index(drop=True)
        
        trades = []
        
        for idx in range(len(df)):
            if self.check_buy_signal(df, idx):
                buy_date = df['date'].iloc[idx]
                buy_price = df['close'].iloc[idx]
                
                # 记录信号详情
                signal = {
                    'symbol': symbol,
                    'buy_date': buy_date,
                    'buy_price': buy_price,
                    'obv': df['OBV'].iloc[idx],
                    'obv_ma': df['OBV_MA'].iloc[idx],
                    'close_ma20_ratio': df['close'].iloc[idx] / df['MA20'].iloc[idx] - 1,
                    'volume_ratio': df['Volume_Ratio'].iloc[idx]
                }
                self.all_signals.append(signal)
                
                # 模拟持有
                max_return, hold_days, stopped = self.simulate_holding(df, idx, buy_date, buy_price)
                
                if max_return is not None:
                    trade = {
                        'symbol': symbol,
                        'buy_date': buy_date,
                        'buy_price': buy_price,
                        'sell_date': df['date'].iloc[min(idx + hold_days, len(df) - 1)],
                        'hold_days': hold_days,
                        'return_pct': max_return,
                        'is_profit': max_return > 0,
                        'stopped': stopped,
                        'stop_type': '止损' if stopped and max_return <= self.stop_loss else ('止盈' if stopped and max_return >= self.take_profit else '到期')
                    }
                    trades.append(trade)
                    self.all_trades.append(trade)
        
        # 保存股票结果
        self.symbol_results[symbol] = trades
        return trades


# ==================== 回测表生成器 ====================

class BacktestReport:
    """回测报表生成器"""
    
    def __init__(self, strategy, output_dir="./obv_backtest_reports"):
        self.strategy = strategy
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
    
    def generate_trade_table(self):
        """生成交易明细表"""
        trades = self.strategy.all_trades
        if not trades:
            return pd.DataFrame()
        
        df_trades = pd.DataFrame(trades)
        df_trades = df_trades.sort_values('buy_date')
        
        # 添加累计收益列
        df_trades['cumulative_return'] = (1 + df_trades['return_pct'] / 100).cumprod()
        df_trades['cumulative_return'] = (df_trades['cumulative_return'] - 1) * 100
        
        # 添加序号
        df_trades.insert(0, 'trade_no', range(1, len(df_trades) + 1))
        
        return df_trades
    
    def generate_signal_table(self):
        """生成信号明细表"""
        signals = self.strategy.all_signals
        if not signals:
            return pd.DataFrame()
        
        df_signals = pd.DataFrame(signals)
        df_signals = df_signals.sort_values('buy_date')
        df_signals.insert(0, 'signal_no', range(1, len(df_signals) + 1))
        
        return df_signals
    
    def generate_daily_return_table(self):
        """生成每日收益统计表"""
        daily_stats = []
        for day in range(1, self.strategy.hold_days + 1):
            returns = self.strategy.daily_returns[day]
            if returns:
                positive = [r for r in returns if r > 0]
                negative = [r for r in returns if r <= 0]
                
                daily_stats.append({
                    '持有天数': day,
                    '样本数': len(returns),
                    '胜率(%)': round(len(positive) / len(returns) * 100, 2),
                    '平均收益(%)': round(np.mean(returns), 2),
                    '中位数收益(%)': round(np.median(returns), 2),
                    '最大收益(%)': round(max(returns), 2),
                    '最小收益(%)': round(min(returns), 2),
                    '正收益总和': round(sum(positive), 2),
                    '负收益总和': round(sum(negative), 2),
                    '盈亏比': round(abs(sum(positive) / sum(negative)), 2) if negative else None
                })
        
        return pd.DataFrame(daily_stats)
    
    def generate_symbol_summary(self):
        """生成股票汇总表"""
        summaries = []
        for symbol, trades in self.strategy.symbol_results.items():
            if trades:
                returns = [t['return_pct'] for t in trades]
                profits = [r for r in returns if r > 0]
                losses = [r for r in returns if r <= 0]
                
                summaries.append({
                    '股票代码': symbol,
                    '交易次数': len(trades),
                    '盈利次数': len(profits),
                    '胜率(%)': round(len(profits) / len(trades) * 100, 2),
                    '平均收益(%)': round(np.mean(returns), 2),
                    '总收益(%)': round(sum(returns), 2),
                    '最大收益(%)': round(max(returns), 2),
                    '最小收益(%)': round(min(returns), 2),
                    '平均持有天数': round(np.mean([t['hold_days'] for t in trades]), 1),
                    '止损次数': len([t for t in trades if t.get('stopped') and t.get('stop_type') == '止损']),
                    '止盈次数': len([t for t in trades if t.get('stopped') and t.get('stop_type') == '止盈'])
                })
        
        return pd.DataFrame(summaries).sort_values('交易次数', ascending=False)
    
    def generate_monthly_summary(self):
        """生成月度统计表"""
        trades = self.strategy.all_trades
        if not trades:
            return pd.DataFrame()
        
        df_trades = pd.DataFrame(trades)
        df_trades['buy_month'] = pd.to_datetime(df_trades['buy_date']).dt.to_period('M')
        
        monthly_stats = []
        for month, group in df_trades.groupby('buy_month'):
            profits = group[group['return_pct'] > 0]
            monthly_stats.append({
                '月份': str(month),
                '交易次数': len(group),
                '盈利次数': len(profits),
                '胜率(%)': round(len(profits) / len(group) * 100, 2),
                '月度总收益(%)': round(group['return_pct'].sum(), 2),
                '平均收益(%)': round(group['return_pct'].mean(), 2),
                '最大单笔收益(%)': round(group['return_pct'].max(), 2),
                '最小单笔收益(%)': round(group['return_pct'].min(), 2)
            })
        
        return pd.DataFrame(monthly_stats)
    
    def generate_yearly_summary(self):
        """生成年度统计表"""
        trades = self.strategy.all_trades
        if not trades:
            return pd.DataFrame()
        
        df_trades = pd.DataFrame(trades)
        df_trades['buy_year'] = pd.to_datetime(df_trades['buy_date']).dt.year
        
        yearly_stats = []
        for year, group in df_trades.groupby('buy_year'):
            profits = group[group['return_pct'] > 0]
            yearly_stats.append({
                '年份': year,
                '交易次数': len(group),
                '盈利次数': len(profits),
                '胜率(%)': round(len(profits) / len(group) * 100, 2),
                '年度总收益(%)': round(group['return_pct'].sum(), 2),
                '平均收益(%)': round(group['return_pct'].mean(), 2),
                '最大单笔收益(%)': round(group['return_pct'].max(), 2),
                '最小单笔收益(%)': round(group['return_pct'].min(), 2)
            })
        
        return pd.DataFrame(yearly_stats)
    
    def generate_equity_curve(self):
        """生成资金曲线数据"""
        trades = self.strategy.all_trades
        if not trades:
            return pd.DataFrame()
        
        df_trades = pd.DataFrame(trades)
        df_trades = df_trades.sort_values('buy_date')
        
        # 添加序号
        df_trades.insert(0, 'trade_no', range(1, len(df_trades) + 1))
        
        # 计算累计收益
        df_trades['cumulative_return'] = (1 + df_trades['return_pct'] / 100).cumprod()
        df_trades['cumulative_return'] = (df_trades['cumulative_return'] - 1) * 100
        
        # 添加回撤计算
        df_trades['max_cumulative'] = df_trades['cumulative_return'].cummax()
        df_trades['drawdown'] = df_trades['cumulative_return'] - df_trades['max_cumulative']
        
        return df_trades[['trade_no', 'buy_date', 'return_pct', 'cumulative_return', 'drawdown']]
    
    def generate_equity_curve_chart(self, save_path=None):
        """生成资金趋势图"""
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib import font_manager
        
        # 设置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        equity_data = self.generate_equity_curve()
        if equity_data.empty:
            print("警告: 没有交易数据，无法生成资金曲线图")
            return None
        
        # 创建图形
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [3, 1]})
        fig.suptitle('OBV高胜率策略 - 资金趋势图', fontsize=16, fontweight='bold')
        
        # 转换日期
        equity_data['buy_date_dt'] = pd.to_datetime(equity_data['buy_date'])
        
        # 上图：累计收益曲线
        ax1.plot(equity_data['buy_date_dt'], equity_data['cumulative_return'], 
                color='#2E86AB', linewidth=2, label='累计收益率')
        ax1.fill_between(equity_data['buy_date_dt'], equity_data['cumulative_return'], 
                        alpha=0.3, color='#2E86AB')
        ax1.axhline(y=0, color='gray', linestyle='--', linewidth=0.5)
        ax1.set_ylabel('累计收益率 (%)', fontsize=12)
        ax1.set_title('累计收益走势', fontsize=13)
        ax1.legend(loc='upper left', fontsize=10)
        ax1.grid(True, alpha=0.3)
        
        # 标注最大回撤
        max_dd_idx = equity_data['drawdown'].idxmin()
        if not pd.isna(max_dd_idx):
            max_dd = equity_data.loc[max_dd_idx, 'drawdown']
            max_dd_date = equity_data.loc[max_dd_idx, 'buy_date_dt']
            ax1.annotate(f'最大回撤\n{max_dd:.2f}%', 
                        xy=(max_dd_date, max_dd),
                        xytext=(10, 30), textcoords='offset points',
                        bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.7),
                        arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='red'),
                        fontsize=9, color='red')
        
        # 下图：单笔收益分布
        colors = ['#A23B72' if r < 0 else '#F18F01' for r in equity_data['return_pct']]
        ax2.bar(range(len(equity_data)), equity_data['return_pct'], color=colors, alpha=0.7, edgecolor='black', linewidth=0.5)
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax2.set_xlabel('交易序号', fontsize=12)
        ax2.set_ylabel('单笔收益率 (%)', fontsize=12)
        ax2.set_title('单笔收益分布', fontsize=13)
        ax2.grid(True, alpha=0.3, axis='y')
        
        # 设置x轴刻度
        step = max(1, len(equity_data) // 10)
        ax2.set_xticks(range(0, len(equity_data), step))
        ax2.set_xticklabels(range(1, len(equity_data) + 1, step), rotation=45)
        
        # 调整布局
        plt.tight_layout()
        
        # 保存图片
        if save_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = f"{self.output_dir}/equity_curve_{timestamp}.png"
        
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"资金趋势图已保存: {save_path}")
        
        plt.close()
        return save_path
    
    def generate_full_report(self):
        """生成完整回测报告"""
        report = {}
        
        # 1. 交易明细表
        report['trade_table'] = self.generate_trade_table()
        
        # 2. 信号明细表
        report['signal_table'] = self.generate_signal_table()
        
        # 3. 每日收益统计表
        report['daily_return_table'] = self.generate_daily_return_table()
        
        # 4. 股票汇总表
        report['symbol_summary'] = self.generate_symbol_summary()
        
        # 5. 月度统计表
        report['monthly_summary'] = self.generate_monthly_summary()
        
        # 6. 年度统计表
        report['yearly_summary'] = self.generate_yearly_summary()
        
        # 7. 资金曲线
        report['equity_curve'] = self.generate_equity_curve()
        
        # 8. 生成资金趋势图
        try:
            chart_path = self.generate_equity_curve_chart()
            report['equity_chart_path'] = chart_path
        except Exception as e:
            print(f"警告: 生成资金趋势图失败 - {e}")
            report['equity_chart_path'] = None
        
        return report
    
    def export_to_excel(self, report):
        """导出到Excel文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.output_dir}/obv_backtest_report_{timestamp}.xlsx"
        
        with pd.ExcelWriter(filename, engine='openpyxl') as writer:
            # 写入各个表格
            for sheet_name, df in report.items():
                # 跳过非 DataFrame 类型的数据（如图表路径）
                if not isinstance(df, pd.DataFrame):
                    continue
                    
                if not df.empty:
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    
                    # 调整列宽
                    worksheet = writer.sheets[sheet_name]
                    for idx, column in enumerate(df.columns):
                        try:
                            # 将列索引转换为 Excel 列字母 (A, B, C, ...)
                            from openpyxl.utils import get_column_letter
                            col_letter = get_column_letter(idx + 1)
                            column_width = max(df[column].astype(str).map(len).max(), len(str(column))) + 2
                            worksheet.column_dimensions[col_letter].width = min(column_width, 30)
                        except Exception as e:
                            print(f"警告: 调整列宽时出错 - {e}")
            
            # 添加策略参数表
            params_df = pd.DataFrame([
                ['短期均线周期', self.strategy.ma_short],
                ['OBV均线周期', self.strategy.obv_ma_period],
                ['RSI周期', self.strategy.rsi_period],
                ['RSI超卖阈值', self.strategy.rsi_oversold],
                ['底背离回溯天数', self.strategy.lookback_days],
                ['持有天数', self.strategy.hold_days],
                ['止损线(%)', self.strategy.stop_loss],
                ['止盈线(%)', self.strategy.take_profit],
                ['回测开始时间', datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
            ], columns=['参数名称', '参数值'])
            params_df.to_excel(writer, sheet_name='策略参数', index=False)
        
        print(f"\n报告已导出: {filename}")
        return filename
    
    def print_summary_stats(self):
        """打印汇总统计"""
        trades = self.strategy.all_trades
        if not trades:
            print("没有交易记录")
            return
        
        df_trades = pd.DataFrame(trades)
        
        total_trades = len(trades)
        profit_trades = df_trades[df_trades['return_pct'] > 0]
        loss_trades = df_trades[df_trades['return_pct'] <= 0]
        
        win_rate = len(profit_trades) / total_trades * 100
        
        print("\n" + "="*70)
        print("OBV高胜率策略 - 回测汇总统计")
        print("="*70)
        
        print(f"\n【核心指标】")
        print(f"  总交易次数: {total_trades}")
        print(f"  胜率: {win_rate:.2f}%")
        print(f"  平均收益率: {df_trades['return_pct'].mean():.2f}%")
        print(f"  总收益率(累计): {df_trades['return_pct'].sum():.2f}%")
        
        print(f"\n【盈利/亏损分布】")
        print(f"  盈利次数: {len(profit_trades)}")
        print(f"  亏损次数: {len(loss_trades)}")
        print(f"  盈利总收益: {profit_trades['return_pct'].sum():.2f}%")
        print(f"  亏损总损失: {loss_trades['return_pct'].sum():.2f}%")
        
        profit_factor = abs(profit_trades['return_pct'].sum() / loss_trades['return_pct'].sum()) if len(loss_trades) > 0 else None
        if profit_factor:
            print(f"  盈亏比(Profit Factor): {profit_factor:.2f}")
        
        print(f"\n【极端情况】")
        print(f"  最大单笔盈利: {df_trades['return_pct'].max():.2f}%")
        print(f"  最大单笔亏损: {df_trades['return_pct'].min():.2f}%")
        print(f"  平均持有天数: {df_trades['hold_days'].mean():.1f}天")
        
        # 止损止盈统计
        if 'stopped' in df_trades.columns:
            stop_loss_count = len(df_trades[(df_trades['stopped'] == True) & (df_trades['stop_type'] == '止损')])
            take_profit_count = len(df_trades[(df_trades['stopped'] == True) & (df_trades['stop_type'] == '止盈')])
            print(f"\n【风控统计】")
            print(f"  触发止损次数: {stop_loss_count}")
            print(f"  触发止盈次数: {take_profit_count}")
        
        print("\n" + "="*70)
        
        # 胜率评级
        if win_rate >= 80:
            print(f"✅ 胜率评级: 优秀 ({win_rate:.2f}%) - 达到80%目标")
        elif win_rate >= 75:
            print(f"👍 胜率评级: 良好 ({win_rate:.2f}%) - 接近目标")
        elif win_rate >= 70:
            print(f"⚠️ 胜率评级: 合格 ({win_rate:.2f}%) - 需优化")
        else:
            print(f"❌ 胜率评级: 待优化 ({win_rate:.2f}%)")
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'avg_return': df_trades['return_pct'].mean(),
            'total_return': df_trades['return_pct'].sum(),
            'max_return': df_trades['return_pct'].max(),
            'min_return': df_trades['return_pct'].min()
        }


# ==================== 多股票回测运行 ====================

def run_backtest_with_report(symbols, start_date="2020-01-01", hold_days=5, output_dir="./obv_backtest_reports"):
    """
    运行回测并生成报告
    """
    print(f"\n{'='*60}")
    print(f"OBV高胜率策略回测")
    print(f"{'='*60}")
    print(f"回测开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"持有天数: {hold_days}天")
    print(f"开始日期: {start_date}")
    print(f"股票数量: {len(symbols)}")
    print(f"{'='*60}\n")
    
    # 初始化策略
    strategy = OBVStrategy(hold_days=hold_days)
    
    # 运行回测
    success_count = 0
    for i, symbol in enumerate(symbols):
        print(f"[{i+1}/{len(symbols)}] 处理: {symbol}")
        
        try:
            # 获取数据
            df = get_local_stock_data(symbol, start_date)
            
            if df is None or len(df) < 100:
                print(f"  数据不足，跳过")
                continue
            
            # 运行回测
            trades = strategy.run_backtest(df, symbol, start_date)
            
            if trades:
                success_count += 1
                print(f"  产生 {len(trades)} 个交易信号")
            else:
                print(f"  无交易信号")
                
        except Exception as e:
            print(f"  处理失败: {e}")
            continue
    
    # 生成报告
    print(f"\n回测完成，共 {len(strategy.all_trades)} 个交易记录")
    
    # 创建报告生成器
    reporter = BacktestReport(strategy, output_dir)
    
    # 打印汇总统计
    stats = reporter.print_summary_stats()
    
    # 生成完整报告
    report = reporter.generate_full_report()
    
    # 导出Excel
    excel_file = reporter.export_to_excel(report)
    
    # 打印每日统计
    print(f"\n【每日收益统计详情】")
    daily_df = report.get('daily_return_table')
    if daily_df is not None and not daily_df.empty:
        print(daily_df.to_string(index=False))
    
    return strategy, report, stats


# ==================== 参数优化 ====================

def optimize_parameters(symbols, start_date="2020-01-01"):
    """
    参数优化：寻找最佳参数组合
    """
    print("\n" + "="*60)
    print("参数优化中...")
    print("="*60)
    
    # 参数范围
    param_grid = {
        'hold_days': [3, 5, 7, 10],
        'obv_ma_period': [5, 10, 15],
        'lookback_days': [15, 20, 25]
    }
    
    results = []
    
    for hold_days in param_grid['hold_days']:
        for obv_ma_period in param_grid['obv_ma_period']:
            for lookback_days in param_grid['lookback_days']:
                
                strategy = OBVStrategy(
                    hold_days=hold_days,
                    obv_ma_period=obv_ma_period,
                    lookback_days=lookback_days
                )
                
                # 快速回测（只测试前10只股票）
                test_symbols = symbols[:10]
                total_trades = 0
                win_trades = 0
                
                for symbol in test_symbols:
                    try:
                        df = get_local_stock_data(symbol, start_date)
                        if df is not None and len(df) > 100:
                            trades = strategy.run_backtest(df, symbol, start_date)
                            if trades:
                                total_trades += len(trades)
                                win_trades += len([t for t in trades if t['return_pct'] > 0])
                    except:
                        continue
                
                if total_trades > 0:
                    win_rate = win_trades / total_trades * 100
                    results.append({
                        'hold_days': hold_days,
                        'obv_ma_period': obv_ma_period,
                        'lookback_days': lookback_days,
                        'total_trades': total_trades,
                        'win_rate': round(win_rate, 2)
                    })
    
    # 按胜率排序
    results_df = pd.DataFrame(results)
    if not results_df.empty:
        results_df = results_df.sort_values('win_rate', ascending=False)
        print("\n参数优化结果（按胜率排序）:")
        print(results_df.to_string(index=False))
        
        # 返回最佳参数
        best = results_df.iloc[0]
        print(f"\n最佳参数组合:")
        print(f"  持有天数: {best['hold_days']}")
        print(f"  OBV均线周期: {best['obv_ma_period']}")
        print(f"  底背离回溯天数: {best['lookback_days']}")
        print(f"  胜率: {best['win_rate']}%")
        
        return best.to_dict()
    
    return None


# ==================== 主程序 ====================

if __name__ == '__main__':
    # 配置参数
    START_DATE = "2020-01-01"
    HOLD_DAYS = 5
    OUTPUT_DIR = "./obv_backtest_reports"
    OPTIMIZE_PARAMS = True  # 是否进行参数优化
    
    # 获取股票列表
    try:
        from czsc_daily_util import get_daily_symbols
        all_symbols = get_daily_symbols()
        # 可以限制数量进行测试
        test_symbols = all_symbols[:50]  # 测试50只股票
        print(f"获取到 {len(all_symbols)} 只股票，本次测试前50只")
    except:
        # 测试用股票列表
        test_symbols = ['sh.600000', 'sh.600036', 'sh.600519', 'sh.600050', 'sh.600104',
                        'sz.000001', 'sz.000002', 'sz.000858', 'sz.002415', 'sz.300750']
        print(f"使用测试股票列表: {test_symbols}")
    
    # 参数优化
    if OPTIMIZE_PARAMS and len(test_symbols) >= 10:
        best_params = optimize_parameters(test_symbols, START_DATE)
        if best_params:
            HOLD_DAYS = best_params['hold_days']
            print(f"\n使用优化后的参数: hold_days={HOLD_DAYS}")
    
    # 运行回测并生成报告
    strategy, report, stats = run_backtest_with_report(
        symbols=test_symbols,
        start_date=START_DATE,
        hold_days=HOLD_DAYS,
        output_dir=OUTPUT_DIR
    )
    
    print(f"\n回测结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")