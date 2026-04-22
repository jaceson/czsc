class DragonStockScanner:
    """龙头股扫描器 - 需要接入实时/历史行情数据"""
    
    def __init__(self, strategy):
        self.strategy = strategy
        
    def calculate_strength_score(self, stock_code, price_data, volume_data):
        """
        计算股票强度分数
        维度：涨幅、成交量、换手率、板块地位
        """
        score = 0
        
        # 1. 近期涨幅 (5日、10日、20日)
        if len(price_data) >= 20:
            gain_5d = (price_data[-1] - price_data[-6]) / price_data[-6] if len(price_data) >= 6 else 0
            gain_10d = (price_data[-1] - price_data[-11]) / price_data[-11] if len(price_data) >= 11 else 0
            gain_20d = (price_data[-1] - price_data[-21]) / price_data[-21] if len(price_data) >= 21 else 0
            
            # 涨幅评分
            if gain_5d > 0.2: score += 30
            elif gain_5d > 0.1: score += 20
            elif gain_5d > 0.05: score += 10
            
            if gain_10d > 0.3: score += 25
            elif gain_10d > 0.15: score += 15
            
            if gain_20d > 0.4: score += 20
            elif gain_20d > 0.2: score += 10
        
        # 2. 成交量放大倍数
        if len(volume_data) >= 6:
            avg_volume_5d = np.mean(volume_data[-6:-1])
            current_volume = volume_data[-1]
            volume_ratio = current_volume / avg_volume_5d if avg_volume_5d > 0 else 1
            
            if volume_ratio > 3: score += 25
            elif volume_ratio > 2: score += 15
            elif volume_ratio > 1.5: score += 8
        
        # 3. 概念叠加数量
        concept_count = len(self.strategy.all_stocks.get(stock_code, {}).get('blocks', []))
        score += min(concept_count * 5, 30)
        
        return score
    
    def get_dragon_candidates(self, price_data_dict, volume_data_dict, top_n=10):
        """获取龙头候选股"""
        candidates = []
        
        for code, price_data in price_data_dict.items():
            if code not in volume_data_dict:
                continue
                
            score = self.calculate_strength_score(
                code, 
                price_data, 
                volume_data_dict.get(code, [])
            )
            
            if score > 0:
                candidates.append({
                    'code': code,
                    'name': self.strategy.all_stocks.get(code, {}).get('name', code),
                    'score': score,
                    'blocks': self.strategy.all_stocks.get(code, {}).get('blocks', [])
                })
        
        return sorted(candidates, key=lambda x: x['score'], reverse=True)[:top_n]