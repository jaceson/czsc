class DragonTradingStrategy:
    """龙头战法完整交易策略"""
    
    def __init__(self, block_data_path):
        self.strategy = DragonStockStrategy(block_data_path)
        self.scanner = DragonStockScanner(self.strategy)
        self.analyzer = BlockStrengthAnalyzer(self.strategy)
        
    def daily_screening(self, market_data):
        """
        每日筛选流程
        market_data: 包含所有股票的价格和成交量数据
        """
        results = {
            'strong_blocks': [],      # 强势板块
            'dragon_candidates': [],  # 龙头候选
            'multi_concept_stocks': [] # 多概念叠加股
        }
        
        # 步骤1: 识别强势板块
        strong_blocks = self.analyzer.get_leading_blocks(
            market_data.get('returns', {})
        )
        results['strong_blocks'] = strong_blocks
        
        # 步骤2: 在强势板块中找龙头
        dragon_list = []
        for block_name, block_info in strong_blocks[:3]:  # 只分析前3个强势板块
            leading_stocks = self.analyzer.get_block_leading_stocks(
                block_name, 
                market_data.get('returns', {}),
                top_n=2
            )
            for stock in leading_stocks:
                stock['leading_block'] = block_name
                dragon_list.append(stock)
        
        # 步骤3: 全市场龙头扫描
        price_data = market_data.get('prices', {})
        volume_data = market_data.get('volumes', {})
        all_candidates = self.scanner.get_dragon_candidates(price_data, volume_data, top_n=10)
        
        results['dragon_candidates'] = all_candidates
        
        # 步骤4: 多概念叠加股（潜在轮动龙头）
        multi_concept = self.strategy.find_cross_stocks(min_blocks=4)
        results['multi_concept_stocks'] = multi_concept[:20]
        
        return results
    
    def get_buy_signals(self, market_data):
        """获取买入信号"""
        screening = self.daily_screening(market_data)
        buy_signals = []
        
        for candidate in screening['dragon_candidates'][:5]:
            buy_signals.append({
                'stock_code': candidate['code'],
                'stock_name': candidate['name'],
                'signal_type': 'DRAGON_LEADER',
                'strength_score': candidate['score'],
                'concepts': candidate['blocks'],
                'action': 'BUY',
                'position_ratio': 0.1,  # 建议仓位10%
                'stop_loss': -0.05,      # 5%止损
                'take_profit': 0.15      # 15%止盈
            })
        
        return buy_signals