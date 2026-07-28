# -*- coding: utf-8 -*-
"""
产业研究模块
============

功能：
1. 行业景气度分析 - 通过财务指标、营收增速等判断
2. 政策面分析 - 跟踪政策利好行业
3. 产业链上下游分析 - 确定产业链核心环节
4. 行业轮动判断 - 根据宏观经济周期判断行业轮动

数据来源：
- akshare: 行业板块数据、财务数据
- baostock: 行业分类、财务指标
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from loguru import logger

try:
    import akshare as ak
except ImportError:
    logger.warning("akshare 未安装，部分功能无法使用")

from czsc.utils.retry import AkshareClient, RetryError

try:
    import baostock as bs
except ImportError:
    logger.warning("baostock 未安装，部分功能无法使用")


class IndustryResearch:
    """产业研究分析器"""
    
    # 行业景气度评分权重
    WEIGHTS = {
        'revenue_growth': 0.25,      # 营收增速
        'profit_growth': 0.25,       # 利润增速
        'roe': 0.15,                 # ROE
        'gross_margin': 0.15,        # 毛利率
        'policy_score': 0.10,        # 政策面评分
        'valuation_percentile': 0.10 # 估值分位
    }
    
    # 政策利好行业映射
    POLICY_HOT_SECTORS = {
        '新能源': ['光伏', '风电', '储能', '锂电池', '新能源汽车'],
        '半导体': ['芯片', '集成电路', '半导体设备', '半导体材料'],
        '人工智能': ['AI', '机器学习', '自然语言处理', '计算机视觉'],
        '生物医药': ['创新药', '医疗器械', 'CXO', '疫苗'],
        '军工': ['航空发动机', '军工电子', '卫星导航'],
        '碳中和': ['碳交易', '环保', '节能'],
    }
    
    def __init__(self, data_source: str = 'akshare'):
        """
        初始化产业研究模块
        
        :param data_source: 数据源，支持 'akshare' 或 'baostock'
        """
        self.data_source = data_source
        self._industry_cache = {}
        self._ak_client = AkshareClient(max_retries=3, initial_delay=2.0, requests_per_second=0.5)
        
    def get_industry_list(self) -> pd.DataFrame:
        """获取行业板块列表"""
        try:
            if self.data_source == 'akshare':
                df = self._ak_client.call(ak.stock_board_industry_name_em)
                return df
            else:
                rs = bs.query_stock_industry()
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                return pd.DataFrame(data, columns=rs.fields)
        except RetryError as e:
            logger.error(f"获取行业列表失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取行业列表失败: {e}")
            return pd.DataFrame()
    
    def get_concept_list(self) -> pd.DataFrame:
        """获取概念板块列表"""
        try:
            if self.data_source == 'akshare':
                df = self._ak_client.call(ak.stock_board_concept_name_em)
                return df
            else:
                return pd.DataFrame()
        except RetryError as e:
            logger.error(f"获取概念列表失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取概念列表失败: {e}")
            return pd.DataFrame()
    
    def get_industry_stocks(self, industry_name: str) -> pd.DataFrame:
        """获取行业成分股"""
        try:
            if self.data_source == 'akshare':
                df = self._ak_client.call(ak.stock_board_industry_cons_em, symbol=industry_name)
                return df
            else:
                rs = bs.query_stock_industry()
                data = []
                while rs.next():
                    row = rs.get_row_data()
                    if row[1] == industry_name:
                        data.append(row)
                return pd.DataFrame(data, columns=rs.fields)
        except RetryError as e:
            logger.error(f"获取行业成分股失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取行业成分股失败: {e}")
            return pd.DataFrame()
    
    def calculate_industry_momentum(self, industry_name: str, days: int = 20) -> Dict:
        """
        计算行业动量
        
        :param industry_name: 行业名称
        :param days: 计算周期
        :return: 行业动量指标
        """
        try:
            # 获取行业指数数据
            if self.data_source == 'akshare':
                df = self._ak_client.call(
                    ak.stock_board_industry_hist_em,
                    symbol=industry_name,
                    period="日k",
                    start_date=(datetime.now() - timedelta(days=days*2)).strftime('%Y%m%d'),
                    end_date=datetime.now().strftime('%Y%m%d'),
                    adjust=""
                )
            else:
                return {}
            
            if df.empty:
                return {}
            
            # 计算动量指标
            df['pct_change'] = df['收盘'].pct_change()
            df['ma5'] = df['收盘'].rolling(5).mean()
            df['ma20'] = df['收盘'].rolling(20).mean()
            
            latest = df.iloc[-1]
            momentum = {
                'name': industry_name,
                'current_price': latest['收盘'],
                'pct_change_5d': df['pct_change'].tail(5).sum(),
                'pct_change_20d': df['pct_change'].tail(20).sum(),
                'ma5': latest['ma5'],
                'ma20': latest['ma20'],
                'is_above_ma5': latest['收盘'] > latest['ma5'],
                'is_above_ma20': latest['收盘'] > latest['ma20'],
                'volume_ratio': df['成交量'].tail(5).mean() / df['成交量'].tail(20).mean(),
            }
            
            return momentum
        except RetryError as e:
            logger.error(f"计算行业动量失败（已重试多次）: {e}")
            return {}
        except Exception as e:
            logger.error(f"计算行业动量失败: {e}")
            return {}
    
    def analyze_industry_fundamentals(self, industry_name: str) -> Dict:
        """
        分析行业基本面
        
        :param industry_name: 行业名称
        :return: 基本面分析结果
        """
        try:
            stocks = self.get_industry_stocks(industry_name)
            if stocks.empty:
                return {}
            
            # 获取行业成分股的财务数据
            # 这里简化处理，实际应用中需要获取详细的财务数据
            fundamentals = {
                'name': industry_name,
                'stock_count': len(stocks),
                'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            }
            
            return fundamentals
        except Exception as e:
            logger.error(f"分析行业基本面失败: {e}")
            return {}
    
    def get_policy_hot_sectors(self) -> List[str]:
        """获取政策利好行业"""
        hot_sectors = []
        for sector, sub_sectors in self.POLICY_HOT_SECTORS.items():
            hot_sectors.extend(sub_sectors)
        return hot_sectors
    
    def calculate_industry_score(self, industry_name: str) -> Dict:
        """
        计算行业综合评分
        
        :param industry_name: 行业名称
        :return: 行业评分和详细信息
        """
        try:
            momentum = self.calculate_industry_momentum(industry_name)
            fundamentals = self.analyze_industry_fundamentals(industry_name)
            policy_hot = self.get_policy_hot_sectors()
            
            # 计算政策面评分
            policy_score = 1.0 if industry_name in policy_hot else 0.5
            
            # 计算动量评分
            momentum_score = 0
            if momentum.get('is_above_ma5'):
                momentum_score += 0.3
            if momentum.get('is_above_ma20'):
                momentum_score += 0.3
            if momentum.get('pct_change_5d', 0) > 0:
                momentum_score += 0.2
            if momentum.get('volume_ratio', 1) > 1:
                momentum_score += 0.2
            
            # 综合评分
            total_score = (
                momentum_score * 0.6 +
                policy_score * 0.4
            )
            
            return {
                'name': industry_name,
                'total_score': round(total_score, 3),
                'momentum_score': round(momentum_score, 3),
                'policy_score': round(policy_score, 3),
                'momentum': momentum,
                'fundamentals': fundamentals,
                'rank': '优秀' if total_score >= 0.7 else '良好' if total_score >= 0.5 else '一般'
            }
        except Exception as e:
            logger.error(f"计算行业评分失败: {e}")
            return {}
    
    def find_hot_industries(self, top_n: int = 10) -> List[Dict]:
        """
        寻找热门行业
        
        :param top_n: 返回前N个行业
        :return: 热门行业列表
        """
        try:
            industries = self.get_industry_list()
            if industries.empty:
                return []
            
            results = []
            for _, row in industries.iterrows():
                industry_name = row.iloc[0] if len(row) > 0 else ""
                if industry_name:
                    score_info = self.calculate_industry_score(industry_name)
                    if score_info:
                        results.append(score_info)
            
            # 按总评分排序
            results.sort(key=lambda x: x.get('total_score', 0), reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.error(f"寻找热门行业失败: {e}")
            return []
    
    def analyze_industry_chain(self, industry_name: str) -> Dict:
        """
        分析产业链上下游
        
        :param industry_name: 行业名称
        :return: 产业链分析结果
        """
        # 产业链映射（简化版）
        industry_chain_map = {
            '新能源汽车': {
                '上游': ['锂矿', '钴矿', '镍矿'],
                '中游': ['锂电池', '电机', '电控'],
                '下游': ['整车', '充电桩'],
            },
            '光伏': {
                '上游': ['硅料', '硅片'],
                '中游': ['电池片', '组件'],
                '下游': ['光伏电站', '逆变器'],
            },
            '半导体': {
                '上游': ['半导体材料', '半导体设备'],
                '中游': ['芯片设计', '芯片制造'],
                '下游': ['封测', '应用'],
            },
            '人工智能': {
                '上游': ['算力', '数据'],
                '中游': ['算法', '模型'],
                '下游': ['应用', '服务'],
            },
        }
        
        chain = industry_chain_map.get(industry_name, {
            '上游': [],
            '中游': [],
            '下游': [],
        })
        
        return {
            'industry': industry_name,
            'chain': chain,
            'core_segments': self._identify_core_segments(chain),
        }
    
    def _identify_core_segments(self, chain: Dict) -> List[str]:
        """识别产业链核心环节"""
        core_segments = []
        for segment, industries in chain.items():
            if industries:
                core_segments.append(segment)
        return core_segments
    
    def get_industry_report(self, industry_name: str) -> Dict:
        """
        生成行业研究报告
        
        :param industry_name: 行业名称
        :return: 研究报告
        """
        score_info = self.calculate_industry_score(industry_name)
        chain_info = self.analyze_industry_chain(industry_name)
        
        report = {
            'title': f'{industry_name}行业研究报告',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'industry': industry_name,
            'summary': {
                'total_score': score_info.get('total_score', 0),
                'rank': score_info.get('rank', '未知'),
                'hot': industry_name in self.get_policy_hot_sectors(),
            },
            'details': {
                'momentum': score_info.get('momentum', {}),
                'fundamentals': score_info.get('fundamentals', {}),
                'policy': {
                    'is_hot': industry_name in self.get_policy_hot_sectors(),
                    'related_sectors': self.POLICY_HOT_SECTORS.get(industry_name, []),
                },
                'industry_chain': chain_info,
            },
            'recommendation': self._generate_recommendation(score_info),
        }
        
        return report
    
    def _generate_recommendation(self, score_info: Dict) -> str:
        """根据评分生成投资建议"""
        total_score = score_info.get('total_score', 0)
        
        if total_score >= 0.7:
            return "强烈推荐：行业景气度高，政策面利好，建议重点关注"
        elif total_score >= 0.5:
            return "推荐：行业表现良好，可适当配置"
        elif total_score >= 0.3:
            return "中性：行业表现一般，建议观望"
        else:
            return "谨慎：行业表现较弱，建议规避"
