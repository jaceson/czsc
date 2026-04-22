import matplotlib.pyplot as plt
import seaborn as sns

class BacktestVisualizer:
    """回测结果可视化"""
    
    def __init__(self, backtest_result):
        self.result = backtest_result
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
        plt.rcParams['axes.unicode_minus'] = False
        
    def plot_equity_curve(self):
        """绘制净值曲线"""
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # 1. 净值曲线
        daily_values = self.result['daily_values']
        ax1 = axes[0, 0]
        ax1.plot(daily_values, label='策略净值', linewidth=2, color='blue')
        ax1.axhline(y=self.result['metrics']['initial_capital'], color='red', linestyle='--', label='初始资金')
        ax1.set_title('净值曲线', fontsize=12)
        ax1.set_xlabel('交易日')
        ax1.set_ylabel('资产(元)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 2. 收益率曲线
        returns = pd.Series(daily_values).pct_change().dropna()
        ax2 = axes[0, 1]
        ax2.plot(returns.index, returns.values, color='green', alpha=0.7)
        ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax2.set_title('每日收益率', fontsize=12)
        ax2.set_xlabel('交易日')
        ax2.set_ylabel('收益率')
        ax2.grid(True, alpha=0.3)
        
        # 3. 回撤曲线
        cummax = pd.Series(daily_values).expanding().max()
        drawdown = (pd.Series(daily_values) - cummax) / cummax * 100
        ax3 = axes[1, 0]
        ax3.fill_between(drawdown.index, drawdown.values, 0, color='red', alpha=0.3)
        ax3.plot(drawdown.index, drawdown.values, color='red', linewidth=1)
        ax3.set_title('回撤曲线', fontsize=12)
        ax3.set_xlabel('交易日')
        ax3.set_ylabel('回撤(%)')
        ax3.grid(True, alpha=0.3)
        
        # 4. 收益分布
        ax4 = axes[1, 1]
        ax4.hist(returns.values * 100, bins=50, color='steelblue', edgecolor='black', alpha=0.7)
        ax4.axvline(x=0, color='red', linestyle='--', linewidth=2)
        ax4.set_title('日收益率分布', fontsize=12)
        ax4.set_xlabel('收益率(%)')
        ax4.set_ylabel('频次')
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('backtest_results.png', dpi=150, bbox_inches='tight')
        plt.show()
        
    def plot_trade_analysis(self):
        """绘制交易分析图"""
        trades = self.result['trades']
        sell_trades = [t for t in trades if t['action'] == 'SELL' and 'profit_pct' in t]
        
        if not sell_trades:
            print("无卖出交易记录")
            return
        
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        
        # 盈亏分布
        profits = [t['profit_pct'] * 100 for t in sell_trades]
        ax1 = axes[0]
        colors = ['green' if p > 0 else 'red' for p in profits]
        ax1.bar(range(len(profits)), profits, color=colors, alpha=0.7)
        ax1.axhline(y=0, color='black', linestyle='-', linewidth=1)
        ax1.set_title('单笔交易盈亏(%)', fontsize=12)
        ax1.set_xlabel('交易序号')
        ax1.set_ylabel('盈亏(%)')
        
        # 累计盈亏
        cumulative_profit = np.cumsum([t['profit'] for t in sell_trades])
        ax2 = axes[1]
        ax2.plot(cumulative_profit, color='purple', linewidth=2, marker='o', markersize=4)
        ax2.set_title('累计盈亏曲线', fontsize=12)
        ax2.set_xlabel('交易序号')
        ax2.set_ylabel('累计盈亏(元)')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('trade_analysis.png', dpi=150, bbox_inches='tight')
        plt.show()