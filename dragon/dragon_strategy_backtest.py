import json
import time
import pandas as pd
import numpy as np
from dragon_backtest import BacktestEngine
from dragon_data_fetcher import RealtimeDataFetcher

class DragonStrategyBacktest:
    """龙头战法回测策略"""
    
    def __init__(self, block_data_path):
        with open(block_data_path, 'r', encoding='utf-8') as f:
            self.block_data = json.load(f)
        self.data_fetcher = RealtimeDataFetcher()
        self.engine = BacktestEngine(initial_capital=1000000)
        
    def calculate_technical_indicators(self, df):
        """计算技术指标"""
        if df.empty:
            return df
        
        # 移动平均线
        df['MA5'] = df['收盘'].rolling(5).mean()
        df['MA10'] = df['收盘'].rolling(10).mean()
        df['MA20'] = df['收盘'].rolling(20).mean()
        df['MA60'] = df['收盘'].rolling(60).mean()
        
        # 成交量均线
        df['VOL_MA5'] = df['成交量'].rolling(5).mean()
        df['VOL_MA10'] = df['成交量'].rolling(10).mean()
        
        # RSI
        delta = df['收盘'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['收盘'].ewm(span=12, adjust=False).mean()
        exp2 = df['收盘'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['Signal']
        
        # 布林带
        df['BB_Middle'] = df['收盘'].rolling(20).mean()
        bb_std = df['收盘'].rolling(20).std()
        df['BB_Upper'] = df['BB_Middle'] + 2 * bb_std
        df['BB_Lower'] = df['BB_Middle'] - 2 * bb_std
        
        return df
    
    def calculate_stock_strength(self, df, stock_code):
        """计算个股强度评分"""
        if df.empty or len(df) < 60:
            return 0
        
        df = self.calculate_technical_indicators(df)
        latest = df.iloc[-1]
        prev_5 = df.iloc[-6] if len(df) >= 6 else latest
        prev_10 = df.iloc[-11] if len(df) >= 11 else latest
        prev_20 = df.iloc[-21] if len(df) >= 21 else latest
        
        score = 0
        
        # 1. 涨幅评分 (30分)
        gain_5d = (latest['收盘'] - prev_5['收盘']) / prev_5['收盘']
        gain_10d = (latest['收盘'] - prev_10['收盘']) / prev_10['收盘']
        gain_20d = (latest['收盘'] - prev_20['收盘']) / prev_20['收盘']
        
        if gain_5d > 0.2: score += 30
        elif gain_5d > 0.1: score += 20
        elif gain_5d > 0.05: score += 10
        
        if gain_10d > 0.3: score += 15
        elif gain_10d > 0.15: score += 10
        
        if gain_20d > 0.4: score += 10
        elif gain_20d > 0.2: score += 5
        
        # 2. 趋势评分 (25分)
        if latest['收盘'] > latest['MA5'] > latest['MA10'] > latest['MA20']:
            score += 25
        elif latest['收盘'] > latest['MA5'] > latest['MA10']:
            score += 15
        elif latest['收盘'] > latest['MA5']:
            score += 8
        
        # 3. 成交量评分 (20分)
        vol_ratio = latest['成交量'] / latest['VOL_MA5'] if latest['VOL_MA5'] > 0 else 1
        if vol_ratio > 3: score += 20
        elif vol_ratio > 2: score += 15
        elif vol_ratio > 1.5: score += 8
        
        # 4. RSI评分 (10分)
        if 50 <= latest['RSI'] <= 80: score += 10
        elif 30 <= latest['RSI'] < 50: score += 5
        
        # 5. MACD评分 (15分)
        if latest['MACD'] > latest['Signal'] and latest['MACD_Hist'] > 0:
            score += 15
        elif latest['MACD'] > latest['Signal']:
            score += 8
        
        # 6. 概念叠加分
        concept_count = len(self.block_data.get(stock_code, {}).get('blocks', [])) if stock_code in self.block_data else 0
        score += min(concept_count * 3, 15)
        
        return score
    
    def get_dragon_signals(self, date, historical_data):
        """获取龙头信号"""
        signals = []
        
        for stock_code, df in historical_data.items():
            if df.empty or len(df) < 60:
                continue
            
            score = self.calculate_stock_strength(df, stock_code)
            
            if score >= 60:  # 高分候选
                latest = df.iloc[-1]
                signals.append({
                    'date': date,
                    'stock_code': stock_code,
                    'score': score,
                    'price': latest['收盘'],
                    'volume': latest['成交量'],
                    'signal_type': 'DRAGON_CANDIDATE'
                })
        
        # 按分数排序，取前5
        signals.sort(key=lambda x: x['score'], reverse=True)
        return signals[:5]
    
    def run_backtest(self, start_date, end_date, watchlist=None):
        """运行回测"""
        print(f"开始回测: {start_date} 至 {end_date}")
        
        # 获取回测日期列表
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        date_range = [d for d in date_range if d.weekday() < 5]  # 只保留交易日
        
        # 如果未指定watchlist，使用热门板块的股票
        if watchlist is None:
            watchlist = self._get_hot_block_stocks()
        
        # 存储每日数据
        daily_prices = {}
        
        for i, date in enumerate(date_range):
            date_str = date.strftime('%Y%m%d')
            print(f"回测进度: {i+1}/{len(date_range)} - {date_str}")
            
            # 获取当日行情
            daily_data = {}
            for code in watchlist[:100]:  # 限制数量
                df = self.data_fetcher.get_historical_data(code, days=120)
                if not df.empty:
                    daily_data[code] = df
            
            # 生成交易信号
            signals = self.get_dragon_signals(date_str, daily_data)
            
            # 获取当前价格
            current_prices = {}
            for code, df in daily_data.items():
                if not df.empty:
                    current_prices[code] = df.iloc[-1]['收盘']
            
            # 止盈止损检查
            self._check_stop_conditions(date_str, current_prices)
            
            # 执行买入信号
            for signal in signals:
                if signal['stock_code'] not in self.engine.positions:
                    # 买入
                    position_size = self.engine.capital * 0.1  # 每只股票10%仓位
                    shares = int(position_size / signal['price'] / 100) * 100
                    if shares > 0:
                        self.engine.execute_trade(
                            date_str, 
                            signal['stock_code'], 
                            'BUY', 
                            signal['price'], 
                            shares,
                            reason=f"龙头信号-评分{signal['score']}"
                        )
            
            # 记录每日净值
            total_value = self.engine.get_current_value(current_prices)
            self.engine.daily_values.append(total_value)
            
            # 延迟避免请求过快
            time.sleep(0.5)
        
        # 回测结束，清仓
        self._close_all_positions(date_range[-1].strftime('%Y%m%d'), current_prices)
        
        return self.get_backtest_report()
    
    def _check_stop_conditions(self, date, current_prices):
        """检查止盈止损"""
        positions_copy = list(self.engine.positions.items())
        
        for code, pos in positions_copy:
            if code in current_prices:
                current_price = current_prices[code]
                pnl_pct = (current_price - pos['avg_price']) / pos['avg_price']
                
                # 止损 -8%
                if pnl_pct <= -0.08:
                    shares = pos['shares']
                    self.engine.execute_trade(date, code, 'SELL', current_price, shares, reason=f"止损 {pnl_pct:.2%}")
                
                # 止盈 +20%
                elif pnl_pct >= 0.20:
                    shares = pos['shares']
                    self.engine.execute_trade(date, code, 'SELL', current_price, shares, reason=f"止盈 {pnl_pct:.2%}")
    
    def _close_all_positions(self, date, current_prices):
        """清仓所有持仓"""
        for code, pos in list(self.engine.positions.items()):
            if code in current_prices:
                self.engine.execute_trade(date, code, 'SELL', current_prices[code], pos['shares'], reason="回测结束清仓")
    
    def _get_hot_block_stocks(self):
        """获取热门板块的股票"""
        hot_blocks = ['新能源车', '芯片', '人工智能', '5G概念', '储能', '机器人概念']
        stocks = set()
        
        for block in hot_blocks:
            if block in self.block_data:
                for stock in self.block_data[block]['stocks']:
                    stocks.add(stock['stock_code'])
        
        return list(stocks)
    
    def get_backtest_report(self):
        """生成回测报告"""
        metrics = self.engine.get_performance_metrics()
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║                      龙头战法回测报告                        ║
╠══════════════════════════════════════════════════════════════╣
║  初始资金: {metrics.get('initial_capital', 0):,.2f}                                     
║  最终权益: {metrics.get('final_value', 0):,.2f}                                     
║  总收益率: {metrics.get('total_return_pct', 0):.2f}%                                        
║  年化收益率: {metrics.get('annual_return_pct', 0):.2f}%                                      
║  夏普比率: {metrics.get('sharpe_ratio', 0):.2f}                                            
║  最大回撤: {metrics.get('max_drawdown_pct', 0):.2f}%                                        
║  胜率: {metrics.get('win_rate_pct', 0):.2f}%                                              
║  总交易次数: {metrics.get('total_trades', 0)}                                             
║  买入次数: {metrics.get('buy_trades', 0)}                                              
║  卖出次数: {metrics.get('sell_trades', 0)}                                             
╚══════════════════════════════════════════════════════════════╝
"""
        return {
            'report': report,
            'metrics': metrics,
            'trades': self.engine.trades,
            'daily_values': self.engine.daily_values
        }