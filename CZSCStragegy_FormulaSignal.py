# coding: utf-8
"""
公式平台和好股网信号策略
策略逻辑：显示公式平台和好股网信号后又显示COLORFF0080，第二天开盘价买入
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

# 统计变量
plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

def calculate_formula_indicators(df):
    """
    计算公式中的所有指标
    
    参数:
        df: 股票数据DataFrame，需要包含：close, high, low, volume, amount
    
    返回:
        DataFrame: 添加了所有计算指标的DataFrame
    """
    ndf = df
    
    # ABC1:=EMA(CLOSE,10);
    ABC1 = EMA(ndf['close'].values, 10)
    ndf['ABC1'] = ABC1
    
    # ABC2:=(ABC1/LLV(ABC1,10)-1)*100;
    ABC2 = (ABC1 / LLV(ABC1, 10) - 1) * 100
    ndf['ABC2'] = ABC2
    
    # ABC3:=(-1)*ABC2;
    ABC3 = (-1) * ABC2
    ndf['ABC3'] = ABC3
    
    # ABC4:=100*(HHV(HIGH,14)-CLOSE)/(HHV(HIGH,14)-LLV(LOW,14));
    ABC4 = 100 * (HHV(ndf['high'].values, 14) - ndf['close'].values) / (HHV(ndf['high'].values, 14) - LLV(ndf['low'].values, 14))
    ndf['ABC4'] = ABC4
    
    # ABC5:=REF(CLOSE,1);
    ABC5 = REF(ndf['close'].values, 1)
    ndf['ABC5'] = ABC5
    
    # ABC6:=SMA(MAX(CLOSE-ABC5,0),9,1)/SMA(ABS(CLOSE-ABC5),9,1)*100;
    ABC6 = SMA(MAX(ndf['close'].values - ABC5, 0), 9, 1) / SMA(ABS(ndf['close'].values - ABC5), 9, 1) * 100
    ndf['ABC6'] = ABC6
    
    # ABC7:=(CLOSE-LLV(LOW,9))/(HHV(HIGH,9)-LLV(LOW,9))*100;
    ABC7 = (ndf['close'].values - LLV(ndf['low'].values, 9)) / ((HHV(ndf['high'].values, 9) - LLV(ndf['low'].values, 9)) + 1e-10) * 100
    ndf['ABC7'] = ABC7
    
    # ABC8:=SMA(ABC7,3,1);
    ABC8 = SMA(ABC7, 3, 1)
    ndf['ABC8'] = ABC8
    
    # ABC9:=SMA(ABC8,3,1);
    ABC9 = SMA(ABC8, 3, 1)
    ndf['ABC9'] = ABC9
    
    # ABC10:=3*ABC8-2*ABC9;
    ABC10 = 3 * ABC8 - 2 * ABC9
    ndf['ABC10'] = ABC10
    
    # ABC11:=ABC6 >=76 OR ABC10 > 95;
    ABC11 = (ABC6 >= 76) | (ABC10 > 95)
    ndf['ABC11'] = ABC11
    
    # ABC12:=ABC4 < 25;
    ABC12 = ABC4 < 25
    ndf['ABC12'] = ABC12
    
    # ABC13:=ABC11 OR ABC12;
    ABC13 = ABC11 | ABC12
    ndf['ABC13'] = ABC13
    
    # ABC14到ABC26: 各种EMA
    ABC14 = EMA(ndf['close'].values, 20)
    ABC15 = EMA(ndf['close'].values, 30)
    ABC16 = EMA(ndf['close'].values, 35)
    ABC17 = EMA(ndf['close'].values, 40)
    ABC18 = EMA(ndf['close'].values, 45)
    ABC19 = EMA(ndf['close'].values, 90)
    ABC20 = EMA(ndf['close'].values, 98)
    ABC21 = EMA(ndf['close'].values, 106)
    ABC22 = EMA(ndf['close'].values, 114)
    ABC23 = EMA(ndf['close'].values, 140)
    ABC24 = EMA(ndf['close'].values, 148)
    ABC25 = EMA(ndf['close'].values, 156)
    ABC26 = EMA(ndf['close'].values, 164)
    
    ndf['ABC14'] = ABC14
    ndf['ABC15'] = ABC15
    ndf['ABC16'] = ABC16
    ndf['ABC17'] = ABC17
    ndf['ABC18'] = ABC18
    ndf['ABC19'] = ABC19
    ndf['ABC20'] = ABC20
    ndf['ABC21'] = ABC21
    ndf['ABC22'] = ABC22
    ndf['ABC23'] = ABC23
    ndf['ABC24'] = ABC24
    ndf['ABC25'] = ABC25
    ndf['ABC26'] = ABC26
    
    # ABC27:=MAX(MAX(MAX(ABC15,ABC16),ABC17),ABC18);
    ABC27 = MAX(MAX(MAX(ABC15, ABC16), ABC17), ABC18)
    ndf['ABC27'] = ABC27
    
    # ABC28:=MIN(MIN(MIN(ABC15,ABC16),ABC17),ABC18);
    ABC28 = MIN(MIN(MIN(ABC15, ABC16), ABC17), ABC18)
    ndf['ABC28'] = ABC28
    
    # ABC29:=MAX(MAX(MAX(ABC19,ABC20),ABC21),ABC22);
    ABC29 = MAX(MAX(MAX(ABC19, ABC20), ABC21), ABC22)
    ndf['ABC29'] = ABC29
    
    # ABC30:=MIN(MIN(MIN(ABC19,ABC20),ABC21),ABC22);
    ABC30 = MIN(MIN(MIN(ABC19, ABC20), ABC21), ABC22)
    ndf['ABC30'] = ABC30
    
    # ABC31:=MAX(MAX(MAX(ABC23,ABC24),ABC25),ABC26);
    ABC31 = MAX(MAX(MAX(ABC23, ABC24), ABC25), ABC26)
    ndf['ABC31'] = ABC31
    
    # ABC32:=MIN(MIN(MIN(ABC23,ABC24),ABC25),ABC26);
    ABC32 = MIN(MIN(MIN(ABC23, ABC24), ABC25), ABC26)
    ndf['ABC32'] = ABC32
    
    # ABC33:=MAX(MAX(ABC27,ABC29),ABC31);
    ABC33 = MAX(MAX(ABC27, ABC29), ABC31)
    ndf['ABC33'] = ABC33
    
    # ABC34:=MIN(MIN(ABC28,ABC30),ABC32);
    ABC34 = MIN(MIN(ABC28, ABC30), ABC32)
    ndf['ABC34'] = ABC34
    
    # ABC35:=ABC33/ABC34;
    ABC35 = ABC33 / (ABC34 + 1e-10)
    ndf['ABC35'] = ABC35
    
    # ABC36:=LOW/ABC27;
    ABC36 = ndf['low'].values / (ABC27 + 1e-10)
    ndf['ABC36'] = ABC36
    
    # ABC37:=ABC35 < 1.3 AND REF(ABC36,1) < 1.05 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08;
    ABC36_PREV = REF(ABC36, 1)
    ABC37 = (ABC35 < 1.3) & (ABC36_PREV < 1.05) & (ndf['close'].values > ABC14) & (ndf['close'].values > ABC33) & (ABC36 < 1.08)
    ndf['ABC37'] = ABC37
    
    # ABC38:=AMOUNT/10000;
    ABC38 = ndf['amount'].values / 10000
    ndf['ABC38'] = ABC38
    
    # ABC39:=LLV(ABC38,2) > 2000 AND ABC38 > 8000;
    ABC39 = (LLV(ABC38, 2) > 2000) & (ABC38 > 8000)
    ndf['ABC39'] = ABC39
    
    # ABC40:=CLOSE/REF(CLOSE,1);
    ABC40 = ndf['close'].values / (ABC5 + 1e-10)
    ndf['ABC40'] = ABC40
    
    # ABC41到ABC45: EMA和MAX/MIN
    ABC41 = EMA(ndf['close'].values, 5)
    ABC42 = EMA(ndf['close'].values, 10)
    ABC43 = EMA(ndf['close'].values, 20)
    ABC44 = MAX(MAX(ABC41, ABC42), ABC43)
    ABC45 = MIN(MIN(ABC41, ABC42), ABC43)
    
    ndf['ABC41'] = ABC41
    ndf['ABC42'] = ABC42
    ndf['ABC43'] = ABC43
    ndf['ABC44'] = ABC44
    ndf['ABC45'] = ABC45
    
    # ABC46:=LOW < ABC45 AND CLOSE > ABC44 AND VOL > REF(VOL,1)*1.2 AND ABC39 AND ABC40 > 1.029 AND ABC37;
    VOL_PREV = REF(ndf['volume'].values, 1)
    ABC46 = (ndf['low'].values < ABC45) & (ndf['close'].values > ABC44) & (ndf['volume'].values > VOL_PREV * 1.2) & ABC39 & (ABC40 > 1.029) & ABC37
    ndf['ABC46'] = ABC46
    
    # ABC47:=(HIGH+LOW+CLOSE)/3;
    ABC47 = (ndf['high'].values + ndf['low'].values + ndf['close'].values) / 3
    ndf['ABC47'] = ABC47
    
    # ABC48:=(ABC47-MA(ABC47,81))*1000/(15*AVEDEV(ABC47,81));
    ABC48 = (ABC47 - MA(ABC47, 81)) * 1000 / (15 * AVEDEV(ABC47, 81) + 1e-10)
    ndf['ABC48'] = ABC48
    
    # ABC49:=CROSS(ABC48,100) AND VOL > REF(VOL,1)*1.2 AND ABC39 AND ABC40 > 1.029 AND ABC37;
    # CROSS(ABC48, 100) 表示ABC48上穿100
    ABC48_PREV = REF(ABC48, 1)
    ABC49_CROSS = (ABC48_PREV <= 100) & (ABC48 > 100)
    ABC49 = ABC49_CROSS & (ndf['volume'].values > VOL_PREV * 1.2) & ABC39 & (ABC40 > 1.029) & ABC37
    ndf['ABC49'] = ABC49
    
    # ABC50到ABC53: MA
    ABC50 = MA(ndf['close'].values, 30)
    ABC51 = MA(ndf['close'].values, 60)
    ABC52 = MA(ndf['close'].values, 90)
    ABC53 = MA(ndf['close'].values, 240)
    
    ndf['ABC50'] = ABC50
    ndf['ABC51'] = ABC51
    ndf['ABC52'] = ABC52
    ndf['ABC53'] = ABC53
    
    # ABC54到ABC56: ABS计算
    ABC54 = ABS(ABC50 / (ABC51 + 1e-10) - 1)
    ABC55 = ABS(ABC51 / (ABC52 + 1e-10) - 1)
    ABC56 = ABS(ABC50 / (ABC52 + 1e-10) - 1)
    
    ndf['ABC54'] = ABC54
    ndf['ABC55'] = ABC55
    ndf['ABC56'] = ABC56
    
    # ABC57:=CLOSE/REF(CLOSE,1);
    ABC57 = ABC40  # 与ABC40相同
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
    
    # ABC65:=ABC64 AND VOL > REF(VOL,1)*1.2 AND ABC39 AND ABC37;
    ABC65 = (ABC64 == 1) & (ndf['volume'].values > VOL_PREV * 1.2) & ABC39 & ABC37
    ndf['ABC65'] = ABC65
    
    # ABC66:=ABC35 < 1.15 AND REF(ABC36,1) < 1.04 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08 AND ABC40 > 1.04 AND VOL > REF(VOL,1)*1.2 AND ABC39 AND ABC37;
    ABC66 = (ABC35 < 1.15) & (ABC36_PREV < 1.04) & (ndf['close'].values > ABC14) & (ndf['close'].values > ABC33) & (ABC36 < 1.08) & (ABC40 > 1.04) & (ndf['volume'].values > VOL_PREV * 1.2) & ABC39 & ABC37
    ndf['ABC66'] = ABC66
    
    # ABC67:=LOW < ABC34 AND CLOSE > ABC33 AND ABC40 > 1.05 AND VOL > REF(VOL,1)*1.2;
    ABC67 = (ndf['low'].values < ABC34) & (ndf['close'].values > ABC33) & (ABC40 > 1.05) & (ndf['volume'].values > VOL_PREV * 1.2)
    ndf['ABC67'] = ABC67
    
    # ABC68:=ABC46 OR ABC49 OR ABC65 OR ABC66 OR ABC67;
    ABC68 = ABC46 | ABC49 | ABC65 | ABC66 | ABC67
    ndf['ABC68'] = ABC68
    
    # ABC69和ABC70
    ABC69 = (ABC1 / (LLV(ABC1, 10) + 1e-10) - 1) * 200
    ABC70 = (ABC1 / (LLV(ABC1, 10) + 1e-10) - 1) * 400
    ndf['ABC69'] = ABC69
    ndf['ABC70'] = ABC70
    
    # ABC71:=IF(ABC68,ABC2,0);
    ABC71 = IF(ABC68, ABC2, 0)
    ndf['ABC71'] = ABC71
    
    return ndf

def get_formula_signal_condition(symbol, df, max_days=20):
    """
    获取公式平台和好股网信号条件
    买入条件：先出现ABC68为真，过几天后出现COLORFF0080条件（ABC2*2 > 20 AND ABC2*2 > REF(ABC2*2,1)）
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
        max_days: ABC68信号后，最多等待多少天出现COLORFF0080才算有效（默认20天）
    
    返回:
        pandas Series: 买入条件布尔序列（COLORFF0080出现时，如果之前有ABC68信号，则为True）
    """
    if df is None or len(df) < 250:  # 需要足够的数据计算指标
        return pd.Series([False] * len(df), index=df.index)
    
    # 计算所有指标
    ndf = calculate_formula_indicators(df)
    
    # ABC68条件：公式平台和好股网信号
    ABC68 = ndf['ABC68'].fillna(False)
    
    # COLORFF0080条件：ABC2*2 > 20 AND ABC2*2 > REF(ABC2*2,1)
    ABC2_DOUBLE = ndf['ABC2'] * 2
    ABC2_DOUBLE_PREV = REF(ABC2_DOUBLE, 1)
    COLORFF0080 = (ABC2_DOUBLE > 20) & (ABC2_DOUBLE > ABC2_DOUBLE_PREV)
    COLORFF0080 = COLORFF0080.fillna(False)
    
    # 创建买入条件序列
    buy_condition = pd.Series([False] * len(df), index=df.index)
    
    # 将ABC68和COLORFF0080转换为numpy数组以提高性能
    ABC68_array = ABC68.values
    COLORFF0080_array = COLORFF0080.values
    
    # 遍历每个交易日，检查买入条件
    for i in range(len(df)):
        # 如果当前出现COLORFF0080条件
        if COLORFF0080_array[i]:
            # 向前查找，看之前是否有ABC68信号（在max_days天内）
            # 使用numpy的any()方法提高效率
            start_idx = max(0, i - max_days)
            if np.any(ABC68_array[start_idx:i]):
                buy_condition.iloc[i] = True
    
    return buy_condition

def get_formula_signal_buy_point(symbol, df):
    """
    获取公式信号买入点（第二天开盘价买入）
    买入条件：先出现ABC68信号，之后出现COLORFF0080信号
    
    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    """
    last_start_index = -1
    buy_con = get_formula_signal_condition(symbol, df)
    
    if not df[buy_con].empty:
        selected_indexs = df[buy_con].index
        for idx in selected_indexs:
            # COLORFF0080信号出现的日期（买入信号日期）
            colorff0080_date = df['date'][idx]
            signal_index = df.iloc[df['date'].values == colorff0080_date].index[0]
            
            # 避免频繁买入（至少间隔hold_days天）
            if last_start_index > 0 and (signal_index - last_start_index) <= hold_days:
                continue
            
            # 查找之前的ABC68信号日期
            ndf = calculate_formula_indicators(df)
            ABC68 = ndf['ABC68'].fillna(False)
            ABC68_array = ABC68.values
            
            # 向前查找最近的ABC68信号
            abc68_date = None
            for j in range(max(0, signal_index - 20), signal_index):
                if ABC68_array[j]:
                    abc68_date = df['date'].iloc[j]
                    break
            
            # 第二天开盘价买入
            buy_index = signal_index + 1
            if buy_index >= len(df):
                continue
            
            buy_date = df['date'].iloc[buy_index]
            buy_price = df['open'].iloc[buy_index]  # 第二天开盘价
            
            if abc68_date:
                print(f"{symbol} ABC68信号日期：{abc68_date}，COLORFF0080信号日期：{colorff0080_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}")
            else:
                print(f"{symbol} COLORFF0080信号日期：{colorff0080_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}")
            
            max_val = -1000
            last_start_index = signal_index
            
            # 计算持有期收益
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
    打印统计结果（优化版，参考 CZSCStragegy_Goldenline.py）
    """
    print("=" * 80)
    print("公式平台和好股网信号策略统计结果")
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
        
        # 使用辅助函数打印详细统计信息
        if len(res_list) > 0:
            print_statistics("    第 {} 天收益统计：".format(x), res_list)

def main():
    """主函数：执行选股策略"""
    print("=" * 80)
    print("公式平台和好股网信号策略")
    print("=" * 80)
    print("策略条件：")
    print("1. 显示公式平台和好股网信号（ABC68为真）")
    print("2. 显示COLORFF0080（ABC2*2 > 20 AND ABC2*2 > REF(ABC2*2,1)）")
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
            df = get_local_stock_data(symbol, '2000-01-01')
            if df is None or len(df) < 250:  # 需要足够的历史数据
                continue
            
            # 获取买入点
            get_formula_signal_buy_point(symbol, df)
            
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

