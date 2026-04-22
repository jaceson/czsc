import sys
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class DragonStockStrategy:
    """龙头战法选股策略"""
    
    def __init__(self, block_data_path):
        self.tdx_api = TdxHq_API()
        try:
            # ping shtdx.gtjas.com 或者 hq.cjis.cn
            if tdx_api.connect('114.28.173.137', 7709):
                pass
                # data = tdx_api.get_index_bars(9, 1, '880001', 0, 100)
                # # 转为DataFrame便于分析
                # df = tdx_api.to_df(data)
                # print(df.head())
            else:
                print(f"通达信4PI 初始化失败")
        except Exception as e:
            print(f"通达信API 初始化失败: {e}")
            sys.exit(-1)

        with open(block_data_path, 'r', encoding='utf-8') as f:
            self.block_data = json.load(f)
        self.all_stocks = self._extract_all_stocks()
        
    def _extract_all_stocks(self):
        """提取所有股票信息"""
        stocks = {}
        for block_name, block_info in self.block_data.items():
            for stock in block_info['stocks']:
                code = stock['stock_code']
                name = stock['stock_name']
                if code not in stocks:
                    stocks[code] = {
                        'name': name,
                        'blocks': []
                    }
                stocks[code]['blocks'].append(block_name)
        return stocks
    
    def get_hot_blocks(self, limit=10):
        """获取热门板块（成分股数量最多的板块）"""
        block_sizes = []
        for block_name, block_info in self.block_data.items():
            block_sizes.append({
                'block_name': block_name,
                'stock_count': len(block_info['stocks']),
                'block_code': block_info['block_code']
            })
        return sorted(block_sizes, key=lambda x: x['stock_count'], reverse=True)[:limit]
    
    def find_cross_stocks(self, min_blocks=3):
        """寻找多概念叠加的股票（可能成为龙头）"""
        cross_stocks = []
        for code, info in self.all_stocks.items():
            if len(info['blocks']) >= min_blocks:
                cross_stocks.append({
                    'code': code,
                    'name': info['name'],
                    'blocks': info['blocks'],
                    'block_count': len(info['blocks'])
                })
        return sorted(cross_stocks, key=lambda x: x['block_count'], reverse=True)
    
    def get_block_stocks(self, block_name):
        """获取指定板块的成分股"""
        if block_name in self.block_data:
            return self.block_data[block_name]['stocks']
        return []