class BlockStrengthAnalyzer:
    """板块强度分析器"""
    
    def __init__(self, strategy):
        self.strategy = strategy
        
    def calculate_block_strength(self, stock_performance):
        """
        计算板块强度
        stock_performance: {stock_code: return_rate}
        """
        block_strength = {}
        
        for block_name, block_info in self.strategy.block_data.items():
            stocks_in_block = block_info['stocks']
            returns = []
            
            for stock in stocks_in_block:
                code = stock['stock_code']
                if code in stock_performance:
                    returns.append(stock_performance[code])
            
            if returns:
                # 板块平均涨幅
                avg_return = np.mean(returns)
                # 板块上涨家数比例
                up_ratio = len([r for r in returns if r > 0]) / len(returns)
                # 板块强度评分
                strength = avg_return * 100 + up_ratio * 50
                
                block_strength[block_name] = {
                    'avg_return': avg_return,
                    'up_ratio': up_ratio,
                    'strength': strength,
                    'stock_count': len(stocks_in_block)
                }
        
        return sorted(block_strength.items(), key=lambda x: x[1]['strength'], reverse=True)
    
    def get_leading_blocks(self, stock_performance, top_n=5):
        """获取领涨板块"""
        sorted_blocks = self.calculate_block_strength(stock_performance)
        return sorted_blocks[:top_n]
    
    def get_block_leading_stocks(self, block_name, stock_performance, top_n=3):
        """获取板块内的领涨个股"""
        stocks = self.strategy.get_block_stocks(block_name)
        stock_returns = []
        
        for stock in stocks:
            code = stock['stock_code']
            if code in stock_performance:
                stock_returns.append({
                    'code': code,
                    'name': stock['stock_name'],
                    'return_rate': stock_performance[code]
                })
        
        return sorted(stock_returns, key=lambda x: x['return_rate'], reverse=True)[:top_n]