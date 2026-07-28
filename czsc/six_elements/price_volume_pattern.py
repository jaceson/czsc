# -*- coding: utf-8 -*-
"""
图形量价模块
============

功能：
1. K线形态识别 - 十字星、锤子线、吞没形态等
2. 成交量分析 - 量价关系、放量缩量
3. 趋势判断 - 均线系统、趋势线
4. 支撑阻力位 - 关键价格位识别
5. 量价背离 - 价涨量缩、价跌量增

核心逻辑：
- 量价齐升：健康上涨
- 量价背离：趋势可能反转
- 缩量回调：可能是洗盘
- 放量突破：趋势确认
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


class PriceVolumePattern:
    """图形量价分析器"""
    
    # K线形态阈值
    PATTERN_THRESHOLDS = {
        'doji_body_ratio': 0.1,      # 十字星实体比例
        'hammer_shadow_ratio': 2.0,  # 锤子线影线比例
        'engulfing_body_ratio': 0.5, # 吞没形态实体比例
    }
    
    # 成交量阈值
    VOLUME_THRESHOLDS = {
        'high_volume_ratio': 2.0,    # 放量阈值
        'low_volume_ratio': 0.5,     # 缩量阈值
    }
    
    # 均线参数
    MA_PERIODS = [5, 10, 20, 60, 120, 250]
    
    def __init__(self):
        """初始化图形量价模块"""
        self._pattern_cache = {}
        
    def identify_kline_patterns(self, opens: List[float], highs: List[float], 
                                lows: List[float], closes: List[float]) -> List[Dict]:
        """
        识别K线形态
        
        :param opens: 开盘价列表
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :return: K线形态列表
        """
        patterns = []
        
        if len(closes) < 3:
            return patterns
        
        # 最近3根K线
        o1, h1, l1, c1 = opens[-3], highs[-3], lows[-3], closes[-3]
        o2, h2, l2, c2 = opens[-2], highs[-2], lows[-2], closes[-2]
        o3, h3, l3, c3 = opens[-1], highs[-1], lows[-1], closes[-1]
        
        # 十字星
        body = abs(c3 - o3)
        total_range = h3 - l3
        if total_range > 0 and body / total_range < self.PATTERN_THRESHOLDS['doji_body_ratio']:
            patterns.append({
                'pattern': '十字星',
                'signal': '犹豫',
                'description': '市场多空平衡，可能变盘',
            })
        
        # 锤子线
        lower_shadow = min(o3, c3) - l3
        upper_shadow = h3 - max(o3, c3)
        if lower_shadow > body * self.PATTERN_THRESHOLDS['hammer_shadow_ratio']:
            if upper_shadow < body:
                patterns.append({
                    'pattern': '锤子线',
                    'signal': '看涨',
                    'description': '下影线长，可能见底',
                })
        
        # 上吊线（高位锤子线）
        if upper_shadow > body * self.PATTERN_THRESHOLDS['hammer_shadow_ratio']:
            if lower_shadow < body:
                patterns.append({
                    'pattern': '上吊线',
                    'signal': '看跌',
                    'description': '上影线长，可能见顶',
                })
        
        # 看涨吞没
        if c2 < o2 and c3 > o3:  # 前阴后阳
            if c3 > o2 and o3 < c2:  # 阳线实体完全包裹阴线实体
                patterns.append({
                    'pattern': '看涨吞没',
                    'signal': '看涨',
                    'description': '多头强势反转',
                })
        
        # 看跌吞没
        if c2 > o2 and c3 < o3:  # 前阳后阴
            if c3 < o2 and o3 > c2:  # 阴线实体完全包裹阳线实体
                patterns.append({
                    'pattern': '看跌吞没',
                    'signal': '看跌',
                    'description': '空头强势反转',
                })
        
        # 早晨之星（三根K线）
        if len(closes) >= 3:
            if (c1 < o1 and  # 第一根阴线
                abs(c2 - o2) < abs(c1 - o1) * 0.3 and  # 第二根小实体
                c3 > o3 and  # 第三根阳线
                c3 > (o1 + c1) / 2):  # 阳线收盘价高于第一根中点
                patterns.append({
                    'pattern': '早晨之星',
                    'signal': '强烈看涨',
                    'description': '底部反转信号',
                })
        
        # 黄昏之星（三根K线）
        if len(closes) >= 3:
            if (c1 > o1 and  # 第一根阳线
                abs(c2 - o2) < abs(c1 - o1) * 0.3 and  # 第二根小实体
                c3 < o3 and  # 第三根阴线
                c3 < (o1 + c1) / 2):  # 阴线收盘价低于第一根中点
                patterns.append({
                    'pattern': '黄昏之星',
                    'signal': '强烈看跌',
                    'description': '顶部反转信号',
                })
        
        return patterns
    
    def analyze_volume_price(self, closes: List[float], volumes: List[float]) -> Dict:
        """
        分析量价关系
        
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :return: 量价分析结果
        """
        if len(closes) < 5 or len(volumes) < 5:
            return {}
        
        # 计算价格变化
        price_change = (closes[-1] - closes[-5]) / closes[-5] * 100
        
        # 计算成交量变化
        avg_vol_5 = np.mean(volumes[-5:])
        avg_vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else avg_vol_5
        vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1
        
        # 判断量价关系
        if price_change > 0 and vol_ratio > 1.5:
            relationship = "量价齐升"
            description = "健康上涨，趋势向好"
            signal = "看涨"
        elif price_change > 0 and vol_ratio < 0.7:
            relationship = "价涨量缩"
            description = "上涨动力不足，可能回调"
            signal = "谨慎"
        elif price_change < 0 and vol_ratio > 1.5:
            relationship = "价跌量增"
            description = "恐慌抛售，可能加速下跌"
            signal = "看跌"
        elif price_change < 0 and vol_ratio < 0.7:
            relationship = "价跌量缩"
            description = "缩量回调，可能是洗盘"
            signal = "观望"
        else:
            relationship = "量价正常"
            description = "无明显异常"
            signal = "中性"
        
        return {
            'price_change_5d': round(price_change, 2),
            'volume_ratio': round(vol_ratio, 2),
            'relationship': relationship,
            'description': description,
            'signal': signal,
        }
    
    def calculate_moving_averages(self, closes: List[float]) -> Dict:
        """
        计算均线系统
        
        :param closes: 收盘价列表
        :return: 均线数据
        """
        ma_data = {}
        
        for period in self.MA_PERIODS:
            if len(closes) >= period:
                ma = np.mean(closes[-period:])
                ma_data[f'ma{period}'] = round(ma, 2)
            else:
                ma_data[f'ma{period}'] = None
        
        # 判断均线排列
        current_price = closes[-1] if closes else 0
        ma_values = [v for v in [ma_data.get(f'ma{p}') for p in self.MA_PERIODS] if v is not None]
        
        if len(ma_values) >= 3:
            if all(ma_values[i] >= ma_values[i+1] for i in range(len(ma_values)-1)):
                arrangement = "多头排列"
                signal = "看涨"
            elif all(ma_values[i] <= ma_values[i+1] for i in range(len(ma_values)-1)):
                arrangement = "空头排列"
                signal = "看跌"
            else:
                arrangement = "交织"
                signal = "中性"
        else:
            arrangement = "未知"
            signal = "中性"
        
        return {
            'ma_data': ma_data,
            'current_price': round(current_price, 2),
            'arrangement': arrangement,
            'signal': signal,
            'above_ma20': current_price > ma_data.get('ma20', 0) if ma_data.get('ma20') else None,
            'above_ma60': current_price > ma_data.get('ma60', 0) if ma_data.get('ma60') else None,
        }
    
    def calculate_support_resistance(self, highs: List[float], lows: List[float], 
                                    closes: List[float]) -> Dict:
        """
        计算支撑阻力位
        
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :return: 支撑阻力位
        """
        if len(closes) < 20:
            return {}
        
        current_price = closes[-1]
        
        # 计算近期高低点
        recent_highs = sorted(highs[-20:], reverse=True)
        recent_lows = sorted(lows[-20:])
        
        # 阻力位（近期高点）
        resistance_levels = [h for h in recent_highs[:3] if h > current_price]
        
        # 支撑位（近期低点）
        support_levels = [l for l in recent_lows[:3] if l < current_price]
        
        # 计算布林带
        if len(closes) >= 20:
            ma20 = np.mean(closes[-20:])
            std20 = np.std(closes[-20:])
            boll_upper = ma20 + 2 * std20
            boll_lower = ma20 - 2 * std20
        else:
            boll_upper = boll_lower = ma20 = 0
        
        return {
            'current_price': round(current_price, 2),
            'resistance_levels': [round(r, 2) for r in resistance_levels],
            'support_levels': [round(s, 2) for s in support_levels],
            'boll_upper': round(boll_upper, 2),
            'boll_lower': round(boll_lower, 2),
            'boll_mid': round(ma20, 2),
        }
    
    def detect_divergence(self, closes: List[float], indicators: List[float]) -> Dict:
        """
        检测背离
        
        :param closes: 收盘价列表
        :param indicators: 指标值列表（如MACD、RSI等）
        :return: 背离分析
        """
        if len(closes) < 20 or len(indicators) < 20:
            return {'divergence': '无', 'signal': '中性'}
        
        # 检测顶背离（价格创新高，指标未创新高）
        price_higher = closes[-1] > closes[-10]
        indicator_higher = indicators[-1] > indicators[-10]
        
        if price_higher and not indicator_higher:
            divergence = "顶背离"
            signal = "看跌"
        elif not price_higher and indicator_higher:
            divergence = "底背离"
            signal = "看涨"
        else:
            divergence = "无背离"
            signal = "中性"
        
        return {
            'divergence': divergence,
            'signal': signal,
            'price_trend': '上涨' if price_higher else '下跌',
            'indicator_trend': '上涨' if indicator_higher else '下跌',
        }
    
    def calculate_trend_strength(self, closes: List[float]) -> Dict:
        """
        计算趋势强度
        
        :param closes: 收盘价列表
        :return: 趋势强度
        """
        if len(closes) < 20:
            return {}
        
        # 计算线性回归斜率
        x = np.arange(len(closes[-20:]))
        y = np.array(closes[-20:])
        
        # 归一化
        x_norm = (x - x.mean()) / x.std()
        y_norm = (y - y.mean()) / y.std()
        
        slope, intercept = np.polyfit(x_norm, y_norm, 1)
        
        # 计算R平方
        y_pred = slope * x_norm + intercept
        ss_res = np.sum((y_norm - y_pred) ** 2)
        ss_tot = np.sum((y_norm - y_norm.mean()) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # 判断趋势
        if slope > 0.3 and r_squared > 0.6:
            trend = "强势上涨"
            strength = "强"
        elif slope > 0.1 and r_squared > 0.4:
            trend = "温和上涨"
            strength = "中"
        elif slope < -0.3 and r_squared > 0.6:
            trend = "强势下跌"
            strength = "强"
        elif slope < -0.1 and r_squared > 0.4:
            trend = "温和下跌"
            strength = "中"
        else:
            trend = "震荡"
            strength = "弱"
        
        return {
            'trend': trend,
            'strength': strength,
            'slope': round(slope, 3),
            'r_squared': round(r_squared, 3),
        }
    
    def get_comprehensive_analysis(self, opens: List[float], highs: List[float], 
                                  lows: List[float], closes: List[float], 
                                  volumes: List[float]) -> Dict:
        """
        获取综合分析结果
        
        :param opens: 开盘价列表
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :return: 综合分析
        """
        patterns = self.identify_kline_patterns(opens, highs, lows, closes)
        volume_price = self.analyze_volume_price(closes, volumes)
        ma_system = self.calculate_moving_averages(closes)
        support_resistance = self.calculate_support_resistance(highs, lows, closes)
        trend = self.calculate_trend_strength(closes)
        
        # 综合信号判断
        bullish_signals = 0
        bearish_signals = 0
        
        for p in patterns:
            if '看涨' in p.get('signal', ''):
                bullish_signals += 1
            elif '看跌' in p.get('signal', ''):
                bearish_signals += 1
        
        if volume_price.get('signal') == '看涨':
            bullish_signals += 1
        elif volume_price.get('signal') == '看跌':
            bearish_signals += 1
        
        if ma_system.get('signal') == '看涨':
            bullish_signals += 1
        elif ma_system.get('signal') == '看跌':
            bearish_signals += 1
        
        if bullish_signals > bearish_signals:
            overall_signal = "看涨"
        elif bearish_signals > bullish_signals:
            overall_signal = "看跌"
        else:
            overall_signal = "中性"
        
        return {
            'patterns': patterns,
            'volume_price': volume_price,
            'ma_system': ma_system,
            'support_resistance': support_resistance,
            'trend': trend,
            'overall_signal': overall_signal,
            'bullish_signals': bullish_signals,
            'bearish_signals': bearish_signals,
        }
    
    def get_pattern_report(self, stock_code: str, opens: List[float], highs: List[float],
                          lows: List[float], closes: List[float], volumes: List[float]) -> Dict:
        """
        生成图形量价报告
        
        :param stock_code: 股票代码
        :param opens: 开盘价列表
        :param highs: 最高价列表
        :param lows: 最低价列表
        :param closes: 收盘价列表
        :param volumes: 成交量列表
        :return: 图形量价报告
        """
        analysis = self.get_comprehensive_analysis(opens, highs, lows, closes, volumes)
        
        report = {
            'title': f'{stock_code}图形量价分析报告',
            'date': datetime.now().strftime('%Y-%m-%d'),
            'stock_code': stock_code,
            'summary': {
                'overall_signal': analysis['overall_signal'],
                'pattern_count': len(analysis['patterns']),
                'volume_relationship': analysis['volume_price'].get('relationship', '未知'),
                'trend': analysis['trend'].get('trend', '未知'),
            },
            'details': analysis,
            'recommendation': self._generate_recommendation(analysis),
        }
        
        return report
    
    def _generate_recommendation(self, analysis: Dict) -> str:
        """根据分析结果生成投资建议"""
        overall_signal = analysis.get('overall_signal', '中性')
        trend = analysis.get('trend', {}).get('trend', '震荡')
        volume_rel = analysis.get('volume_price', {}).get('relationship', '')
        
        if overall_signal == '看涨' and trend in ['强势上涨', '温和上涨']:
            return "强烈推荐：技术面看涨，趋势向上，量价配合良好"
        elif overall_signal == '看涨':
            return "推荐：技术面偏多，可适当关注"
        elif overall_signal == '看跌' and trend in ['强势下跌', '温和下跌']:
            return "谨慎：技术面看跌，趋势向下，建议规避"
        elif overall_signal == '看跌':
            return "观望：技术面偏空，建议等待企稳信号"
        else:
            return "中性：技术面无明显方向，建议观望"
