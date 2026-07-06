# coding: utf-8
"""
趋势通道共振策略
通达信公式策略回测：
    均价:=(3*C+H+L+O)/6;
    趋势线:=(8*均价+7*REF(均价,1)+6*REF(均价,2)+5*REF(均价,3)+4*REF(均价,4)+3*REF(均价,5)+2*REF(均价,6)+REF(均价,8))/36;
    上轨累和:=(HHV(趋势线,2)+HHV(趋势线,4)+HHV(趋势线,8))/3;
    下轨累和:=(LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3;
    上轨线:=(HHV(上轨累和,2)+HHV(上轨累和,4)+HHV(上轨累和,8))/3;
    下轨线A:=(LLV(下轨累和,2)+LLV(下轨累和,4)+LLV(下轨累和,8))/3;
    下轨线B:=(LLV(趋势线,2)+LLV(趋势线,4)+LLV(趋势线,8))/3;
    买入:=REF(下轨线A,1)=REF(趋势线,1) AND 下轨线A<趋势线;
    加仓:=REF(下轨线B,1)=REF(趋势线,1) AND 下轨线B<趋势线;
    强势条件:=C>REF(C,1)*1.03 AND MA(V,5)>MA(V,30);
    突破信号:=CROSS(C,上轨线) AND 强势条件;
    共振买入:=买入 AND 突破信号;
    共振加仓:=加仓 AND 突破信号;
    总共振:=共振买入 OR 共振加仓;
    排除ST:=NOT(NAMELIKE('ST') OR NAMELIKE('*ST') OR CODELIKE('688'));
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

plus_list = []
minus_list = []
total_ratio = []
total_hold_days = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

def calculate_indicators(df):
    """计算公式中的所有指标"""
    ndf = df.copy()

    均价 = (3 * ndf['close'] + ndf['high'] + ndf['low'] + ndf['open']) / 6
    ndf['均价'] = 均价

    均价1 = REF(均价, 1)
    均价2 = REF(均价, 2)
    均价3 = REF(均价, 3)
    均价4 = REF(均价, 4)
    均价5 = REF(均价, 5)
    均价6 = REF(均价, 6)
    均价8 = REF(均价, 8)
    趋势线 = (8*均价 + 7*均价1 + 6*均价2 + 5*均价3 + 4*均价4 + 3*均价5 + 2*均价6 + 均价8) / 36
    ndf['趋势线'] = 趋势线

    上轨累和 = (HHV(趋势线, 2) + HHV(趋势线, 4) + HHV(趋势线, 8)) / 3
    ndf['上轨累和'] = 上轨累和

    下轨累和 = (LLV(趋势线, 2) + LLV(趋势线, 4) + LLV(趋势线, 8)) / 3
    ndf['下轨累和'] = 下轨累和

    上轨线 = (HHV(上轨累和, 2) + HHV(上轨累和, 4) + HHV(上轨累和, 8)) / 3
    ndf['上轨线'] = 上轨线

    下轨线A = (LLV(下轨累和, 2) + LLV(下轨累和, 4) + LLV(下轨累和, 8)) / 3
    ndf['下轨线A'] = 下轨线A

    下轨线B = (LLV(趋势线, 2) + LLV(趋势线, 4) + LLV(趋势线, 8)) / 3
    ndf['下轨线B'] = 下轨线B

    买入 = (REF(下轨线A, 1) == REF(趋势线, 1)) & (下轨线A < 趋势线)
    ndf['买入'] = 买入

    加仓 = (REF(下轨线B, 1) == REF(趋势线, 1)) & (下轨线B < 趋势线)
    ndf['加仓'] = 加仓

    强势条件 = (ndf['close'] > REF(ndf['close'], 1) * 1.03) & (MA(ndf['volume'], 5) > MA(ndf['volume'], 30))
    ndf['强势条件'] = 强势条件

    上轨线_cross = CROSS(ndf['close'].values, 上轨线)
    突破信号 = 上轨线_cross & 强势条件
    ndf['突破信号'] = 突破信号

    共振买入 = 买入 & 突破信号
    ndf['共振买入'] = 共振买入

    共振加仓 = 加仓 & 突破信号
    ndf['共振加仓'] = 共振加仓

    总共振 = 共振买入 | 共振加仓
    ndf['总共振'] = 总共振

    return ndf

def backtest_strategy(symbol, df):
    """对单只股票执行策略回测"""
    global plus_list, minus_list, total_ratio, total_hold_days, ratio_map

    if df is None or len(df) < 100:
        return

    ndf = calculate_indicators(df)
    last_start_index = -1

    buy_signals = ndf['总共振']
    signal_indices = np.where(buy_signals.fillna(False))[0]

    for idx in signal_indices:
        if idx + hold_days >= len(ndf):
            continue
        if last_start_index > 0 and (idx - last_start_index) <= hold_days:
            continue

        buy_price = ndf['open'].iloc[idx + 1] if idx + 1 < len(ndf) else ndf['open'].iloc[idx]
        buy_date = ndf['date'].iloc[idx + 1] if idx + 1 < len(ndf) else ndf['date'].iloc[idx]

        signal_date = ndf['date'].iloc[idx]
        signal_type = []
        if ndf['共振买入'].iloc[idx]:
            signal_type.append("共振买入")
        if ndf['共振加仓'].iloc[idx]:
            signal_type.append("共振加仓")

        print(f"{symbol} 信号日期：{signal_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}，类型：{' + '.join(signal_type)}")

        max_val = -1000
        last_start_index = idx
        sell_price = buy_price

        for day_offset in range(1, hold_days + 1):
            sell_idx = idx + day_offset
            if sell_idx < len(ndf):
                cur_close = ndf['close'].iloc[sell_idx]
                ratio = round(100 * (cur_close - buy_price) / buy_price, 2)
                ratio_map[day_offset].append(ratio)
                max_val = max(max_val, ratio)

        if max_val > 0:
            plus_list.append(max_val)
            print(f"  最大收益: {max_val:.2f}%")
        else:
            minus_list.append(max_val)
            print(f"  最大亏损: {max_val:.2f}%")

        sell_idx = idx + 1
        while sell_idx < len(ndf):
            cur_ratio = round(100 * (ndf['close'].iloc[sell_idx] - buy_price) / buy_price, 2)
            if cur_ratio > 0:
                break
            sell_idx += 1

        if sell_idx >= len(ndf):
            sell_idx = min(idx + hold_days, len(ndf) - 1)
            sell_price = ndf['close'].iloc[sell_idx]
        else:
            sell_price = ndf['close'].iloc[sell_idx]

        total_ratio.append(round(100 * (sell_price - buy_price) / buy_price, 2))
        total_hold_days.append(sell_idx - idx)

def print_statistics(title, arr):
    if len(arr) == 0:
        print(f"{title}: 无数据")
        return
    average = np.mean(arr)
    max_value = np.max(arr)
    min_value = np.min(arr)
    lower_bound = np.percentile(arr, 50)
    upper_bound = np.percentile(arr, 95)
    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 的百分位数：{lower_bound:.2f}")
    print(f"    95% 的百分位数：{upper_bound:.2f}")

def print_console():
    print("=" * 80)
    print("趋势通道共振策略统计结果")
    print("=" * 80)

    print("正收益次数：" + str(len(plus_list)))
    if len(minus_list) > 0 or len(plus_list) > 0:
        print("正收益占比：" + str(round(100 * len(plus_list) / (len(minus_list) + len(plus_list)), 2)) + "%")

    total = sum(plus_list)
    print("总的正收益：" + str(round(total, 2)))

    total = sum(minus_list)
    print("总的负收益：" + str(round(total, 2)))

    all_returns = plus_list + minus_list
    if len(all_returns) > 0:
        print("\n总体收益统计：")
        print_statistics('总收益：', all_returns)

    if plus_list:
        print("\n正收益统计：")
        print_statistics('正收益：', plus_list)

    if minus_list:
        print("\n负收益统计：")
        print_statistics('负收益：', minus_list)

    print("\n" + "=" * 80)
    print("按天统计收益")
    print("=" * 80)
    for x in range(1, hold_days + 1):
        print(f"\n第 {x} 天：")
        res_list = ratio_map[x]
        if not res_list:
            print("    无数据")
            continue
        plus_num = sum(1 for r in res_list if r > 0)
        plus_val = sum(r for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)
        minus_val = sum(r for r in res_list if r <= 0)
        print(f"    正收益次数：{plus_num}")
        if plus_num > 0 or minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(plus_val, 2)}")
        print(f"    总的负收益：{round(minus_val, 2)}")
        print_statistics(f"    第 {x} 天收益统计：", res_list)

    if total_ratio:
        print_statistics('\n总收益率：', total_ratio)
    if total_hold_days:
        print_statistics('总持有天数：', total_hold_days)

def main():
    print("=" * 80)
    print("趋势通道共振策略 (Trend Channel Resonance Strategy)")
    print("=" * 80)
    print("策略条件：")
    print("1. 买入信号：下轨线A(或下轨线B)触到趋势线后趋势线向上")
    print("2. 突破信号：收盘价上穿上轨线且强势条件成立")
    print("3. 强势条件：涨幅>3%且5日均量>30日均量")
    print("4. 共振买入 = 买入 + 突破信号")
    print("5. 共振加仓 = 加仓 + 突破信号")
    print("=" * 80)

    all_symbols = get_daily_symbols()
    print(f"共 {len(all_symbols)} 只股票待筛选")

    for idx, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{idx + 1} / {len(all_symbols)}")
        try:
            df = get_local_stock_data(symbol, '2018-01-01')
            if df is None or len(df) < 200:
                continue
            backtest_strategy(symbol, df)
            if (idx + 1) % 100 == 0:
                print_console()
        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            import traceback
            traceback.print_exc()
            continue

    print_console()

if __name__ == '__main__':
    main()

'''
================================================================================
趋势通道共振策略统计结果
================================================================================
正收益次数：14538
正收益占比：83.46%
总的正收益：126010.64
总的负收益：-5650.41

总体收益统计：
总收益：
    平均值：6.91
    最大值：87.37
    最小值：-14.33
    50% 的百分位数：4.50
    95% 的百分位数：28.17

正收益统计：
正收益：
    平均值：8.67
    最大值：87.37
    最小值：0.01
    50% 的百分位数：5.62
    95% 的百分位数：32.30

负收益统计：
负收益：
    平均值：-1.96
    最大值：0.00
    最小值：-14.33
    50% 的百分位数：-1.42
    95% 的百分位数：0.00

================================================================================
按天统计收益
================================================================================

第 1 天：
    正收益次数：11258
    正收益占比：64.63%
    总的正收益：34977.79
    总的负收益：-11590.4
    第 1 天收益统计：
    平均值：1.34
    最大值：19.81
    最小值：-15.29
    50% 的百分位数：1.02
    95% 的百分位数：7.75

第 2 天：
    正收益次数：11942
    正收益占比：68.56%
    总的正收益：91268.37
    总的负收益：-16176.11
    第 2 天收益统计：
    平均值：4.31
    最大值：70.32
    最小值：-22.05
    50% 的百分位数：2.53
    95% 的百分位数：21.19

第 3 天：
    正收益次数：10789
    正收益占比：61.94%
    总的正收益：48243.58
    总的负收益：-21557.69
    第 3 天收益统计：
    平均值：1.53
    最大值：41.01
    最小值：-27.88
    50% 的百分位数：1.16
    95% 的百分位数：10.79

第 4 天：
    正收益次数：11794
    正收益占比：67.71%
    总的正收益：101612.55
    总的负收益：-22707.8
    第 4 天收益统计：
    平均值：4.53
    最大值：87.37
    最小值：-30.19
    50% 的百分位数：2.88
    95% 的百分位数：25.45

第 5 天：
    正收益次数：10434
    正收益占比：59.9%
    总的正收益：58093.37
    总的负收益：-28338.6
    第 5 天收益统计：
    平均值：1.71
    最大值：66.08
    最小值：-30.39
    50% 的百分位数：1.17
    95% 的百分位数：13.57

总收益率：
    平均值：3.41
    最大值：58.51
    最小值：-28.31
    50% 的百分位数：2.15
    95% 的百分位数：9.76
总持有天数：
    平均值：13.63
    最大值：1803.00
    最小值：1.00
    50% 的百分位数：1.00
    95% 的百分位数：50.00
'''