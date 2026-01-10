# coding: utf-8
"""
大鱼吃小鱼形态选股策略 - 调试版
策略逻辑：
1. 前面出现小鱼的形态（ABC2*2 < 小鱼阈值，持续一段时间）
2. 在小鱼尾部突然出现大鱼嘴（ABC2*2 >= 大鱼阈值，且出现买入信号）
3. 出现大鱼嘴时选入股票

用于调试，可以分别测试各个条件，找出限制选股结果的原因
使用方法：将OUT后面的条件改为要测试的条件
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

# 从 FormulaSignal 导入指标计算函数
from CZSCStragegy_FormulaSignal import calculate_formula_indicators

# 统计变量
plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

# ========== 参数设置区 ==========
N1 = 10          # EMA周期
N2 = 14          # 威廉指标周期
N3 = 9           # RSI周期
成交额阈值1 = 2000   # 成交额下限（万元）
成交额阈值2 = 8000   # 成交额上限（万元）
涨幅阈值1 = 2.9     # 涨幅阈值1（%）
涨幅阈值2 = 4.0     # 涨幅阈值2（%）
涨幅阈值3 = 5.0     # 涨幅阈值3（%）

# ========== 大鱼吃小鱼形态参数 ==========
小鱼阈值 = 30        # 小鱼形态的ABC2*2上限值，可调
大鱼阈值 = 40        # 大鱼嘴的ABC2*2下限值，可调
涨幅跳跃阈值 = 10    # 从小鱼到大鱼嘴的涨幅跳跃最小值，可调

# ========== 市场环境判断 ==========
启用市场过滤 = 1     # 0=关闭市场过滤，1=启用市场过滤
大盘指数代码 = "sh.000001"  # 上证指数代码

# 全局变量：大盘指数数据缓存
_index_data_cache = None

def get_index_data(start_date='2000-01-01'):
    """
    获取大盘指数数据（缓存）
    
    参数:
        start_date: 开始日期
    
    返回:
        DataFrame: 大盘指数数据
    """
    global _index_data_cache
    if _index_data_cache is None:
        try:
            _index_data_cache = get_local_stock_data(大盘指数代码, start_date)
            if _index_data_cache is None or len(_index_data_cache) == 0:
                print(f"警告：无法获取大盘指数数据 {大盘指数代码}，市场过滤将被禁用")
                _index_data_cache = pd.DataFrame()
        except Exception as e:
            print(f"警告：获取大盘指数数据失败: {e}，市场过滤将被禁用")
            _index_data_cache = pd.DataFrame()
    return _index_data_cache

def calculate_market_filter(df):
    """
    计算市场过滤条件
    
    参数:
        df: 股票数据DataFrame（用于对齐日期）
    
    返回:
        pandas Series: 市场过滤条件布尔序列
    """
    if 启用市场过滤 == 0:
        # 关闭市场过滤，返回全True
        return pd.Series([True] * len(df), index=df.index)
    
    index_df = get_index_data()
    if index_df is None or len(index_df) == 0:
        # 无法获取指数数据，返回全True（不进行过滤）
        return pd.Series([True] * len(df), index=df.index)
    
    # 合并股票数据和指数数据（按日期对齐）
    merged_df = pd.merge(df[['date']], index_df[['date', 'close']], on='date', how='left')
    merged_df = merged_df.sort_values('date').reset_index(drop=True)
    
    # 计算大盘指标
    大盘指数 = merged_df['close'].values
    大盘MA20 = MA(大盘指数, 20)
    大盘MA60 = MA(大盘指数, 60)
    
    # 大盘趋势:=MA(大盘指数,20) > MA(大盘指数,60);
    大盘趋势 = 大盘MA20 > 大盘MA60
    
    # 市场强度:=(大盘指数-MA(大盘指数,20))/MA(大盘指数,20)*100;
    市场强度 = (大盘指数 - 大盘MA20) / (大盘MA20 + 1e-10) * 100
    
    # 市场过滤:=IF(启用市场过滤=1,大盘趋势 AND 市场强度 > -3,1);
    市场过滤 = pd.Series([True] * len(df), index=df.index)
    if 启用市场过滤 == 1:
        # 对齐到原始df的索引
        for i, date in enumerate(df['date']):
            idx = merged_df[merged_df['date'] == date].index
            if len(idx) > 0:
                j = idx[0]
                if j < len(大盘趋势) and j < len(市场强度):
                    市场过滤.iloc[i] = 大盘趋势[j] & (市场强度[j] > -3)
    
    return 市场过滤.fillna(True)  # 缺失值视为True（不进行过滤）

def calculate_bigfish_indicators(df):
    """
    计算大鱼吃小鱼策略所需的所有指标
    基于 FormulaSignal 的基础指标，但需要根据用户公式调整部分参数
    
    参数:
        df: 股票数据DataFrame，需要包含：close, high, low, volume, amount
    
    返回:
        DataFrame: 添加了所有计算指标的DataFrame
    """
    # 使用 FormulaSignal 的基础指标计算（ABC1-ABC13）
    ndf = calculate_formula_indicators(df)
    
    # ========== 简化均线系统 ==========
    # ABC14:=EMA(CLOSE,20);
    # ABC15:=EMA(CLOSE,30);
    # ABC16:=EMA(CLOSE,60);
    # ABC17:=EMA(CLOSE,120);
    # ABC18:=EMA(CLOSE,250);
    ABC14 = EMA(ndf['close'].values, 20)
    ABC15 = EMA(ndf['close'].values, 30)
    ABC16 = EMA(ndf['close'].values, 60)
    ABC17 = EMA(ndf['close'].values, 120)
    ABC18 = EMA(ndf['close'].values, 250)
    
    ndf['ABC14'] = ABC14
    ndf['ABC15'] = ABC15
    ndf['ABC16'] = ABC16
    ndf['ABC17'] = ABC17
    ndf['ABC18'] = ABC18
    
    # ABC27:=MAX(MAX(ABC15,ABC16),ABC17);
    ABC27 = MAX(MAX(ABC15, ABC16), ABC17)
    ndf['ABC27'] = ABC27
    
    # ABC28:=MIN(MIN(ABC15,ABC16),ABC17);
    ABC28 = MIN(MIN(ABC15, ABC16), ABC17)
    ndf['ABC28'] = ABC28
    
    # ABC29:=MAX(ABC27,ABC18);
    ABC29 = MAX(ABC27, ABC18)
    ndf['ABC29'] = ABC29
    
    # ABC30:=MIN(ABC28,ABC18);
    ABC30 = MIN(ABC28, ABC18)
    ndf['ABC30'] = ABC30
    
    # ABC33:=ABC29;
    # ABC34:=ABC30;
    ABC33 = ABC29
    ABC34 = ABC30
    ndf['ABC33'] = ABC33
    ndf['ABC34'] = ABC34
    
    # ABC35:=ABC33/ABC34;
    ABC35 = ABC33 / (ABC34 + 1e-10)
    ndf['ABC35'] = ABC35
    
    # ABC36:=LOW/ABC27;
    ABC36 = ndf['low'].values / (ABC27 + 1e-10)
    ndf['ABC36'] = ABC36
    
    # ========== 成交额过滤 ==========
    # ABC38:=AMOUNT/10000;
    ABC38 = ndf['amount'].values / 10000
    ndf['ABC38'] = ABC38
    
    # ABC39:=LLV(ABC38,2) > 成交额阈值1 AND ABC38 > 成交额阈值2;
    ABC39 = (LLV(ABC38, 2) > 成交额阈值1) & (ABC38 > 成交额阈值2)
    ndf['ABC39'] = ABC39
    
    # ========== 趋势过滤条件 ==========
    # ABC37:=ABC35 < 1.3 AND REF(ABC36,1) < 1.05 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08;
    ABC36_PREV = REF(ABC36, 1)
    ABC37 = (ABC35 < 1.3) & (ABC36_PREV < 1.05) & (ndf['close'].values > ABC14) & (ndf['close'].values > ABC33) & (ABC36 < 1.08)
    ndf['ABC37'] = ABC37
    
    # ========== 成交量确认增强 ==========
    VOL_PREV = REF(ndf['volume'].values, 1)
    VOL_MA5 = MA(ndf['volume'].values, 5)
    VOL_MA20 = MA(ndf['volume'].values, 20)
    
    量能放大1 = ndf['volume'].values > VOL_PREV * 1.5
    量能放大2 = ndf['volume'].values > VOL_MA5 * 1.2
    量能放大3 = ndf['volume'].values > VOL_MA20 * 1.1
    量能确认 = 量能放大1 & (量能放大2 | 量能放大3)
    ndf['量能确认'] = 量能确认
    
    # ========== 涨跌幅计算 ==========
    # ABC40:=CLOSE/REF(CLOSE,1);
    ABC40 = ndf['close'].values / (REF(ndf['close'].values, 1) + 1e-10)
    ndf['ABC40'] = ABC40
    
    # ========== 买入信号1：均线突破 ==========
    # ABC41:=EMA(CLOSE,5);
    # ABC42:=EMA(CLOSE,10);
    # ABC43:=EMA(CLOSE,20);
    ABC41 = EMA(ndf['close'].values, 5)
    ABC42 = EMA(ndf['close'].values, 10)
    ABC43 = EMA(ndf['close'].values, 20)
    
    # ABC44:=MAX(MAX(ABC41,ABC42),ABC43);
    # ABC45:=MIN(MIN(ABC41,ABC42),ABC43);
    ABC44 = MAX(MAX(ABC41, ABC42), ABC43)
    ABC45 = MIN(MIN(ABC41, ABC42), ABC43)
    
    ndf['ABC41'] = ABC41
    ndf['ABC42'] = ABC42
    ndf['ABC43'] = ABC43
    ndf['ABC44'] = ABC44
    ndf['ABC45'] = ABC45
    
    # ABC46:=LOW < ABC45 AND CLOSE > ABC44 AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC46 = (ndf['low'].values < ABC45) & (ndf['close'].values > ABC44) & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    ndf['ABC46'] = ABC46
    
    # ========== 买入信号2：典型价格突破 ==========
    # ABC47:=(HIGH+LOW+CLOSE)/3;
    ABC47 = (ndf['high'].values + ndf['low'].values + ndf['close'].values) / 3
    ndf['ABC47'] = ABC47
    
    # ABC48:=(ABC47-MA(ABC47,81))*1000/(15*AVEDEV(ABC47,81));
    ABC48 = (ABC47 - MA(ABC47, 81)) * 1000 / (15 * AVEDEV(ABC47, 81) + 1e-10)
    ndf['ABC48'] = ABC48
    
    # ABC49:=CROSS(ABC48,100) AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC48_PREV = REF(ABC48, 1)
    ABC49_CROSS = (ABC48_PREV <= 100) & (ABC48 > 100)
    ABC49 = ABC49_CROSS & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    ndf['ABC49'] = ABC49
    
    # ========== 买入信号3：均线粘合突破 ==========
    # ABC50:=MA(CLOSE,30);
    # ABC51:=MA(CLOSE,60);
    # ABC52:=MA(CLOSE,90);
    # ABC53:=MA(CLOSE,240);
    ABC50 = MA(ndf['close'].values, 30)
    ABC51 = MA(ndf['close'].values, 60)
    ABC52 = MA(ndf['close'].values, 90)
    ABC53 = MA(ndf['close'].values, 240)
    
    ndf['ABC50'] = ABC50
    ndf['ABC51'] = ABC51
    ndf['ABC52'] = ABC52
    ndf['ABC53'] = ABC53
    
    # ABC54:=ABS(ABC50/ABC51-1);
    # ABC55:=ABS(ABC51/ABC52-1);
    # ABC56:=ABS(ABC50/ABC52-1);
    ABC54 = ABS(ABC50 / (ABC51 + 1e-10) - 1)
    ABC55 = ABS(ABC51 / (ABC52 + 1e-10) - 1)
    ABC56 = ABS(ABC50 / (ABC52 + 1e-10) - 1)
    
    ndf['ABC54'] = ABC54
    ndf['ABC55'] = ABC55
    ndf['ABC56'] = ABC56
    
    # ABC57:=CLOSE/REF(CLOSE,1);
    ABC57 = ABC40
    ndf['ABC57'] = ABC57
    
    # ABC58:=ABC57-1;
    ABC58 = ABC57 - 1
    ndf['ABC58'] = ABC58
    
    # ABC59:=(ABC50+ABC51+ABC52)/3;
    ABC59 = (ABC50 + ABC51 + ABC52) / 3
    ndf['ABC59'] = ABC59
    
    # ABC60:=IF(CLOSE > ABC59*1.04 AND CLOSE < ABC59*1.15,1,0);
    ABC60 = IF((ndf['close'].values > ABC59 * 1.04) & (ndf['close'].values < ABC59 * 1.15), 1, 0)
    ndf['ABC60'] = ABC60
    
    # ABC61:=ABC53/REF(ABC53,20);
    ABC53_PREV20 = REF(ABC53, 20)
    ABC61 = ABC53 / (ABC53_PREV20 + 1e-10)
    ndf['ABC61'] = ABC61
    
    # ABC62:=ABS(ABC61-1);
    ABC62 = ABS(ABC61 - 1)
    ndf['ABC62'] = ABC62
    
    # ABC63:=IF(ABC62 < 0.04,1,0);
    ABC63 = IF(ABC62 < 0.04, 1, 0)
    ndf['ABC63'] = ABC63
    
    # ABC64:=IF(ABC54 < 0.04 AND ABC55 < 0.04 AND ABC56 < 0.04 AND ABC58 > 0.04 AND ABC60=1 AND ABC63=1 AND ABC59 > ABC53,1,0);
    ABC64 = IF((ABC54 < 0.04) & (ABC55 < 0.04) & (ABC56 < 0.04) & (ABC58 > 0.04) & (ABC60 == 1) & (ABC63 == 1) & (ABC59 > ABC53), 1, 0)
    ndf['ABC64'] = ABC64
    
    # ABC65:=ABC64 AND 量能确认 AND ABC39 AND ABC37;
    ABC65 = (ABC64 == 1) & 量能确认 & ABC39 & ABC37
    ndf['ABC65'] = ABC65
    
    # ========== 买入信号4：强势突破 ==========
    # ABC66:=ABC35 < 1.15 AND REF(ABC36,1) < 1.04 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08 AND ABC40 > (1+涨幅阈值2/100) AND 量能确认 AND ABC39 AND ABC37;
    ABC66 = (ABC35 < 1.15) & (ABC36_PREV < 1.04) & (ndf['close'].values > ABC14) & (ndf['close'].values > ABC33) & (ABC36 < 1.08) & (ABC40 > (1 + 涨幅阈值2/100)) & 量能确认 & ABC39 & ABC37
    ndf['ABC66'] = ABC66
    
    # ========== 买入信号5：低位反弹 ==========
    # ABC67:=LOW < ABC34 AND CLOSE > ABC33 AND ABC40 > (1+涨幅阈值3/100) AND 量能确认;
    ABC67 = (ndf['low'].values < ABC34) & (ndf['close'].values > ABC33) & (ABC40 > (1 + 涨幅阈值3/100)) & 量能确认
    ndf['ABC67'] = ABC67
    
    # ========== 综合买入信号 ==========
    # ABC68:=ABC46 OR ABC49 OR ABC65 OR ABC66 OR ABC67;
    ABC68 = ABC46 | ABC49 | ABC65 | ABC66 | ABC67
    ndf['ABC68'] = ABC68
    
    # 计算市场过滤
    市场过滤 = calculate_market_filter(df)
    ndf['市场过滤'] = 市场过滤.values
    
    # ABC80:=ABC68 AND 市场过滤;
    ABC80 = ABC68 & 市场过滤.values
    ndf['ABC80'] = ABC80
    
    return ndf

def get_bigfish_eat_smallfish_condition(symbol, df, debug_output='大鱼吃小鱼形态'):
    """
    获取大鱼吃小鱼形态选股条件
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
        debug_output: 调试输出条件，可选值：
            '测试买入信号' 或 'ABC80' - 买入信号数量
            '测试大鱼嘴' - 大鱼嘴数量
            '测试小鱼形态' - 小鱼形态数量
            '测试条件1' 或 '条件1' - 当前是大鱼嘴
            '测试条件2' 或 '条件2' - 前面有小鱼形态
            '测试条件3' 或 '条件3' - 从小鱼突然跳到大鱼
            '测试条件4' 或 '条件4' - 确保不是一直在大鱼状态
            '测试成交额' - 成交额过滤
            '测试成交量' - 成交量确认
            '测试市场' - 市场过滤
            '大鱼吃小鱼形态' - 综合选股条件（默认）
    
    返回:
        pandas Series: 买入条件布尔序列
    """
    if df is None or len(df) < 250:  # 需要足够的数据计算指标
        return pd.Series([False] * len(df), index=df.index)
    
    # 计算所有指标
    ndf = calculate_bigfish_indicators(df)
    
    # ========== 大鱼吃小鱼形态识别 ==========
    # 当前ABC2*2值
    当前鱼值 = ndf['ABC2'] * 2
    ndf['当前鱼值'] = 当前鱼值
    
    # 判断当前是否是大鱼嘴：ABC2*2超过大鱼阈值，且出现买入信号
    当前是大鱼嘴 = (当前鱼值 >= 大鱼阈值) & ndf['ABC80'].fillna(False)
    
    # 获取前N天的鱼值
    当前鱼值_PREV1 = REF(当前鱼值, 1)
    当前鱼值_PREV2 = REF(当前鱼值, 2)
    当前鱼值_PREV3 = REF(当前鱼值, 3)
    当前鱼值_PREV4 = REF(当前鱼值, 4)
    当前鱼值_PREV5 = REF(当前鱼值, 5)
    当前鱼值_PREV6 = REF(当前鱼值, 6)
    当前鱼值_PREV7 = REF(当前鱼值, 7)
    当前鱼值_PREV8 = REF(当前鱼值, 8)
    当前鱼值_PREV9 = REF(当前鱼值, 9)
    当前鱼值_PREV10 = REF(当前鱼值, 10)
    
    # 判断最近3天小鱼
    最近3天小鱼 = (当前鱼值_PREV1 < 小鱼阈值) | (当前鱼值_PREV2 < 小鱼阈值) | (当前鱼值_PREV3 < 小鱼阈值)
    
    # 判断最近5天小鱼
    最近5天小鱼 = 最近3天小鱼 | (当前鱼值_PREV4 < 小鱼阈值) | (当前鱼值_PREV5 < 小鱼阈值)
    
    # 判断最近10天小鱼
    最近10天小鱼 = 最近5天小鱼 | (当前鱼值_PREV6 < 小鱼阈值) | (当前鱼值_PREV7 < 小鱼阈值) | (当前鱼值_PREV8 < 小鱼阈值) | (当前鱼值_PREV9 < 小鱼阈值) | (当前鱼值_PREV10 < 小鱼阈值)
    
    # 判断最近连续几天是小鱼（更严格的条件）
    连续2天小鱼 = (当前鱼值_PREV1 < 小鱼阈值) & (当前鱼值_PREV2 < 小鱼阈值)
    连续3天小鱼 = 连续2天小鱼 & (当前鱼值_PREV3 < 小鱼阈值)
    
    # 判断是否从小鱼突然跳到大鱼：涨幅跳跃
    涨幅跳跃 = 当前鱼值 - 当前鱼值_PREV1
    涨幅跳跃大 = 涨幅跳跃 >= 涨幅跳跃阈值
    
    # 判断昨天或前天是小鱼，今天突然跳到大鱼
    昨天小鱼今大鱼 = (当前鱼值_PREV1 < 小鱼阈值) & (当前鱼值 >= 大鱼阈值)
    前天小鱼今大鱼 = (当前鱼值_PREV2 < 小鱼阈值) & (当前鱼值_PREV1 < 小鱼阈值 * 1.2) & (当前鱼值 >= 大鱼阈值)
    
    # ========== 大鱼吃小鱼形态选股条件 ==========
    # 条件1：当前出现大鱼嘴（必须条件）
    条件1 = 当前是大鱼嘴
    
    # 条件2：前面有小鱼形态（最近3-10天内有小鱼，且最近连续2-3天是小鱼）
    条件2 = 最近10天小鱼 & (连续2天小鱼 | 连续3天小鱼)
    
    # 条件3：从小鱼突然跳到大鱼（涨幅跳跃明显，或昨天/前天是小鱼今天是大鱼）
    条件3 = ((涨幅跳跃大 & (当前鱼值_PREV1 < 小鱼阈值)) | 昨天小鱼今大鱼 | 前天小鱼今大鱼)
    
    # 条件4：确保不是一直在大鱼状态（避免选到已经是大鱼的股票）
    条件4 = (当前鱼值_PREV1 < 大鱼阈值) & (当前鱼值_PREV2 < 大鱼阈值)
    
    # 综合选股条件
    大鱼吃小鱼形态 = 条件1 & 条件2 & 条件3 & 条件4
    
    # ========== 调试测试条件 ==========
    # 测试1：买入信号数量
    测试买入信号 = ndf['ABC80'].fillna(False)
    
    # 测试2：大鱼嘴数量
    测试大鱼嘴 = 当前鱼值 >= 大鱼阈值
    
    # 测试3：小鱼形态数量
    测试小鱼形态 = 最近10天小鱼
    
    # 测试4-7：条件1-4（已在上面定义）
    # 条件1 = 当前是大鱼嘴
    # 条件2 = 最近10天小鱼 & (连续2天小鱼 | 连续3天小鱼)
    # 条件3 = ((涨幅跳跃大 & (当前鱼值_PREV1 < 小鱼阈值)) | 昨天小鱼今大鱼 | 前天小鱼今大鱼)
    # 条件4 = (当前鱼值_PREV1 < 大鱼阈值) & (当前鱼值_PREV2 < 大鱼阈值)
    
    # 测试8：成交额过滤
    测试成交额 = ndf['ABC39'].fillna(False)
    
    # 测试9：成交量确认
    测试成交量 = ndf['量能确认'].fillna(False)
    
    # 测试10：市场过滤
    测试市场 = ndf['市场过滤'].fillna(False)
    
    # 根据调试输出参数返回相应的条件
    if debug_output == '测试买入信号' or debug_output == 'ABC80':
        output_condition = 测试买入信号
    elif debug_output == '测试大鱼嘴':
        output_condition = 测试大鱼嘴
    elif debug_output == '测试小鱼形态':
        output_condition = 测试小鱼形态
    elif debug_output == '测试条件1' or debug_output == '条件1':
        output_condition = 条件1
    elif debug_output == '测试条件2' or debug_output == '条件2':
        output_condition = 条件2
    elif debug_output == '测试条件3' or debug_output == '条件3':
        output_condition = 条件3
    elif debug_output == '测试条件4' or debug_output == '条件4':
        output_condition = 条件4
    elif debug_output == '测试成交额':
        output_condition = 测试成交额
    elif debug_output == '测试成交量':
        output_condition = 测试成交量
    elif debug_output == '测试市场':
        output_condition = 测试市场
    elif debug_output == '大鱼吃小鱼形态':
        output_condition = 大鱼吃小鱼形态
    else:
        # 默认返回大鱼吃小鱼形态
        output_condition = 大鱼吃小鱼形态
    
    # 处理NaN值（将NaN视为False），并确保索引与原始df一致
    # output_condition = pd.Series(output_condition.fillna(False).values, index=df.index)
    output_condition = pd.Series(output_condition, index=df.index).fillna(False)

    return output_condition

def get_bigfish_eat_smallfish_buy_point(symbol, df, debug_output='大鱼吃小鱼形态'):
    """
    获取大鱼吃小鱼形态买入点（第二天开盘价买入）
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
        debug_output: 调试输出条件
    """
    last_start_index = -1
    buy_con = get_bigfish_eat_smallfish_condition(symbol, df, debug_output)
    
    if not df[buy_con].empty:
        selected_indexs = df[buy_con].index
        for idx in selected_indexs:
            signal_date = df['date'][idx]
            start_index = df.iloc[df['date'].values == signal_date].index[0]
            
            # 避免频繁买入（至少间隔hold_days天）
            if last_start_index > 0 and (start_index - last_start_index) <= hold_days:
                continue
            
            # 第二天开盘价买入
            buy_index = start_index + 1
            if buy_index >= len(df):
                continue
            
            # 计算指标以获取详细信息
            ndf = calculate_bigfish_indicators(df)
            当前鱼值 = ndf['ABC2'].iloc[start_index] * 2
            前一天鱼值 = REF(ndf['ABC2'].values, 1)[start_index] * 2 if start_index > 0 else 0
            
            buy_date = df['date'].iloc[buy_index]
            buy_price = df['open'].iloc[buy_index]  # 第二天开盘价
            
            print(f"{symbol} [{debug_output}] 信号日期：{signal_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}，当前鱼值：{当前鱼值:.2f}，前一天鱼值：{前一天鱼值:.2f}")
            
            max_val = -1000
            last_start_index = start_index
            
            # 计算持有期收益（从买入日第二天开始计算）
            for day_offset in range(1, hold_days + 1):
                sell_index = buy_index + day_offset
                if sell_index < len(df):
                    stock_close = df['close'].iloc[sell_index]
                    ratio = round(100 * (stock_close - buy_price) / buy_price, 2)
                    ratio_map[day_offset].append(ratio)
                    max_val = max(max_val, ratio)
            
            if max_val > 0:
                plus_list.append(max_val)
                print(f"  最大收益: {max_val:.2f}%")
            else:
                minus_list.append(max_val)
                print(f"  最大亏损: {max_val:.2f}%")

def print_statistics(title, arr):
    """
    打印统计信息：平均值、最大值、最小值、50%和95%的百分位数
    参考 CZSCStragegy_Goldenline.py 的实现
    
    参数:
        title: 统计标题
        arr: 数据数组
    """
    if len(arr) == 0:
        print(f"{title}: 无数据")
        return
    
    # 计算平均值
    average = np.mean(arr)
    
    # 计算最大值
    max_value = np.max(arr)
    
    # 计算最小值
    min_value = np.min(arr)
    
    # 计算 50% 和 95% 的百分位数
    percentile_50 = np.percentile(arr, 50)
    percentile_95 = np.percentile(arr, 95)
    
    # 输出结果
    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 的百分位数：{percentile_50:.2f}")
    print(f"    95% 的百分位数：{percentile_95:.2f}")

def print_console(s_plus_list, s_minus_list, s_ratio_map, debug_output='ABC80'):
    """
    打印统计结果（参考 CZSCStragegy_Goldenline.py）
    """
    print("=" * 80)
    print(f"大鱼吃小鱼形态选股策略统计结果 [调试输出: {debug_output}]")
    print("=" * 80)
    print("正收益次数：" + str(len(s_plus_list)))
    if len(s_minus_list) > 0 or len(s_plus_list):
        print("正收益占比：" + str(round(100 * len(s_plus_list) / (len(s_minus_list) + len(s_plus_list)), 2)) + "%")
    
    total = 0
    for x in range(0, len(s_plus_list)):
        total += s_plus_list[x]
    print("总的正收益：" + str(round(total, 2)))
    
    total = 0
    for x in range(0, len(s_minus_list)):
        total += s_minus_list[x]
    print("总的负收益：" + str(round(total, 2)))
    
    # 打印总体统计
    all_returns = s_plus_list + s_minus_list
    if len(all_returns) > 0:
        print_statistics('总收益：', all_returns)
    if len(s_plus_list) > 0:
        print_statistics('正收益：', s_plus_list)
    if len(s_minus_list) > 0:
        print_statistics('负收益：', s_minus_list)
    
    # 每天统计
    for x in range(1, hold_days + 1):
        print("第 {} 天：".format(x))
        res_list = s_ratio_map[x]
        if len(res_list) == 0:
            print("    无数据")
            continue
            
        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for idx in range(0, len(res_list)):
            ratio = res_list[idx]
            if ratio > 0:
                plus_num += 1
                plus_val += ratio
            else:
                minus_num += 1
                minus_val += ratio
        print("     正收益次数：" + str(plus_num))
        if plus_num > 0 or minus_num > 0:
            print("     正收益占比：" + str(round(100 * plus_num / (plus_num + minus_num), 2)) + "%")
        print("     总的正收益：" + str(round(plus_val, 2)))
        print("     总的负收益：" + str(round(minus_val, 2)))
        
        # 使用辅助函数打印详细统计信息
        if len(res_list) > 0:
            print_statistics("第 {} 天：".format(x), res_list)

def main():
    """主函数：执行选股策略"""
    # ========== 调试输出设置 ==========
    # 可以修改这里的值来测试不同的条件
    # 可选值：
    #   '测试买入信号' 或 'ABC80' - 买入信号数量
    #   '测试大鱼嘴' - 大鱼嘴数量
    #   '测试小鱼形态' - 小鱼形态数量
    #   '测试条件1' 或 '条件1' - 当前是大鱼嘴
    #   '测试条件2' 或 '条件2' - 前面有小鱼形态
    #   '测试条件3' 或 '条件3' - 从小鱼突然跳到大鱼
    #   '测试条件4' 或 '条件4' - 确保不是一直在大鱼状态
    #   '测试成交额' - 成交额过滤
    #   '测试成交量' - 成交量确认
    #   '测试市场' - 市场过滤
    #   '大鱼吃小鱼形态' - 综合选股条件（默认）
    debug_output_list = ['大鱼吃小鱼形态','测试买入信号','测试大鱼嘴','测试小鱼形态','测试条件1','测试条件2','测试条件3','测试条件4','测试成交额','测试成交量','测试市场','大鱼吃小鱼形态']
    debug_output = '大鱼吃小鱼形态'  # 默认输出完整选股条件
    if len(sys.argv) > 1 and int(sys.argv[1])<len(debug_output_list):
        debug_output = debug_output_list[int(sys.argv[1])]
    print("=" * 80)
    print("大鱼吃小鱼形态选股策略 - 调试版")
    print("=" * 80)
    print("策略条件：")
    print("1. 前面出现小鱼的形态（ABC2*2 < {}，持续一段时间）".format(小鱼阈值))
    print("2. 在小鱼尾部突然出现大鱼嘴（ABC2*2 >= {}，且出现买入信号）".format(大鱼阈值))
    print("3. 出现大鱼嘴时选入股票")
    print("=" * 80)
    print("参数设置：")
    print(f"  小鱼阈值: {小鱼阈值}")
    print(f"  大鱼阈值: {大鱼阈值}")
    print(f"  涨幅跳跃阈值: {涨幅跳跃阈值}")
    print(f"  启用市场过滤: {启用市场过滤}")
    print(f"  调试输出: {debug_output}")
    print("=" * 80)
    print("提示：可以修改代码中的 debug_output 变量来测试不同的条件")
    print("  可选值：")
    print("    '测试买入信号' 或 'ABC80' - 买入信号数量")
    print("    '测试大鱼嘴' - 大鱼嘴数量")
    print("    '测试小鱼形态' - 小鱼形态数量")
    print("    '测试条件1' 或 '条件1' - 当前是大鱼嘴")
    print("    '测试条件2' 或 '条件2' - 前面有小鱼形态")
    print("    '测试条件3' 或 '条件3' - 从小鱼突然跳到大鱼")
    print("    '测试条件4' 或 '条件4' - 确保不是一直在大鱼状态")
    print("    '测试成交额' - 成交额过滤")
    print("    '测试成交量' - 成交量确认")
    print("    '测试市场' - 市场过滤")
    print("    '大鱼吃小鱼形态' - 综合选股条件（默认）")
    print("=" * 80)
    
    # 获取所有股票代码
    all_symbols = get_daily_symbols()
    print(f"共 {len(all_symbols)} 只股票待筛选")
    print("=" * 80)
    
    # 遍历所有股票
    for idx, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{idx + 1} / {len(all_symbols)}")
        
        try:
            # 获取股票数据
            df = get_local_stock_data(symbol, '2000-01-01')
            if df is None or len(df) < 250:  # 需要足够的历史数据
                continue
            
            # 获取买入点
            get_bigfish_eat_smallfish_buy_point(symbol, df, debug_output)
            
            # 分阶段打印统计结果
            if (idx + 1) % 100 == 0:
                print_console(plus_list, minus_list, ratio_map, debug_output)
        
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # 最终统计
    print_console(plus_list, minus_list, ratio_map, debug_output)

if __name__ == '__main__':
    main()
