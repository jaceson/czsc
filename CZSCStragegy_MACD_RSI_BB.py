# coding: utf-8
"""
MACD + RSI + 布林带（BB）组合策略
核心逻辑：MACD 判断趋势方向，RSI 确认买卖力度，布林带辅助判断波动范围。三者共振可减少假信号。

买入信号：MACD 在 0 轴上方金叉，RSI 在 30 以下超卖，股价触及布林带下轨。
卖出信号：MACD 在 0 轴下方死叉，RSI 在 70 以上超买，股价触及布林带上轨。
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

# 统计变量
buy_signals = []
sell_signals = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

def detect_macd_golden_cross_above_zero(df):
    """
    检测MACD在0轴上方金叉
    金叉：DIF上穿DEA，且DIF和DEA都在0轴上方
    
    参数:
        df: 包含DIF和DEA的DataFrame
    
    返回:
        tuple: (是否出现金叉, 金叉索引位置)
    """
    if len(df) < 2:
        return False, None
    
    # 获取最后两天的数据
    last_dif = df['DIF'].iloc[-1]
    last_dea = df['DEA'].iloc[-1]
    prev_dif = df['DIF'].iloc[-2]
    prev_dea = df['DEA'].iloc[-2]
    
    # 金叉条件：
    # 1. 前一天DIF < DEA，今天DIF > DEA
    # 2. 当前DIF和DEA都在0轴上方
    golden_cross = (prev_dif < prev_dea) and (last_dif > last_dea)
    above_zero = (last_dif > 0) and (last_dea > 0)
    
    if golden_cross and above_zero:
        return True, df.index[-1]
    
    return False, None

def detect_macd_dead_cross_below_zero(df):
    """
    检测MACD在0轴下方死叉
    死叉：DIF下穿DEA，且DIF和DEA都在0轴下方
    
    参数:
        df: 包含DIF和DEA的DataFrame
    
    返回:
        tuple: (是否出现死叉, 死叉索引位置)
    """
    if len(df) < 2:
        return False, None
    
    # 获取最后两天的数据
    last_dif = df['DIF'].iloc[-1]
    last_dea = df['DEA'].iloc[-1]
    prev_dif = df['DIF'].iloc[-2]
    prev_dea = df['DEA'].iloc[-2]
    
    # 死叉条件：
    # 1. 前一天DIF > DEA，今天DIF < DEA
    # 2. 当前DIF和DEA都在0轴下方
    dead_cross = (prev_dif > prev_dea) and (last_dif < last_dea)
    below_zero = (last_dif < 0) and (last_dea < 0)
    
    if dead_cross and below_zero:
        return True, df.index[-1]
    
    return False, None

def detect_rsi_oversold(df, threshold=30):
    """
    检测RSI超卖（RSI在阈值以下）
    
    参数:
        df: 包含RSI的DataFrame
        threshold: 超卖阈值，默认30
    
    返回:
        bool: 是否超卖
    """
    if len(df) < 1:
        return False
    
    last_rsi = df['RSI'].iloc[-1]
    return last_rsi < threshold

def detect_rsi_overbought(df, threshold=70):
    """
    检测RSI超买（RSI在阈值以上）
    
    参数:
        df: 包含RSI的DataFrame
        threshold: 超买阈值，默认70
    
    返回:
        bool: 是否超买
    """
    if len(df) < 1:
        return False
    
    last_rsi = df['RSI'].iloc[-1]
    return last_rsi > threshold

def detect_price_touches_boll_lower(df, tolerance=0.02):
    """
    检测股价触及布林带下轨
    触及：收盘价接近或低于布林带下轨（允许一定容差）
    
    参数:
        df: 包含close和LOWER的DataFrame
        tolerance: 容差百分比，默认2%（0.02）
    
    返回:
        bool: 是否触及下轨
    """
    if len(df) < 1:
        return False
    
    last_close = df['close'].iloc[-1]
    last_lower = df['LOWER'].iloc[-1]
    
    # 允许收盘价在下轨附近（容差范围内）
    return last_close <= last_lower * (1 + tolerance)

def detect_price_touches_boll_upper(df, tolerance=0.02):
    """
    检测股价触及布林带上轨
    触及：收盘价接近或高于布林带上轨（允许一定容差）
    
    参数:
        df: 包含close和UPPER的DataFrame
        tolerance: 容差百分比，默认2%（0.02）
    
    返回:
        bool: 是否触及上轨
    """
    if len(df) < 1:
        return False
    
    last_close = df['close'].iloc[-1]
    last_upper = df['UPPER'].iloc[-1]
    
    # 允许收盘价在上轨附近（容差范围内）
    return last_close >= last_upper * (1 - tolerance)

def check_buy_signal(df):
    """
    检查买入信号
    买入信号：MACD 在 0 轴上方金叉，RSI 在 20 以下超卖，股价触及布林带下轨
    
    参数:
        df: 包含所有指标的DataFrame
    
    返回:
        tuple: (是否有买入信号, 信号日期)
    """
    if len(df) < 50:  # 需要足够的数据计算指标
        return False, None
    
    # 检测MACD在0轴上方金叉
    has_golden_cross, cross_idx = detect_macd_golden_cross_above_zero(df)
    if not has_golden_cross:
        return False, None
    
    # 检测RSI超卖
    is_oversold = detect_rsi_oversold(df, threshold=30)
    if not is_oversold:
        return False, None
    
    # 检测股价触及布林带下轨
    touches_lower = detect_price_touches_boll_lower(df, tolerance=0.02)
    if not touches_lower:
        return False, None
    
    # 所有条件都满足
    signal_date = df['date'].iloc[-1]
    return True, signal_date

def check_sell_signal(df):
    """
    检查卖出信号
    卖出信号：MACD 在 0 轴下方死叉，RSI 在 70 以上超买，股价触及布林带上轨
    
    参数:
        df: 包含所有指标的DataFrame
    
    返回:
        tuple: (是否有卖出信号, 信号日期)
    """
    if len(df) < 50:  # 需要足够的数据计算指标
        return False, None
    
    # 检测MACD在0轴下方死叉
    has_dead_cross, cross_idx = detect_macd_dead_cross_below_zero(df)
    if not has_dead_cross:
        return False, None
    
    # 检测RSI超买
    is_overbought = detect_rsi_overbought(df, threshold=70)
    if not is_overbought:
        return False, None
    
    # 检测股价触及布林带上轨
    touches_upper = detect_price_touches_boll_upper(df, tolerance=0.02)
    if not touches_upper:
        return False, None
    
    # 所有条件都满足
    signal_date = df['date'].iloc[-1]
    return True, signal_date

def get_macd_rsi_bb_condition(symbol, df):
    """
    获取MACD+RSI+布林带买入条件
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    
    返回:
        pandas Series: 买入条件布尔序列（索引与df一致）
    """
    if df is None or len(df) < 50:
        return pd.Series([False] * len(df), index=df.index)
    
    # 创建副本避免修改原数据
    ndf = df.copy()
    
    # 计算MACD指标
    dif, dea, macd = MACD(ndf['close'].values)
    ndf['DIF'] = dif
    ndf['DEA'] = dea
    ndf['MACD'] = macd
    
    # 计算RSI指标（默认周期24）
    rsi = RSI(ndf['close'].values, N=24)
    ndf['RSI'] = rsi
    
    # 计算布林带指标（默认周期20，标准差倍数2）
    upper, mid, lower = BOLL(ndf['close'].values, N=20, P=2)
    ndf['UPPER'] = upper
    ndf['MID'] = mid
    ndf['LOWER'] = lower
    
    # 计算前一天的DIF和DEA（用于判断金叉）
    # ndf['DIF_PREV'] = REF(ndf['DIF'].values, 1)
    # ndf['DEA_PREV'] = REF(ndf['DEA'].values, 1)
    ndf['MACD_PREV'] = REF(ndf['MACD'].values, 1)

    # 买入条件：
    # 1. MACD条件：MACD < -2 且 MACD > 前一天的MACD（MACD上升趋势）
    macd_golden_cross = (
        (ndf['MACD'] < -2) & 
        (ndf['MACD'] > ndf['MACD_PREV'])
    )
    return macd_golden_cross
    # 2. RSI在20以下超卖
    rsi_oversold = ndf['RSI'] < 30

    # 3. 股价触及布林带下轨（允许2%容差）
    touches_lower = ndf['close'] <= ndf['LOWER'] * 1.02

    # 综合买入条件
    buy_condition = macd_golden_cross & rsi_oversold & touches_lower
    
    # 处理NaN值（将NaN视为False），并确保索引与原始df一致
    # buy_condition = pd.Series(buy_condition.fillna(False).values, index=df.index)
    
    return buy_condition

def get_macd_rsi_bb_buy_point(symbol, df):
    """
    获取MACD+RSI+布林带买入点（类似MonthTurnStrategy的get_month_turn_join_buy_point）
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    """
    last_start_index = -1
    buy_con = get_macd_rsi_bb_condition(symbol, df)
    
    if not df[buy_con].empty:
        selected_indexs = df[buy_con].index
        for idx in selected_indexs:
            buy_date = df['date'][idx]
            start_index = df.iloc[df['date'].values == buy_date].index[0]
            
            # 避免频繁买入（至少间隔hold_days天）
            if last_start_index > 0 and (start_index - last_start_index) <= hold_days:
                continue
            
            print(f"{symbol} MACD+RSI+BB买入日期：{buy_date}")
            
            buy_price = df['close'].iloc[start_index]
            max_val = -1000
            last_start_index = start_index
            
            # 计算持有期收益
            for idx in range(start_index + 1, start_index + hold_days + 1):
                if idx < len(df['date']):
                    stock_close = df['close'].iloc[idx]
                    ratio = round(100 * (stock_close - buy_price) / buy_price, 2)
                    ratio_map[idx - start_index].append(ratio)
                    max_val = max(max_val, ratio)
            
            # 记录买入信号
            buy_signals.append({
                'symbol': symbol,
                'buy_date': buy_date,
                'buy_price': buy_price,
                'max_return': max_val
            })
            
            if max_val > 0:
                print(f"  最大收益: {max_val:.2f}%")
            else:
                print(f"  最大亏损: {max_val:.2f}%")

def print_statistics(title, arr):
    """
    打印统计信息：平均值、最大值、最小值、50%和95%的百分位数
    
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

def print_console(s_plus_list, s_minus_list, s_ratio_map):
    """
    打印统计结果（优化版，增加更多统计维度）
    """
    print("=" * 80)
    print("MACD + RSI + 布林带策略统计结果")
    print("=" * 80)
    
    # 基本统计
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
    
    # 合并所有收益用于总体统计
    all_returns = s_plus_list + s_minus_list
    if len(all_returns) > 0:
        print("\n总体收益统计：")
        print_statistics('总收益：', all_returns)
    
    # 正收益统计
    if len(s_plus_list) > 0:
        print("\n正收益统计：")
        print_statistics('正收益：', s_plus_list)
    
    # 负收益统计
    if len(s_minus_list) > 0:
        print("\n负收益统计：")
        print_statistics('负收益：', s_minus_list)
    
    # 每天统计
    print("\n" + "=" * 80)
    print("按天统计收益")
    print("=" * 80)
    for x in range(1, hold_days + 1):
        print("\n第 {} 天：".format(x))
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
        
        print("    正收益次数：" + str(plus_num))
        if plus_num > 0 or minus_num > 0:
            print("    正收益占比：" + str(round(100 * plus_num / (plus_num + minus_num), 2)) + "%")
        print("    总的正收益：" + str(round(plus_val, 2)))
        print("    总的负收益：" + str(round(minus_val, 2)))
        
        # 添加详细统计信息
        if len(res_list) > 0:
            print_statistics("    第 {} 天收益统计：".format(x), res_list)

def main():
    """主函数：执行选股策略"""
    print("=" * 80)
    print("MACD + RSI + 布林带组合策略")
    print("=" * 80)
    print("策略条件：")
    print("买入信号：MACD 在 0 轴上方金叉，RSI 在 20 以下超卖，股价触及布林带下轨")
    print("卖出信号：MACD 在 0 轴下方死叉，RSI 在 70 以上超买，股价触及布林带上轨")
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
            if df is None or len(df) < 50:
                continue
            
            # 获取买入点
            get_macd_rsi_bb_buy_point(symbol, df)
            
            # 分阶段打印统计结果
            if (idx + 1) % 100 == 0:
                plus_list = [sig['max_return'] for sig in buy_signals if sig['max_return'] > 0]
                minus_list = [sig['max_return'] for sig in buy_signals if sig['max_return'] <= 0]
                print_console(plus_list, minus_list, ratio_map)
        
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            continue
    
    # 最终统计
    plus_list = [sig['max_return'] for sig in buy_signals if sig['max_return'] > 0]
    minus_list = [sig['max_return'] for sig in buy_signals if sig['max_return'] <= 0]
    print_console(plus_list, minus_list, ratio_map)
    
    # 保存结果到文件
    if buy_signals:
        output_file = os.path.join(get_data_dir(), 'macd_rsi_bb_signals.json')
        import json
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(buy_signals, f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {output_file}")
        print(f"共找到 {len(buy_signals)} 个买入信号")

if __name__ == '__main__':
    main()

