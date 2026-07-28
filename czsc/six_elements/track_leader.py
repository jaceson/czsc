# -*- coding: utf-8 -*-
"""
产业赛道龙头模块
================

功能：
1. 赛道识别 - 识别高成长性赛道
2. 龙头筛选 - 从赛道中筛选龙头股
3. 成长性分析 - 评估公司成长潜力
4. 竞争格局分析 - 行业竞争格局、市场份额

龙头筛选标准：
- 市值领先
- 业绩增长确定性高
- 行业地位稳固（市占率高）
- 估值合理
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


class TrackLeader:
    """产业赛道龙头分析器"""
    
    # 赛道分类
    TRACK_CATEGORIES = {
        '新能源': {
            'sub_tracks': ['光伏', '风电', '储能', '锂电池', '新能源汽车'],
            'growth_keywords': ['碳中和', '新能源', '清洁能源'],
        },
        '科技': {
            'sub_tracks': ['半导体', '人工智能', '云计算', '大数据', '物联网'],
            'growth_keywords': ['数字经济', '信创', '国产替代'],
        },
        '医药': {
            'sub_tracks': ['创新药', '医疗器械', 'CXO', '疫苗', '中药'],
            'growth_keywords': ['老龄化', '医保', '创新'],
        },
        '消费': {
            'sub_tracks': ['白酒', '食品饮料', '家电', '服装', '旅游'],
            'growth_keywords': ['消费升级', '品牌', '渠道'],
        },
        '金融': {
            'sub_tracks': ['银行', '保险', '券商', '金融科技'],
            'growth_keywords': ['利率', '监管', '创新'],
        },
    }
    
    # 龙头筛选标准权重
    LEADER_WEIGHTS = {
        'market_cap': 0.20,           # 市值
        'revenue_growth': 0.20,       # 营收增速
        'profit_growth': 0.20,        # 利润增速
        'roe': 0.15,                  # ROE
        'market_share': 0.15,         # 市场份额
        'valuation': 0.10,            # 估值合理性
    }
    
    def __init__(self, data_source: str = 'akshare'):
        """
        初始化产业赛道龙头模块
        
        :param data_source: 数据源
        """
        self.data_source = data_source
        self._track_cache = {}
        self._ak_client = AkshareClient(max_retries=3, initial_delay=2.0, requests_per_second=0.5)
        
    def get_track_list(self) -> List[str]:
        """获取所有赛道"""
        tracks = []
        for category, info in self.TRACK_CATEGORIES.items():
            tracks.extend(info['sub_tracks'])
        return tracks
    
    def get_track_category(self, track_name: str) -> Optional[str]:
        """获取赛道所属类别"""
        for category, info in self.TRACK_CATEGORIES.items():
            if track_name in info['sub_tracks']:
                return category
        return None
    
    def get_track_stocks(self, track_name: str) -> pd.DataFrame:
        """
        获取赛道成分股
        
        :param track_name: 赛道名称
        :return: 成分股数据
        """
        try:
            if self.data_source == 'akshare':
                # 尝试从概念板块获取
                df = self._ak_client.call(ak.stock_board_concept_cons_em, symbol=track_name)
                if df.empty:
                    # 尝试从行业板块获取
                    df = self._ak_client.call(ak.stock_board_industry_cons_em, symbol=track_name)
                return df
            return pd.DataFrame()
        except RetryError as e:
            logger.error(f"获取赛道成分股失败（已重试多次）: {e}")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取赛道成分股失败: {e}")
            return pd.DataFrame()
    
    def calculate_financial_score(self, stock_code: str) -> Dict:
        """
        计算财务评分
        
        :param stock_code: 股票代码
        :return: 财务评分
        """
        # 这里简化处理，实际应用中需要获取详细的财务数据
        # 包括：营收增速、利润增速、ROE、毛利率等
        
        financial_score = {
            'stock_code': stock_code,
            'revenue_growth_score': np.random.uniform(0.5, 1.0),  # 示例
            'profit_growth_score': np.random.uniform(0.5, 1.0),
            'roe_score': np.random.uniform(0.5, 1.0),
            'gross_margin_score': np.random.uniform(0.5, 1.0),
        }
        
        # 计算综合财务评分
        weights = [0.3, 0.3, 0.2, 0.2]
        scores = [
            financial_score['revenue_growth_score'],
            financial_score['profit_growth_score'],
            financial_score['roe_score'],
            financial_score['gross_margin_score'],
        ]
        financial_score['total_score'] = sum(w * s for w, s in zip(weights, scores))
        
        return financial_score
    
    def calculate_growth_score(self, stock_code: str) -> Dict:
        """
        计算成长性评分
        
        :param stock_code: 股票代码
        :return: 成长性评分
        """
        # 简化处理
        growth_score = {
            'stock_code': stock_code,
            'revenue_cagr': np.random.uniform(0.1, 0.3),  # 示例：营收复合增长率
            'profit_cagr': np.random.uniform(0.1, 0.3),   # 示例：利润复合增长率
            'market_growth': np.random.uniform(0.05, 0.2), # 示例：市场增长率
        }
        
        # 计算成长性评分
        growth_score['total_score'] = (
            growth_score['revenue_cagr'] * 0.4 +
            growth_score['profit_cagr'] * 0.4 +
            growth_score['market_growth'] * 0.2
        )
        
        return growth_score
    
    def identify_leader(self, track_name: str, top_n: int = 5) -> List[Dict]:
        """
        识别赛道龙头
        
        :param track_name: 赛道名称
        :param top_n: 返回前N只股票
        :return: 龙头股列表
        """
        try:
            stocks_df = self.get_track_stocks(track_name)
            if stocks_df.empty:
                return []
            
            leaders = []
            for _, row in stocks_df.iterrows():
                stock_code = row.iloc[0] if len(row) > 0 else ""
                stock_name = row.iloc[1] if len(row) > 1 else ""
                
                if stock_code:
                    # 计算各项评分
                    financial = self.calculate_financial_score(stock_code)
                    growth = self.calculate_growth_score(stock_code)
                    
                    # 综合评分
                    total_score = (
                        financial['total_score'] * 0.5 +
                        growth['total_score'] * 0.5
                    )
                    
                    leaders.append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'track_name': track_name,
                        'financial_score': round(financial['total_score'], 3),
                        'growth_score': round(growth['total_score'], 3),
                        'total_score': round(total_score, 3),
                        'financial_details': financial,
                        'growth_details': growth,
                    })
            
            # 按总评分排序
            leaders.sort(key=lambda x: x['total_score'], reverse=True)
            return leaders[:top_n]
        except Exception as e:
            logger.error(f"识别赛道龙头失败: {e}")
            return []
    
    def analyze_competition(self, track_name: str) -> Dict:
        """
        分析赛道竞争格局
        
        :param track_name: 赛道名称
        :return: 竞争格局分析
        """
        try:
            leaders = self.identify_leader(track_name, top_n=10)
            
            if not leaders:
                return {}
            
            # 计算市场集中度（简化版）
            scores = [l['total_score'] for l in leaders]
            total = sum(scores) if scores else 1
            
            # 计算CR3、CR5
            sorted_scores = sorted(scores, reverse=True)
            cr3 = sum(sorted_scores[:3]) / total if len(sorted_scores) >= 3 else 1
            cr5 = sum(sorted_scores[:5]) / total if len(sorted_scores) >= 5 else 1
            
            # 判断竞争格局
            if cr3 >= 0.6:
                pattern = "寡头垄断"
            elif cr5 >= 0.5:
                pattern = "高度集中"
            elif cr3 >= 0.3:
                pattern = "适度集中"
            else:
                pattern = "分散竞争"
            
            return {
                'track_name': track_name,
                'competition_pattern': pattern,
                'cr3': round(cr3, 3),
                'cr5': round(cr5, 3),
                'leaders': leaders[:5],
                'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            }
        except Exception as e:
            logger.error(f"分析赛道竞争格局失败: {e}")
            return {}
    
    def find_high_growth_tracks(self, top_n: int = 5) -> List[Dict]:
        """
        寻找高成长赛道
        
        :param top_n: 返回前N个赛道
        :return: 高成长赛道列表
        """
        try:
            tracks = self.get_track_list()
            results = []
            
            for track in tracks:
                leaders = self.identify_leader(track, top_n=3)
                if leaders:
                    # 计算赛道平均成长性
                    avg_growth = np.mean([l['growth_score'] for l in leaders])
                    avg_total = np.mean([l['total_score'] for l in leaders])
                    
                    results.append({
                        'track_name': track,
                        'category': self.get_track_category(track),
                        'avg_growth_score': round(avg_growth, 3),
                        'avg_total_score': round(avg_total, 3),
                        'leader_count': len(leaders),
                        'leaders': leaders,
                    })
            
            # 按平均成长性排序
            results.sort(key=lambda x: x['avg_growth_score'], reverse=True)
            return results[:top_n]
        except Exception as e:
            logger.error(f"寻找高成长赛道失败: {e}")
            return []
    
    def get_track_report(self, track_name: str) -> Dict:
        """
        生成赛道研究报告
        
        :param track_name: 赛道名称
        :return: 研究报告
        """
        leaders = self.identify_leader(track_name, top_n=10)
        competition = self.analyze_competition(track_name)
        category = self.get_track_category(track_name)
        
        report = {
            'title': f'{track_name}赛道研究报告',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'track_name': track_name,
            'category': category,
            'summary': {
                'leader_count': len(leaders),
                'competition_pattern': competition.get('competition_pattern', '未知'),
                'avg_total_score': np.mean([l['total_score'] for l in leaders]) if leaders else 0,
            },
            'leaders': leaders,
            'competition': competition,
            'recommendation': self._generate_recommendation(leaders, competition),
        }
        
        return report
    
    def _generate_recommendation(self, leaders: List, competition: Dict) -> str:
        """根据龙头质量和竞争格局生成投资建议"""
        if not leaders:
            return "赛道数据不足，建议观望"
        
        avg_score = np.mean([l['total_score'] for l in leaders])
        pattern = competition.get('competition_pattern', '')
        
        if avg_score >= 0.7 and pattern in ['寡头垄断', '高度集中']:
            return "强烈推荐：赛道成长性好，竞争格局清晰，龙头优势明显"
        elif avg_score >= 0.5:
            return "推荐：赛道表现良好，可关注龙头股"
        elif avg_score >= 0.3:
            return "中性：赛道表现一般，建议观望"
        else:
            return "谨慎：赛道表现较弱，建议规避"
