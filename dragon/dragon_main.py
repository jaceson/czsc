# 安装依赖
# pip install akshare pandas numpy matplotlib seaborn

import pandas as pd
import numpy as np
from dragon_strategy_backtest import DragonStrategyBacktest
from dragon_backtest_visual import BacktestVisualizer
from dragon_data_fetcher import RealtimeDataFetcher

def main():
    print("=" * 60)
    print("龙头战法策略系统启动")
    print("=" * 60)
    
    # 1. 初始化系统
    dragon_backtest = DragonStrategyBacktest('../data/block_list.json')
    
    # 2. 设置回测参数
    start_date = '2024-01-01'
    end_date = '2024-12-31'
    
    # 3. 运行回测
    print("\n开始回测...")
    result = dragon_backtest.run_backtest(start_date, end_date)
    
    # 4. 输出回测报告
    print(result['report'])
    
    # 5. 可视化分析
    visualizer = BacktestVisualizer(result)
    visualizer.plot_equity_curve()
    visualizer.plot_trade_analysis()
    
    # 6. 输出交易记录
    print("\n=== 交易记录摘要 ===")
    trades_df = pd.DataFrame(result['trades'])
    if not trades_df.empty:
        print(trades_df[['date', 'stock_code', 'action', 'price', 'shares']].head(20))
    
    # 7. 获取当前市场龙头候选
    print("\n=== 当前市场龙头候选 ===")
    fetcher = RealtimeDataFetcher()
    hot_stocks = dragon_backtest._get_hot_block_stocks()
    realtime_data = fetcher.get_realtime_price_akshare(hot_stocks[:50])
    
    candidates = []
    for code, data in realtime_data.items():
        if data['change_pct'] > 5 and data['change_pct'] < 10:  # 涨幅5%-10%
            candidates.append({
                'code': code,
                'name': data['name'],
                'price': data['price'],
                'change_pct': data['change_pct'],
                'turnover': data['turnover']
            })
    
    candidates.sort(key=lambda x: x['change_pct'], reverse=True)
    for c in candidates[:10]:
        print(f"{c['code']} {c['name']}: 涨幅{c['change_pct']:.2f}%, 换手{c['turnover']:.2f}%")
    
    return result

if __name__ == "__main__":
    result = main()