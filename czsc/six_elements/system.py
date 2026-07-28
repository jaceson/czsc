# -*- coding: utf-8 -*-
"""
六大环节交易系统
================

系统架构：
1. 产业研究 - 行业景气度、政策面、产业链分析
2. 板块人气龙头 - 板块资金关注度、多概念叠加
3. 产业赛道龙头 - 赛道内估值、业绩、成长性
4. 前瞻动态PE - 市盈率预测、估值分位
5. 情绪周期 - 市场情绪周期判断、恐慌贪婪
6. 图形量价 - K线形态、成交量分析、趋势判断

综合评分机制：
- 每个环节独立评分（0-100）
- 加权平均计算综合评分
- 根据综合评分给出投资建议
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from loguru import logger

from czsc.six_elements.industry_research import IndustryResearch
from czsc.six_elements.block_popularity import BlockPopularity
from czsc.six_elements.track_leader import TrackLeader
from czsc.six_elements.forward_pe import ForwardPE
from czsc.six_elements.sentiment_cycle import SentimentCycle
from czsc.six_elements.price_volume_pattern import PriceVolumePattern


class SixElementSystem:
    """六大环节交易系统"""
    
    # 六大环节权重
    ELEMENT_WEIGHTS = {
        'industry_research': 0.15,      # 产业研究
        'block_popularity': 0.20,       # 板块人气龙头
        'track_leader': 0.20,           # 产业赛道龙头
        'forward_pe': 0.15,             # 前瞻动态PE
        'sentiment_cycle': 0.15,        # 情绪周期
        'price_volume_pattern': 0.15,   # 图形量价
    }
    
    def __init__(self, data_source: str = 'akshare'):
        """
        初始化六大环节交易系统
        
        :param data_source: 数据源
        """
        self.data_source = data_source
        
        # 初始化六个模块
        self.industry_research = IndustryResearch(data_source)
        self.block_popularity = BlockPopularity(data_source)
        self.track_leader = TrackLeader(data_source)
        self.forward_pe = ForwardPE(data_source)
        self.sentiment_cycle = SentimentCycle()
        self.price_volume_pattern = PriceVolumePattern()
        
        logger.info("六大环节交易系统初始化完成")
    
    def analyze_industry(self, industry_name: str) -> Dict:
        """
        分析产业研究环节
        
        :param industry_name: 行业名称
        :return: 产业研究分析结果
        """
        try:
            report = self.industry_research.get_industry_report(industry_name)
            score = report.get('summary', {}).get('total_score', 0) * 100
            
            return {
                'element': '产业研究',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['industry_research'],
            }
        except Exception as e:
            logger.error(f"产业研究分析失败: {e}")
            return {'element': '产业研究', 'score': 0, 'error': str(e)}
    
    def analyze_block(self, block_name: str, block_type: str = 'concept') -> Dict:
        """
        分析板块人气龙头环节
        
        :param block_name: 板块名称
        :param block_type: 板块类型
        :return: 板块人气龙头分析结果
        """
        try:
            report = self.block_popularity.get_block_report(block_name, block_type)
            score = report.get('summary', {}).get('heat_score', 0) * 100
            
            return {
                'element': '板块人气龙头',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['block_popularity'],
            }
        except Exception as e:
            logger.error(f"板块人气龙头分析失败: {e}")
            return {'element': '板块人气龙头', 'score': 0, 'error': str(e)}
    
    def analyze_track(self, track_name: str) -> Dict:
        """
        分析产业赛道龙头环节
        
        :param track_name: 赛道名称
        :return: 产业赛道龙头分析结果
        """
        try:
            report = self.track_leader.get_track_report(track_name)
            score = report.get('summary', {}).get('avg_total_score', 0) * 100
            
            return {
                'element': '产业赛道龙头',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['track_leader'],
            }
        except Exception as e:
            logger.error(f"产业赛道龙头分析失败: {e}")
            return {'element': '产业赛道龙头', 'score': 0, 'error': str(e)}
    
    def analyze_valuation(self, stock_code: str) -> Dict:
        """
        分析前瞻动态PE环节
        
        :param stock_code: 股票代码
        :return: 前瞻动态PE分析结果
        """
        try:
            report = self.forward_pe.get_valuation_report(stock_code)
            
            # 计算估值评分
            percentile = report.get('summary', {}).get('percentile', 50)
            valuation_level = report.get('summary', {}).get('valuation_level', '合理')
            
            # 估值越低分数越高
            if valuation_level == '低估':
                score = 90
            elif valuation_level == '合理':
                score = 70
            elif valuation_level == '偏高':
                score = 40
            else:
                score = 20
            
            # 根据分位数调整
            if percentile < 30:
                score = min(100, score + 10)
            elif percentile > 70:
                score = max(0, score - 10)
            
            return {
                'element': '前瞻动态PE',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['forward_pe'],
            }
        except Exception as e:
            logger.error(f"前瞻动态PE分析失败: {e}")
            return {'element': '前瞻动态PE', 'score': 0, 'error': str(e)}
    
    def analyze_sentiment(self, market_data: Dict, sentiment_history: List[float] = None) -> Dict:
        """
        分析情绪周期环节
        
        :param market_data: 市场数据
        :param sentiment_history: 历史情绪数据
        :return: 情绪周期分析结果
        """
        try:
            report = self.sentiment_cycle.get_sentiment_report(market_data, sentiment_history)
            
            # 计算情绪评分
            sentiment_score = report.get('summary', {}).get('sentiment_score', 50)
            stage = report.get('summary', {}).get('stage', '中性')
            
            # 情绪评分转换（恐慌=低分，贪婪=高分，但投资价值相反）
            # 恐慌时投资价值高，贪婪时投资价值低
            if stage in ['极度恐慌', '恐慌']:
                score = 80 + (50 - sentiment_score) / 5
            elif stage in ['犹豫']:
                score = 60
            elif stage in ['贪婪']:
                score = 40
            elif stage in ['狂热', '极度狂热']:
                score = 20 - (sentiment_score - 70) / 5
            else:
                score = 50
            
            score = max(0, min(100, score))
            
            return {
                'element': '情绪周期',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['sentiment_cycle'],
            }
        except Exception as e:
            logger.error(f"情绪周期分析失败: {e}")
            return {'element': '情绪周期', 'score': 0, 'error': str(e)}
    
    def analyze_technical(self, opens: List[float], highs: List[float], 
                         lows: List[float], closes: List[float], 
                         volumes: List[float], stock_code: str = '') -> Dict:
        """
        分析图形量价环节
        
        :param opens: 开盘价列表
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :param stock_code: 股票代码
        :return: 图形量价分析结果
        """
        try:
            report = self.price_volume_pattern.get_pattern_report(
                stock_code, opens, highs, lows, closes, volumes
            )
            
            # 计算技术评分
            overall_signal = report.get('summary', {}).get('overall_signal', '中性')
            trend = report.get('summary', {}).get('trend', '震荡')
            
            if overall_signal == '看涨' and trend in ['强势上涨', '温和上涨']:
                score = 85
            elif overall_signal == '看涨':
                score = 70
            elif overall_signal == '中性':
                score = 50
            elif overall_signal == '看跌':
                score = 30
            else:
                score = 15
            
            return {
                'element': '图形量价',
                'score': round(score, 2),
                'report': report,
                'weight': self.ELEMENT_WEIGHTS['price_volume_pattern'],
            }
        except Exception as e:
            logger.error(f"图形量价分析失败: {e}")
            return {'element': '图形量价', 'score': 0, 'error': str(e)}
    
    def calculate_composite_score(self, element_scores: List[Dict]) -> Dict:
        """
        计算综合评分
        
        :param element_scores: 各环节评分列表
        :return: 综合评分
        """
        total_score = 0
        total_weight = 0
        element_details = []
        
        for item in element_scores:
            score = item.get('score', 0)
            weight = item.get('weight', 0)
            element = item.get('element', '')
            
            total_score += score * weight
            total_weight += weight
            
            element_details.append({
                'element': element,
                'score': score,
                'weight': weight,
                'weighted_score': round(score * weight, 2),
            })
        
        if total_weight > 0:
            composite_score = total_score / total_weight
        else:
            composite_score = 0
        
        # 判断综合评级
        if composite_score >= 80:
            rating = "强烈推荐"
        elif composite_score >= 65:
            rating = "推荐"
        elif composite_score >= 50:
            rating = "中性"
        elif composite_score >= 35:
            rating = "谨慎"
        else:
            rating = "不推荐"
        
        return {
            'composite_score': round(composite_score, 2),
            'rating': rating,
            'element_details': element_details,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def generate_trading_signal(self, composite_result: Dict) -> Dict:
        """
        生成交易信号
        
        :param composite_result: 综合评分结果
        :return: 交易信号
        """
        score = composite_result.get('composite_score', 50)
        rating = composite_result.get('rating', '中性')
        
        if score >= 80:
            action = "强烈买入"
            position = "满仓"
            stop_loss = "-8%"
            take_profit = "+20%"
        elif score >= 65:
            action = "买入"
            position = "半仓"
            stop_loss = "-6%"
            take_profit = "+15%"
        elif score >= 50:
            action = "观望"
            position = "轻仓"
            stop_loss = "-5%"
            take_profit = "+10%"
        elif score >= 35:
            action = "减仓"
            position = "空仓"
            stop_loss = "-3%"
            take_profit = "+5%"
        else:
            action = "卖出"
            position = "空仓"
            stop_loss = "不适用"
            take_profit = "不适用"
        
        return {
            'action': action,
            'position': position,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'confidence': min(100, score),
        }
    
    def run_full_analysis(self, stock_code: str = '', industry_name: str = '',
                         block_name: str = '', track_name: str = '',
                         market_data: Dict = None, price_data: Dict = None) -> Dict:
        """
        运行完整分析
        
        :param stock_code: 股票代码
        :param industry_name: 行业名称
        :param block_name: 板块名称
        :param track_name: 赛道名称
        :param market_data: 市场数据
        :param price_data: 价格数据
        :return: 完整分析结果
        """
        element_scores = []
        
        # 1. 产业研究分析
        if industry_name:
            result = self.analyze_industry(industry_name)
            element_scores.append(result)
        
        # 2. 板块人气龙头分析
        if block_name:
            result = self.analyze_block(block_name)
            element_scores.append(result)
        
        # 3. 产业赛道龙头分析
        if track_name:
            result = self.analyze_track(track_name)
            element_scores.append(result)
        
        # 4. 前瞻动态PE分析
        if stock_code:
            result = self.analyze_valuation(stock_code)
            element_scores.append(result)
        
        # 5. 情绪周期分析
        if market_data:
            result = self.analyze_sentiment(market_data)
            element_scores.append(result)
        
        # 6. 图形量价分析
        if price_data:
            result = self.analyze_technical(
                price_data.get('opens', []),
                price_data.get('highs', []),
                price_data.get('lows', []),
                price_data.get('closes', []),
                price_data.get('volumes', []),
                stock_code
            )
            element_scores.append(result)
        
        # 计算综合评分
        composite_result = self.calculate_composite_score(element_scores)
        
        # 生成交易信号
        trading_signal = self.generate_trading_signal(composite_result)
        
        return {
            'stock_code': stock_code,
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            'element_scores': element_scores,
            'composite_result': composite_result,
            'trading_signal': trading_signal,
        }
    
    def generate_report(self, analysis_result: Dict) -> str:
        """
        生成分析报告
        
        :param analysis_result: 分析结果
        :return: 报告文本
        """
        lines = []
        lines.append("=" * 60)
        lines.append("六大环节交易系统分析报告")
        lines.append("=" * 60)
        lines.append(f"股票代码: {analysis_result.get('stock_code', 'N/A')}")
        lines.append(f"分析日期: {analysis_result.get('analysis_date', 'N/A')}")
        lines.append("")
        
        # 各环节评分
        lines.append("【各环节评分】")
        for item in analysis_result.get('element_scores', []):
            element = item.get('element', '')
            score = item.get('score', 0)
            lines.append(f"  {element}: {score:.2f}分")
        
        lines.append("")
        
        # 综合评分
        composite = analysis_result.get('composite_result', {})
        lines.append(f"【综合评分】{composite.get('composite_score', 0):.2f}分")
        lines.append(f"【综合评级】{composite.get('rating', '未知')}")
        lines.append("")
        
        # 交易信号
        signal = analysis_result.get('trading_signal', {})
        lines.append("【交易信号】")
        lines.append(f"  操作建议: {signal.get('action', '未知')}")
        lines.append(f"  仓位建议: {signal.get('position', '未知')}")
        lines.append(f"  止损位: {signal.get('stop_loss', '未知')}")
        lines.append(f"  止盈位: {signal.get('take_profit', '未知')}")
        lines.append(f"  信心指数: {signal.get('confidence', 0):.0f}%")
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)
