# -*- coding: utf-8 -*-
"""
情绪周期模块
============

功能：
1. 市场情绪指标 - PSY、VR、BRAR、CR、MFI等
2. 恐慌贪婪指数 - 综合多指标判断市场情绪
3. 情绪周期阶段 - 识别市场处于哪个情绪周期阶段
4. 极端情绪预警 - 识别市场极端情绪（极度恐慌/极度贪婪）

情绪周期四个阶段：
1. 恐慌阶段 - 市场极度悲观，往往是底部区域
2. 犹豫阶段 - 市场情绪恢复中，趋势不明朗
3. 贪婪阶段 - 市场乐观情绪上升，趋势向上
4. 狂热阶段 - 市场极度乐观，往往是顶部区域
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import OrderedDict
from loguru import logger

try:
    import talib as ta
except ImportError:
    logger.warning("ta-lib 未安装，部分功能无法使用")


class SentimentCycle:
    """情绪周期分析器"""
    
    # 情绪周期阈值
    SENTIMENT_THRESHOLDS = {
        'extreme_fear': 20,      # 极度恐慌
        'fear': 35,              # 恐慌
        'neutral': 50,           # 中性
        'greed': 65,             # 贪婪
        'extreme_greed': 80,     # 极度贪婪
    }
    
    # 情绪指标权重
    INDICATOR_WEIGHTS = {
        'psy': 0.15,           # 心理线
        'vr': 0.15,            # 成交量变异率
        'brar': 0.15,          # 情绪指标
        'cr': 0.10,            # 能量指标
        'mfi': 0.10,           # 资金流向
        'volume_ratio': 0.10,  # 量比
        'amplitude': 0.10,     # 振幅
        'turnover': 0.15,      # 换手率
    }
    
    def __init__(self):
        """初始化情绪周期模块"""
        self._sentiment_cache = {}
        
    def calculate_psy(self, closes: List[float], n: int = 12) -> float:
        """
        计算PSY心理线
        
        :param closes: 收盘价列表
        :param n: 计算周期
        :return: PSY值 (0-100)
        """
        if len(closes) < n + 1:
            return 50.0
        
        up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        psy = up_count / n * 100
        return min(100, max(0, psy))
    
    def calculate_vr(self, closes: List[float], volumes: List[float], n: int = 26) -> float:
        """
        计算VR成交量变异率
        
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :param n: 计算周期
        :return: VR值
        """
        if len(closes) < n + 1 or len(volumes) < n + 1:
            return 100.0
        
        vol_up = 0
        vol_down = 0
        vol_total = 0
        
        for i in range(1, n + 1):
            vol_total += volumes[-i]
            if closes[-i] > closes[-i-1]:
                vol_up += volumes[-i]
            elif closes[-i] < closes[-i-1]:
                vol_down += volumes[-i]
        
        if vol_down == 0:
            return 200.0
        
        vr = (vol_up + vol_total / 2) / (vol_down + vol_total / 2) * 100
        return min(300, max(0, vr))
    
    def calculate_brar(self, opens: List[float], highs: List[float], 
                       lows: List[float], closes: List[float], n: int = 26) -> Dict:
        """
        计算BRAR情绪指标
        
        :param opens: 开盘价列表
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param n: 计算周期
        :return: AR和BR值
        """
        if len(closes) < n + 1:
            return {'ar': 100, 'br': 100}
        
        sum_h_o = sum(highs[-i] - opens[-i] for i in range(1, n + 1))
        sum_o_l = sum(opens[-i] - lows[-i] for i in range(1, n + 1))
        
        ar = sum_h_o / sum_o_l * 100 if sum_o_l > 0 else 100
        
        sum_h_pc = sum(max(0, highs[-i] - closes[-i-1]) for i in range(1, n + 1))
        sum_pc_l = sum(max(0, closes[-i-1] - lows[-i]) for i in range(1, n + 1))
        
        br = sum_h_pc / sum_pc_l * 100 if sum_pc_l > 0 else 100
        
        return {'ar': min(300, max(0, ar)), 'br': min(500, max(0, br))}
    
    def calculate_cr(self, highs: List[float], lows: List[float], 
                     closes: List[float], n: int = 26) -> float:
        """
        计算CR能量指标
        
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param n: 计算周期
        :return: CR值
        """
        if len(closes) < n + 1:
            return 100.0
        
        mid_prev = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(1, n + 1)]
        
        sum_h_mid = sum(max(0, highs[-i] - mid_prev[i-1]) for i in range(1, n) if i < len(mid_prev))
        sum_mid_l = sum(max(0, mid_prev[i-1] - lows[-i]) for i in range(1, n) if i < len(mid_prev))
        
        cr = sum_h_mid / sum_mid_l * 100 if sum_mid_l > 0 else 100
        return min(300, max(0, cr))
    
    def calculate_mfi(self, highs: List[float], lows: List[float], 
                      closes: List[float], volumes: List[float], n: int = 14) -> float:
        """
        计算MFI资金流向指标
        
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :param n: 计算周期
        :return: MFI值 (0-100)
        """
        if len(closes) < n + 1:
            return 50.0
        
        typical_prices = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(n, 0, -1)]
        
        pos_mf = 0
        neg_mf = 0
        
        for i in range(1, len(typical_prices)):
            rmf = typical_prices[i] * volumes[-(n-i+1)]
            if typical_prices[i] > typical_prices[i-1]:
                pos_mf += rmf
            elif typical_prices[i] < typical_prices[i-1]:
                neg_mf += rmf
        
        if neg_mf == 0:
            return 100.0
        
        mfr = pos_mf / neg_mf
        mfi = 100 - (100 / (1 + mfr))
        return min(100, max(0, mfi))
    
    def calculate_sentiment_score(self, market_data: Dict) -> Dict:
        """
        计算市场情绪综合评分
        
        :param market_data: 市场数据
        :return: 情绪评分
        """
        closes = market_data.get('closes', [])
        volumes = market_data.get('volumes', [])
        opens = market_data.get('opens', [])
        highs = market_data.get('highs', [])
        lows = market_data.get('lows', [])
        
        # 计算各项指标
        psy = self.calculate_psy(closes)
        vr = self.calculate_vr(closes, volumes)
        brar = self.calculate_brar(opens, highs, lows, closes)
        cr = self.calculate_cr(highs, lows, closes)
        mfi = self.calculate_mfi(highs, lows, closes, volumes)
        
        # 计算量比
        if len(volumes) >= 20:
            vol_ratio = np.mean(volumes[-5:]) / np.mean(volumes[-20:])
        else:
            vol_ratio = 1.0
        
        # 计算振幅
        if len(closes) >= 2:
            amplitude = (max(highs[-5:]) - min(lows[-5:])) / closes[-5] * 100 if len(highs) >= 5 else 0
        else:
            amplitude = 0
        
        # 计算换手率（简化版）
        turnover = market_data.get('turnover_rate', 1.0)
        
        # 标准化各项指标到0-100
        indicators = {
            'psy': psy,
            'vr': min(100, vr / 3),  # VR通常0-300，标准化到0-100
            'brar': min(100, brar['ar'] / 3),  # AR通常0-300
            'cr': min(100, cr / 3),  # CR通常0-300
            'mfi': mfi,
            'volume_ratio': min(100, vol_ratio * 30),  # 量比通常0-3
            'amplitude': min(100, amplitude * 5),  # 振幅通常0-20%
            'turnover': min(100, turnover * 10),  # 换手率通常0-10%
        }
        
        # 计算综合情绪评分
        total_score = sum(
            indicators[k] * self.INDICATOR_WEIGHTS[k] 
            for k in self.INDICATOR_WEIGHTS.keys()
        )
        
        return {
            'indicators': indicators,
            'total_score': round(total_score, 2),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
    
    def identify_sentiment_stage(self, sentiment_score: float) -> Dict:
        """
        识别情绪周期阶段
        
        :param sentiment_score: 情绪评分 (0-100)
        :return: 情绪阶段信息
        """
        thresholds = self.SENTIMENT_THRESHOLDS
        
        if sentiment_score <= thresholds['extreme_fear']:
            stage = "极度恐慌"
            description = "市场极度悲观，往往是底部区域，可考虑逢低布局"
            action = "买入"
        elif sentiment_score <= thresholds['fear']:
            stage = "恐慌"
            description = "市场情绪低迷，可能接近底部，可关注超跌反弹机会"
            action = "观望/轻仓买入"
        elif sentiment_score <= thresholds['neutral']:
            stage = "犹豫"
            description = "市场情绪恢复中，趋势不明朗，建议观望"
            action = "观望"
        elif sentiment_score <= thresholds['greed']:
            stage = "贪婪"
            description = "市场乐观情绪上升，趋势向上，可顺势而为"
            action = "持有/加仓"
        elif sentiment_score <= thresholds['extreme_greed']:
            stage = "狂热"
            description = "市场极度乐观，可能接近顶部，注意风险"
            action = "减仓/观望"
        else:
            stage = "极度狂热"
            description = "市场情绪极端亢奋，往往是顶部区域，建议逢高减仓"
            action = "卖出"
        
        return {
            'stage': stage,
            'description': description,
            'action': action,
            'score': sentiment_score,
            'risk_level': '高' if sentiment_score > 70 or sentiment_score < 30 else '中',
        }
    
    def detect_extreme_sentiment(self, sentiment_score: float) -> Optional[Dict]:
        """
        检测极端情绪
        
        :param sentiment_score: 情绪评分
        :return: 极端情绪预警
        """
        thresholds = self.SENTIMENT_THRESHOLDS
        
        if sentiment_score <= thresholds['extreme_fear']:
            return {
                'type': '极度恐慌',
                'level': 'warning',
                'message': '市场情绪极度恐慌，可能是买入机会',
                'score': sentiment_score,
            }
        elif sentiment_score >= thresholds['extreme_greed']:
            return {
                'type': '极度贪婪',
                'level': 'warning',
                'message': '市场情绪极度贪婪，注意风险',
                'score': sentiment_score,
            }
        
        return None
    
    def analyze_sentiment_trend(self, sentiment_history: List[float]) -> Dict:
        """
        分析情绪趋势
        
        :param sentiment_history: 历史情绪评分列表
        :return: 情绪趋势分析
        """
        if len(sentiment_history) < 2:
            return {'trend': '未知', 'momentum': 0}
        
        recent = sentiment_history[-5:] if len(sentiment_history) >= 5 else sentiment_history
        
        # 计算趋势
        trend_values = np.polyfit(range(len(recent)), recent, 1)
        momentum = trend_values[0]
        
        if momentum > 2:
            trend = "快速上升"
        elif momentum > 0.5:
            trend = "缓慢上升"
        elif momentum > -0.5:
            trend = "横盘整理"
        elif momentum > -2:
            trend = "缓慢下降"
        else:
            trend = "快速下降"
        
        return {
            'trend': trend,
            'momentum': round(momentum, 3),
            'latest_score': sentiment_history[-1],
            'avg_score': round(np.mean(sentiment_history), 2),
        }
    
    def get_sentiment_report(self, market_data: Dict, sentiment_history: List[float] = None) -> Dict:
        """
        生成情绪周期报告
        
        :param market_data: 市场数据
        :param sentiment_history: 历史情绪评分
        :return: 情绪报告
        """
        sentiment = self.calculate_sentiment_score(market_data)
        stage = self.identify_sentiment_stage(sentiment['total_score'])
        extreme = self.detect_extreme_sentiment(sentiment['total_score'])
        
        trend = {}
        if sentiment_history:
            trend = self.analyze_sentiment_trend(sentiment_history)
        
        report = {
            'title': '市场情绪周期研究报告',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'summary': {
                'sentiment_score': sentiment['total_score'],
                'stage': stage['stage'],
                'action': stage['action'],
                'extreme_warning': extreme is not None,
            },
            'details': {
                'indicators': sentiment['indicators'],
                'stage_info': stage,
                'extreme_sentiment': extreme,
                'trend': trend,
            },
            'recommendation': self._generate_recommendation(stage, extreme, trend),
        }
        
        return report
    
    def _generate_recommendation(self, stage: Dict, extreme: Optional[Dict], trend: Dict) -> str:
        """根据情绪阶段生成投资建议"""
        stage_name = stage.get('stage', '')
        action = stage.get('action', '')
        
        if extreme:
            if extreme['type'] == '极度恐慌':
                return "极度恐慌预警：市场情绪极度悲观，可能是中长期买入机会，建议分批建仓"
            else:
                return "极度贪婪预警：市场情绪极度乐观，注意控制仓位，可适当减仓"
        
        if stage_name == '恐慌':
            return "恐慌阶段：市场情绪低迷，建议关注超跌优质股，轻仓试探"
        elif stage_name == '犹豫':
            return "犹豫阶段：市场方向不明，建议观望为主，等待趋势明朗"
        elif stage_name == '贪婪':
            return "贪婪阶段：市场情绪向好，可顺势而为，关注强势板块龙头"
        elif stage_name == '狂热':
            return "狂热阶段：市场情绪亢奋，注意风险，建议逐步减仓"
        else:
            return "情绪中性：保持正常仓位，关注市场变化"
