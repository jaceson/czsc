# coding: utf-8
"""
周线MACD背离+金叉选股策略
策略条件：
1. 周线走势出现MACD底背离（价格创新低，但MACD没有创新低）
2. 最后一个交易日周线MACD出现金叉（DIF上穿DEA）
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

def detect_macd_divergence(df, lookback_period=30):
    """
    检测MACD底背离
    底背离：价格创新低，但MACD（DIF）没有创新低
    
    参数:
        df: 包含close和MACD指标的DataFrame
        lookback_period: 回看周期，用于寻找低点
    
    返回:
        bool: 是否存在底背离
    """
    if len(df) < lookback_period + 5:
        return False
    
    # 获取最近的数据用于分析
    recent_df = df.tail(lookback_period).copy()
    close_prices = recent_df['close'].values
    dif_values = recent_df['DIF'].values
    
    # 找到最近的两个局部低点
    # 使用滚动窗口找到局部最低点（前后各2个周期内的最低点）
    window = 3
    local_lows_price = []
    local_lows_dif = []
    local_lows_idx = []
    
    for i in range(window, len(close_prices) - window):
        # 检查是否是局部低点（价格）
        is_local_low = True
        for j in range(i - window, i + window + 1):
            if j != i and close_prices[j] < close_prices[i]:
                is_local_low = False
                break
        
        if is_local_low:
            local_lows_price.append(close_prices[i])
            local_lows_dif.append(dif_values[i])
            local_lows_idx.append(i)
    
    # 如果找到的局部低点少于2个，返回False
    if len(local_lows_price) < 2:
        return False
    
    # 找到最近的两个低点
    # 最后一个低点应该是最新的
    if local_lows_idx[-1] < len(close_prices) - 5:
        # 如果最后一个低点太早，可能没有背离
        return False
    
    # 比较最近的两个低点
    last_low_idx = local_lows_idx[-1]
    last_low_price = local_lows_price[-1]
    last_low_dif = local_lows_dif[-1]
    
    # 找到前一个低点
    prev_low_idx = local_lows_idx[-2]
    prev_low_price = local_lows_price[-2]
    prev_low_dif = local_lows_dif[-2]
    
    # 底背离条件：
    # 1. 当前低点的价格低于前一个低点
    # 2. 当前低点的DIF高于前一个低点（或至少不更低）
    price_divergence = last_low_price < prev_low_price
    macd_divergence = last_low_dif > prev_low_dif
    
    if price_divergence and macd_divergence:
        return True
    
    # 如果只有两个低点，检查是否满足条件
    # 也可以检查是否有更早的低点形成背离
    if len(local_lows_price) >= 3:
        # 检查最近的低点与更早的低点
        for i in range(len(local_lows_price) - 2, -1, -1):
            if local_lows_idx[i] < last_low_idx:
                if close_prices[local_lows_idx[i]] > last_low_price and dif_values[local_lows_idx[i]] < last_low_dif:
                    return True
    
    return False

def detect_macd_golden_cross(df):
    """
    检测MACD金叉
    金叉：DIF上穿DEA
    
    参数:
        df: 包含DIF和DEA的DataFrame
    
    返回:
        bool: 最后一个交易日是否出现金叉
    """
    if len(df) < 2:
        return False
    
    # 获取最后两天的数据
    last_dif = df['DIF'].iloc[-1]
    last_dea = df['DEA'].iloc[-1]
    prev_dif = df['DIF'].iloc[-2]
    prev_dea = df['DEA'].iloc[-2]
    
    # 金叉：前一天DIF < DEA，今天DIF > DEA
    golden_cross = (prev_dif < prev_dea) and (last_dif > last_dea)
    
    return golden_cross

def check_weekly_macd_strategy(symbol, start_date='2020-01-01'):
    """
    检查股票是否符合周线MACD背离+金叉策略
    
    参数:
        symbol: 股票代码
        start_date: 开始日期
    
    返回:
        tuple: (是否符合条件, 详细信息字典)
    """
    try:
        # 获取周线数据
        df = get_local_stock_data(symbol, start_date, frequency='w')
        
        if df is None or len(df) < 50:  # 需要足够的历史数据
            return False, None
        
        # 计算MACD指标
        dif, dea, macd = MACD(df['close'].values)
        df['DIF'] = dif
        df['DEA'] = dea
        df['MACD'] = macd
        
        # 去除NaN值
        df = df.dropna()
        
        if len(df) < 30:
            return False, None
        
        # 检测MACD底背离
        has_divergence = detect_macd_divergence(df, lookback_period=20)
        
        # 检测MACD金叉
        has_golden_cross = detect_macd_golden_cross(df)
        
        # 两个条件都满足
        if has_divergence and has_golden_cross:
            info = {
                'symbol': symbol,
                'last_date': df['date'].iloc[-1],
                'last_close': df['close'].iloc[-1],
                'last_dif': df['DIF'].iloc[-1],
                'last_dea': df['DEA'].iloc[-1],
                'last_macd': df['MACD'].iloc[-1],
            }
            return True, info
        
        return False, None
        
    except Exception as e:
        print(f"检查 {symbol} 时出错: {e}")
        return False, None

def main():
    """主函数：执行选股策略"""
    print("=" * 80)
    print("周线MACD背离+金叉选股策略")
    print("=" * 80)
    print("策略条件：")
    print("1. 周线走势出现MACD底背离（价格创新低，但MACD没有创新低）")
    print("2. 最后一个交易日周线MACD出现金叉（DIF上穿DEA）")
    print("=" * 80)
    
    # 获取所有股票代码
    all_symbols = get_daily_symbols()
    print(f"共 {len(all_symbols)} 只股票待筛选")
    print("=" * 80)
    
    # 符合条件的股票列表
    selected_stocks = []
    
    # 遍历所有股票
    for idx, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{idx + 1} / {len(all_symbols)}")
        
        # 检查股票是否符合策略
        is_match, info = check_weekly_macd_strategy(symbol)
        
        if is_match:
            selected_stocks.append(info)
            print(f"✅ 发现符合条件的股票: {info['symbol']}")
            print(f"   日期: {info['last_date']}, 收盘价: {info['last_close']:.2f}")
            print(f"   DIF: {info['last_dif']:.4f}, DEA: {info['last_dea']:.4f}, MACD: {info['last_macd']:.4f}")
            print("-" * 80)
    
    # 输出结果汇总
    print("=" * 80)
    print(f"选股完成！共找到 {len(selected_stocks)} 只符合条件的股票")
    print("=" * 80)
    
    if selected_stocks:
        print("\n符合条件的股票列表：")
        print("-" * 80)
        print(f"{'股票代码':<15} {'日期':<12} {'收盘价':<10} {'DIF':<10} {'DEA':<10} {'MACD':<10}")
        print("-" * 80)
        for stock in selected_stocks:
            print(f"{stock['symbol']:<15} {stock['last_date']:<12} {stock['last_close']:<10.2f} "
                  f"{stock['last_dif']:<10.4f} {stock['last_dea']:<10.4f} {stock['last_macd']:<10.4f}")
        print("-" * 80)
        
        # 保存结果到文件
        output_file = os.path.join(get_data_dir(), 'weekly_macd_divergence_stocks.json')
        import json
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(selected_stocks, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_file}")
    else:
        print("未找到符合条件的股票")

if __name__ == '__main__':
    main()
