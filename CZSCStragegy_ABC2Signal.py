# coding: utf-8
"""
ABC2信号策略
策略逻辑：
1. 前一天 ABC2*2 <= REF(ABC2*2,1)
2. 当天 ABC2*2 > REF(ABC2*2,1)
3. 第二天开盘价买入
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

def get_abc2_signal_condition(symbol, df):
    """
    获取ABC2信号条件
    买入条件：
    1. 前三天都显示COLORGRAY（前三天都有有效数据）
    2. 前三天开始吃鱼值连续减小（前3天 < 前2天 < 前1天）
    3. 当天显示COLOR4080FF（ABC2*2 > REF(ABC2*2,1)）
    4. 从前三天到当天，开始吃鱼值大于2
    5. 当天开始吃鱼值大于前一天
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    
    返回:
        pandas Series: 买入条件布尔序列
    """
    if df is None or len(df) < 250:  # 需要足够的数据计算指标
        return pd.Series([False] * len(df), index=df.index)
    
    # 计算所有指标
    ndf = calculate_formula_indicators(df)
    
    # ABC2*2
    ABC2_DOUBLE = ndf['ABC2'] * 2
    
    # REF(ABC2*2,1) - 前一天的ABC2*2
    ABC2_DOUBLE_PREV1 = REF(ABC2_DOUBLE, 1)
    ABC2_DOUBLE_PREV2 = REF(ABC2_DOUBLE, 2)
    ABC2_DOUBLE_PREV3 = REF(ABC2_DOUBLE, 3)
    ABC2_DOUBLE_PREV4 = REF(ABC2_DOUBLE, 4)
    ABC2_DOUBLE_PREV5 = REF(ABC2_DOUBLE, 5)
    
    # 计算"开始吃鱼"指标
    # 开始吃鱼:IF(ABC68,ABC70,ABC69)
    # ABC69:=(ABC1/LLV(ABC1,10)-1)*200;
    # ABC70:=(ABC1/LLV(ABC1,10)-1)*400;
    ABC68 = ndf['ABC68'].fillna(False)
    ABC69 = ndf['ABC69']
    ABC70 = ndf['ABC70']
    
    # 开始吃鱼 = IF(ABC68, ABC70, ABC69)
    START_EAT_FISH = IF(ABC68, ABC70, ABC69)
    ndf['START_EAT_FISH'] = START_EAT_FISH
    
    # 获取前1天、前2天、前3天的"开始吃鱼"值
    START_EAT_FISH_PREV1 = REF(START_EAT_FISH, 1)  # 前1天
    START_EAT_FISH_PREV2 = REF(START_EAT_FISH, 2)  # 前2天
    START_EAT_FISH_PREV3 = REF(START_EAT_FISH, 3)  # 前3天
    START_EAT_FISH_PREV4 = REF(START_EAT_FISH, 4)  # 前4天
    START_EAT_FISH_PREV5 = REF(START_EAT_FISH, 5)  # 前5天
    
    # 买入条件：
    # 1. 前三天都显示COLORGRAY（前三天都有有效数据，即ABC2*2不为NaN）
    # COLORGRAY对应基础显示，这里检查前三天数据是否有效
    condition1 = (
        ~np.isnan(ABC2_DOUBLE_PREV1) & 
        ~np.isnan(ABC2_DOUBLE_PREV2) & 
        ~np.isnan(ABC2_DOUBLE_PREV3) & 
        ~np.isnan(ABC2_DOUBLE_PREV4) & 
        ~np.isnan(ABC2_DOUBLE_PREV5)
    )
    
    # 2. 前三天开始吃鱼值连续减小（前3天 > 前2天 > 前1天）
    condition2 = (
        (START_EAT_FISH_PREV5 > START_EAT_FISH_PREV4) & 
        (START_EAT_FISH_PREV4 > START_EAT_FISH_PREV3) & 
        (START_EAT_FISH_PREV3 > START_EAT_FISH_PREV2) & 
        (START_EAT_FISH_PREV2 > START_EAT_FISH_PREV1)
    )
    
    # 3. 当天显示COLOR4080FF（ABC2*2 > REF(ABC2*2,1)）
    # COLOR4080FF对应：STICKLINE(ABC2*2 > REF(ABC2*2,1),ABC2*2,ABC3*2,2,0),COLOR4080FF;
    condition3 = (
        (ABC2_DOUBLE > ABC2_DOUBLE_PREV1) &
        (ABC2_DOUBLE_PREV1 < ABC2_DOUBLE_PREV2) &
        (ABC2_DOUBLE_PREV2 < ABC2_DOUBLE_PREV3) &
        (ABC2_DOUBLE_PREV3 < ABC2_DOUBLE_PREV4) &
        (ABC2_DOUBLE_PREV4 < ABC2_DOUBLE_PREV5) 
    )
    
    # 4. 从前三天到当天，开始吃鱼值大于2
    condition4 = (
        (START_EAT_FISH_PREV5 > 2) & 
        (START_EAT_FISH_PREV4 > 2) & 
        (START_EAT_FISH_PREV3 > 2) & 
        (START_EAT_FISH_PREV2 > 2) & 
        (START_EAT_FISH > 2)
    )
    
    # 5. 当天开始吃鱼值大于前一天
    condition5 = START_EAT_FISH > START_EAT_FISH_PREV1
    
    # 综合买入条件
    buy_condition = condition1 & condition2 & condition3 & condition4 & condition5
    
    # 处理NaN值（将NaN视为False），并确保索引与原始df一致
    buy_condition = pd.Series(buy_condition.fillna(False).values, index=df.index)
    
    return buy_condition

def get_abc2_signal_buy_point(symbol, df):
    """
    获取ABC2信号买入点（第二天开盘价买入）
    参考 MonthTurnStrategy 的 get_month_turn_join_buy_point
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    """
    last_start_index = -1
    buy_con = get_abc2_signal_condition(symbol, df)
    
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
            
            eat_fish = df['START_EAT_FISH'].iloc[start_index]
            buy_date = df['date'].iloc[buy_index]
            buy_price = df['open'].iloc[buy_index]  # 第二天开盘价
            
            print(f"{symbol} ABC2信号日期：{signal_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}，吃鱼：{eat_fish:.2f}")
            
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

def print_console(s_plus_list, s_minus_list, s_ratio_map):
    """
    打印统计结果（参考 CZSCStragegy_Goldenline.py）
    """
    print("=" * 80)
    print("ABC2信号策略统计结果")
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
    print("=" * 80)
    print("ABC2信号策略")
    print("=" * 80)
    print("策略条件：")
    print("1. 前一天 ABC2*2 <= REF(ABC2*2,1)")
    print("2. 当天 ABC2*2 > REF(ABC2*2,1)")
    print("3. 第二天开盘价买入")
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
            df = get_local_stock_data(symbol, '2020-01-01')
            if df is None or len(df) < 250:  # 需要足够的历史数据
                continue
            
            # 获取买入点
            get_abc2_signal_buy_point(symbol, df)
            
            # 分阶段打印统计结果
            if (idx + 1) % 100 == 0:
                print_console(plus_list, minus_list, ratio_map)
        
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # 最终统计
    print_console(plus_list, minus_list, ratio_map)

if __name__ == '__main__':
    main()

