# -*- coding: utf-8 -*-
"""
板块人气龙头模块
================

功能：
1. 板块热度分析 - 板块资金流入、成交量、涨幅排名
2. 人气股识别 - 多概念叠加、资金关注度高的股票
3. 龙头股识别 - 板块内领涨、抗跌的个股
4. 板块轮动判断 - 板块强弱变化、轮动趋势

核心逻辑：
- 多概念叠加股更容易成为龙头
- 板块内涨停股数量反映板块强度
- 连板股是板块人气的重要指标
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
from loguru import logger

try:
    import akshare as ak
except ImportError:
    logger.warning("akshare 未安装，部分功能无法使用")

from czsc.utils.retry import AkshareClient, RetryError


class BlockPopularity:
    """板块人气龙头分析器"""
    
    def __init__(self, data_source: str = 'akshare'):
        """
        初始化板块人气龙头模块
        
        :param data_source: 数据源
        """
        self.data_source = data_source
        self._block_cache = {}
        self._stock_blocks_cache = {}
        self._ak_client = AkshareClient(max_retries=3, initial_delay=2.0, requests_per_second=0.5)
        
    def get_concept_blocks(self) -> pd.DataFrame:
        """获取概念板块列表"""
        try:
            if self.data_source == 'akshare':
                df = self._ak_client.call(ak.stock_board_concept_name_em)
                return df
            return pd.DataFrame()
        except RetryError as e:
            logger.error(f"获取概念板块失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取概念板块失败: {e}")
            return pd.DataFrame()
    
    def get_industry_blocks(self) -> pd.DataFrame:
        """获取行业板块列表"""
        try:
            if self.data_source == 'akshare':
                df = self._ak_client.call(ak.stock_board_industry_name_em)
                return df
            return pd.DataFrame()
        except RetryError as e:
            logger.error(f"获取行业板块失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取行业板块失败: {e}")
            return pd.DataFrame()
    
    def get_block_stocks(self, block_name: str, block_type: str = 'concept') -> pd.DataFrame:
        """
        获取板块成分股
        
        :param block_name: 板块名称
        :param block_type: 板块类型，concept=概念，industry=行业
        :return: 成分股数据
        """
        try:
            if self.data_source == 'akshare':
                if block_type == 'concept':
                    df = self._ak_client.call(ak.stock_board_concept_cons_em, symbol=block_name)
                else:
                    df = self._ak_client.call(ak.stock_board_industry_cons_em, symbol=block_name)
                return df
            return pd.DataFrame()
        except RetryError as e:
            logger.error(f"获取板块成分股失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取板块成分股失败: {e}")
            return pd.DataFrame()
    
    def build_stock_block_map(self) -> Dict[str, List[str]]:
        """
        构建股票-板块映射
        
        :return: {股票代码: [板块名称列表]}
        """
        if self._stock_blocks_cache:
            return self._stock_blocks_cache
        
        stock_blocks = defaultdict(list)
        
        try:
            # 获取概念板块
            concept_df = self.get_concept_blocks()
            if not concept_df.empty:
                for _, row in concept_df.iterrows():
                    block_name = row.iloc[0] if len(row) > 0 else ""
                    if block_name:
                        stocks_df = self.get_block_stocks(block_name, 'concept')
                        if not stocks_df.empty:
                            for _, stock_row in stocks_df.iterrows():
                                stock_code = stock_row.iloc[0] if len(stock_row) > 0 else ""
                                if stock_code:
                                    stock_blocks[stock_code].append(block_name)
            
            self._stock_blocks_cache = dict(stock_blocks)
            return self._stock_blocks_cache
        except Exception as e:
            logger.error(f"构建股票-板块映射失败: {e}")
            return {}
    
    def find_multi_concept_stocks(self, min_blocks: int = 3) -> List[Dict]:
        """
        寻找多概念叠加股
        
        :param min_blocks: 最少概念数量
        :return: 多概念叠加股列表
        """
        stock_blocks = self.build_stock_block_map()
        
        multi_concept = []
        for stock_code, blocks in stock_blocks.items():
            if len(blocks) >= min_blocks:
                multi_concept.append({
                    'stock_code': stock_code,
                    'block_count': len(blocks),
                    'blocks': blocks,
                    'is_hot': len(blocks) >= 5,  # 5个以上概念视为热门
                })
        
        # 按概念数量排序
        multi_concept.sort(key=lambda x: x['block_count'], reverse=True)
        return multi_concept
    
    def calculate_block_strength(self, block_name: str, block_type: str = 'concept') -> Dict:
        """
        计算板块强度
        
        :param block_name: 板块名称
        :param block_type: 板块类型
        :return: 板块强度指标
        """
        try:
            stocks_df = self.get_block_stocks(block_name, block_type)
            if stocks_df.empty:
                return {}
            
            # 获取成分股的涨跌数据
            # 这里简化处理，实际应用中需要获取实时行情
            strength = {
                'name': block_name,
                'type': block_type,
                'stock_count': len(stocks_df),
                'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            }
            
            return strength
        except Exception as e:
            logger.error(f"计算板块强度失败: {e}")
            return {}
    
    def identify_leaders(self, block_name: str, block_type: str = 'concept', top_n: int = 5) -> List[Dict]:
        """
        识别板块龙头
        
        :param block_name: 板块名称
        :param block_type: 板块类型
        :param top_n: 返回前N只股票
        :return: 龙头股列表
        """
        try:
            stocks_df = self.get_block_stocks(block_name, block_type)
            if stocks_df.empty:
                return []
            
            # 获取多概念叠加信息
            stock_blocks = self.build_stock_block_map()
            
            leaders = []
            for _, row in stocks_df.iterrows():
                stock_code = row.iloc[0] if len(row) > 0 else ""
                stock_name = row.iloc[1] if len(row) > 1 else ""
                
                if stock_code:
                    blocks = stock_blocks.get(stock_code, [])
                    leaders.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'block_name': block_name,
                        'concept_count': len(blocks),
                        'is_multi_concept': len(blocks) >= 3,
                        'is_hot': len(blocks) >= 5,
                    })
            
            # 按概念数量排序
            leaders.sort(key=lambda x: x['concept_count'], reverse=True)
            return leaders[:top_n]
        except Exception as e:
            logger.error(f"识别板块龙头失败: {e}")
            return []
    
    def calculate_block_heat(self, block_name: str, block_type: str = 'concept') -> Dict:
        """
        计算板块热度
        
        :param block_name: 板块名称
        :param block_type: 板块类型
        :return: 板块热度指标
        """
        try:
            strength = self.calculate_block_strength(block_name, block_type)
            leaders = self.identify_leaders(block_name, block_type, top_n=3)
            
            # 计算热度评分
            heat_score = 0
            
            # 板块规模评分（成分股数量）
            stock_count = strength.get('stock_count', 0)
            if stock_count >= 50:
                heat_score += 0.3
            elif stock_count >= 30:
                heat_score += 0.2
            elif stock_count >= 10:
                heat_score += 0.1
            
            # 龙头股质量评分
            hot_leaders = sum(1 for l in leaders if l.get('is_hot'))
            if hot_leaders >= 2:
                heat_score += 0.4
            elif hot_leaders >= 1:
                heat_score += 0.2
            
            # 多概念股数量评分
            multi_concept_count = sum(1 for l in leaders if l.get('is_multi_concept'))
            if multi_concept_count >= 3:
                heat_score += 0.3
            elif multi_concept_count >= 1:
                heat_score += 0.15
            
            return {
                'name': block_name,
                'type': block_type,
                'heat_score': round(heat_score, 3),
                'stock_count': stock_count,
                'leaders': leaders,
                'hot_leaders': hot_leaders,
                'multi_concept_count': multi_concept_count,
                'heat_level': '极高' if heat_score >= 0.8 else '高' if heat_score >= 0.6 else '中' if heat_score >= 0.4 else '低',
            }
        except Exception as e:
            logger.error(f"计算板块热度失败: {e}")
            return {}
    
    def find_hot_blocks(self, block_type: str = 'concept', top_n: int = 10) -> List[Dict]:
        """
        寻找热门板块
        
        :param block_type: 板块类型
        :param top_n: 返回前N个板块
        :return: 热门板块列表
        """
        try:
            if block_type == 'concept':
                blocks_df = self.get_concept_blocks()
            else:
                blocks_df = self.get_industry_blocks()
            
            if blocks_df.empty:
                return []
            
            results = []
            for _, row in blocks_df.iterrows():
                block_name = row.iloc[0] if len(row) > 0 else ""
                if block_name:
                    heat_info = self.calculate_block_heat(block_name, block_type)
                    if heat_info:
                        results.append(heat_info)
            
            # 按热度排序
            results.sort(key=lambda x: x.get('heat_score', 0), reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.error(f"寻找热门板块失败: {e}")
            return []
    
    def analyze_block_rotation(self, block_type: str = 'concept') -> Dict:
        """
        分析板块轮动
        
        :param block_type: 板块类型
        :return: 板块轮动分析结果
        """
        try:
            hot_blocks = self.find_hot_blocks(block_type, top_n=20)
            
            # 分类板块
            strong_blocks = [b for b in hot_blocks if b.get('heat_score', 0) >= 0.6]
            medium_blocks = [b for b in hot_blocks if 0.3 <= b.get('heat_score', 0) < 0.6]
            weak_blocks = [b for b in hot_blocks if b.get('heat_score', 0) < 0.3]
            
            return {
                'analysis_date': datetime.now().strftime('%Y-%m-%d'),
                'block_type': block_type,
                'strong_blocks': strong_blocks,
                'medium_blocks': medium_blocks,
                'weak_blocks': weak_blocks,
                'rotation_suggestion': self._suggest_rotation(strong_blocks, medium_blocks),
            }
        except Exception as e:
            logger.error(f"分析板块轮动失败: {e}")
            return {}
    
    def _suggest_rotation(self, strong_blocks: List, medium_blocks: List) -> str:
        """根据板块强弱给出轮动建议"""
        if len(strong_blocks) >= 3:
            return "强势板块较多，市场热点分散，可关注强势板块中的龙头股"
        elif len(strong_blocks) >= 1:
            return f"强势板块集中，重点关注：{', '.join([b.get('name', '') for b in strong_blocks[:3]])}"
        elif len(medium_blocks) >= 3:
            return "板块强度一般，建议观望或轻仓参与"
        else:
            return "市场整体偏弱，建议空仓观望"
    
    def get_block_report(self, block_name: str, block_type: str = 'concept') -> Dict:
        """
        生成板块研究报告
        
        :param block_name: 板块名称
        :param block_type: 板块类型
        :return: 研究报告
        """
        heat_info = self.calculate_block_heat(block_name, block_type)
        leaders = self.identify_leaders(block_name, block_type, top_n=10)
        
        report = {
            'title': f'{block_name}板块研究报告',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'block_name': block_name,
            'block_type': block_type,
            'summary': {
                'heat_score': heat_info.get('heat_score', 0),
                'heat_level': heat_info.get('heat_level', '未知'),
                'stock_count': heat_info.get('stock_count', 0),
                'leader_count': len(leaders),
            },
            'leaders': leaders,
            'recommendation': self._generate_recommendation(heat_info),
        }
        
        return report
    
    def _generate_recommendation(self, heat_info: Dict) -> str:
        """根据热度生成投资建议"""
        heat_score = heat_info.get('heat_score', 0)
        
        if heat_score >= 0.8:
            return "强烈推荐：板块热度极高，资金关注度高，重点关注龙头股"
        elif heat_score >= 0.6:
            return "推荐：板块热度较高，可适当配置龙头股"
        elif heat_score >= 0.4:
            return "中性：板块热度一般，建议观望为主"
        else:
            return "谨慎：板块热度较低，建议规避"
