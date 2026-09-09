# coding: utf-8
"""
仙人指路选股策略回测
公式逻辑：
    TUPO:=0.5*(C+H)>HHV(REF(C,1),60);           -- 突破：(收盘+最高)/2 > 60日内昨日收盘的最高价
    SSQS:=MA(C,5)>MA(C,60) AND MA(C,10)>MA(C,60); -- 上升趋势：5日10日均线在60日之上
    YINX:=(H-MAX(O,C))/REF(C,1)>0.045             -- 影线：上影线占比>4.5%
          AND ABS(C-O)/REF(C,1)<0.035              -- 实体小：<3.5%
          AND (H-MAX(O,C))>2.0*ABS(C-O);           -- 上影线>2倍实体
    QIANG:=IF(FINANCE(3)=2/3/4,                    -- 强势：创业板/科创板/北交所放宽条件
              REF(C,1)/REF(C,6)<1.27,
              REF(C,1)/REF(C,6)<1.18)  AND >1.04;
    QIANK:=REF((H-C),1)/REF(C,2)<1.045            -- 前K线：上影线小，且非大阴线
           AND REF(C,1)/REF(C,2)>0.97;
    信号日收盘满足以上全部条件，次日开盘价买入，持有N日后收盘卖出
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
total_ratio = []
total_hold_days = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []


def calculate_xrlz_indicators(df):
    """
    计算仙人指路公式的所有指标

    参数:
        df: 股票数据DataFrame，需要包含：open, close, high, low, volume, amount

    返回:
        DataFrame: 添加了条件列的DataFrame
    """
    ndf = df.copy()

    close = ndf['close'].values
    high = ndf['high'].values
    opn = ndf['open'].values

    # TUPO:=0.5*(C+H) > HHV(REF(C,1),60)
    # REF(C,1) = 昨日收盘, HHV(...,60) = 60日内该序列的最大值
    ref_c1 = REF(close, 1)
    hhv_ref_c1_60 = HHV(ref_c1, 60)
    ndf['ref_c1'] = ref_c1
    ndf['hhv_ref_c1_60'] = hhv_ref_c1_60
    ndf['TUPO'] = (0.5 * (close + high) > hhv_ref_c1_60)

    # SSQS:=MA(C,5)>MA(C,60) AND MA(C,10)>MA(C,60)
    ma5 = MA(close, 5)
    ma10 = MA(close, 10)
    ma60 = MA(close, 60)
    ndf['MA5'] = ma5
    ndf['MA10'] = ma10
    ndf['MA60'] = ma60
    ndf['SSQS'] = (ma5 > ma60) & (ma10 > ma60)

    # YINX 条件
    # (H-MAX(O,C))/REF(C,1) > 0.045
    upper_shadow = high - np.maximum(opn, close)
    ref_c1_for_ratio = REF(close, 1)
    yinx_shadow = upper_shadow / (ref_c1_for_ratio + 1e-10) > 0.045
    # ABS(C-O)/REF(C,1) < 0.035
    yinx_body = np.abs(close - opn) / (ref_c1_for_ratio + 1e-10) < 0.035
    # (H-MAX(O,C)) > 2.0*ABS(C-O)
    yinx_compare = upper_shadow > 2.0 * np.abs(close - opn)
    ndf['YINX'] = yinx_shadow & yinx_body & yinx_compare

    # QIANG 条件
    # FINANCE(3): 1=沪市主板, 2=深市主板, 3=创业板, 4=科创板
    # QIANG2(宽): 深市主板/创业板/科创板, REF(C,1)/REF(C,6) 在 1.04~1.27
    # QIANG1(严): 沪市主板, REF(C,1)/REF(C,6) 在 1.04~1.18
    qiang_ratio = REF(close, 1) / (REF(close, 6) + 1e-10)
    ndf['QIANG'] = (qiang_ratio > 1.04) & (qiang_ratio < 1.18)

    # QIANK:=REF((H-C),1)/REF(C,2)<1.045 AND REF(C,1)/REF(C,2)>0.97
    ref_h_minus_c_1 = REF(high - close, 1)
    ref_c2 = REF(close, 2)
    qiank_shadow = ref_h_minus_c_1 / (ref_c2 + 1e-10) < 1.045
    qiank_close = REF(close, 1) / (ref_c2 + 1e-10) > 0.97
    ndf['QIANK'] = qiank_shadow & qiank_close

    # 综合选股条件
    ndf['SIGNAL'] = ndf['TUPO'] & ndf['SSQS'] & ndf['YINX'] & ndf['QIANG'] & ndf['QIANK']

    return ndf


def get_xrlz_buy_point(symbol, df):
    """
    仙人指路策略买入点检测

    信号日满足全部条件，次日开盘价买入，持有 hold_days 日后收盘卖出
    根据股票代码自动判断板块（沪市主板用QIANG1，其余用QIANG2）

    参数:
        symbol: 股票代码
        df: 股票数据DataFrame
    """
    global plus_list, minus_list, total_ratio, total_hold_days

    last_start_index = -1

    # 需要足够的数据计算 MA60 和 REF
    if df is None or len(df) < 70:
        return

    ndf = calculate_xrlz_indicators(df)

    # 根据股票代码判断板块，决定QIANG条件
    # 沪市主板(60xxxx)用QIANG1(4%~18%)，其余用QIANG2(4%~27%)
    code_str = str(symbol)
    is_sh_main = code_str.startswith('60')
    if not is_sh_main:
        # 深市主板(00xxxx)、创业板(30xxxx)、科创板(688xxx) 用QIANG2
        qiang_ratio_vals = REF(ndf['close'].values, 1) / (REF(ndf['close'].values, 6) + 1e-10)
        ndf['QIANG'] = (qiang_ratio_vals > 1.04) & (qiang_ratio_vals < 1.27)
        ndf['SIGNAL'] = ndf['TUPO'] & ndf['SSQS'] & ndf['YINX'] & ndf['QIANG'] & ndf['QIANK']

    buy_con = ndf['SIGNAL'].fillna(False)

    if not ndf[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        for idx in selected_indexs:
            signal_date = df['date'].iloc[idx]
            signal_index = idx

            # 避免频繁买入（至少间隔 hold_days 天）
            if last_start_index > 0 and (signal_index - last_start_index) <= hold_days:
                continue

            # 次日开盘价买入
            buy_index = signal_index + 1
            if buy_index >= len(df):
                continue

            buy_date = df['date'].iloc[buy_index]
            buy_price = df['open'].iloc[buy_index]  # 次日开盘价

            # 打印选股详情
            tup_val = 0.5 * (df['close'].iloc[signal_index] + df['high'].iloc[signal_index])
            hhv_val = ndf['hhv_ref_c1_60'].iloc[signal_index]
            print(f"{symbol} 信号日期：{signal_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}，"
                  f"TUPO值：{tup_val:.2f}，HHV(REF(C,1),60)：{hhv_val:.2f}")

            max_val = -1000
            last_start_index = signal_index

            # 计算持有期收益
            for day_offset in range(1, hold_days + 1):
                sell_index = buy_index + day_offset
                if sell_index < len(df):
                    sell_price = df['close'].iloc[sell_index]
                    ratio = round(100 * (sell_price - buy_price) / buy_price, 2)
                    ratio_map[day_offset].append(ratio)
                    max_val = max(max_val, ratio)

            if max_val > 0:
                plus_list.append(max_val)
                total_ratio.append(max_val)
                print(f"  最大收益: {max_val:.2f}%")
            else:
                minus_list.append(max_val)
                total_ratio.append(max_val)
                print(f"  最大亏损: {max_val:.2f}%")


def print_statistics(title, arr):
    """
    打印统计信息：平均值、最大值、最小值、50%和95%的百分位数
    """
    if len(arr) == 0:
        print(f"{title}: 无数据")
        return

    average = np.mean(arr)
    max_value = np.max(arr)
    min_value = np.min(arr)
    percentile_50 = np.percentile(arr, 50)
    percentile_95 = np.percentile(arr, 95)

    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 的百分位数：{percentile_50:.2f}")
    print(f"    95% 的百分位数：{percentile_95:.2f}")


def print_console(symbol_count=None):
    """
    打印统计结果（参考 CZSCStragegy_Goldenline.py）
    """
    prefix = ""
    if symbol_count is not None:
        prefix = f"\n=== 已处理 {symbol_count} 个symbol的统计结果 ===\n"
    else:
        prefix = "\n=== 最终统计结果 ===\n"

    print(prefix)
    print("=" * 60)
    print("仙人指路选股策略统计结果")
    print("=" * 60)

    # 基本统计
    print("正收益次数：" + str(len(plus_list)))
    if len(minus_list) > 0 or len(plus_list) > 0:
        print("正收益占比：" + str(round(100 * len(plus_list) / (len(minus_list) + len(plus_list)), 2)) + "%")

    total_pos = sum(plus_list) if plus_list else 0
    total_neg = sum(minus_list) if minus_list else 0
    print("总的正收益：" + str(round(total_pos, 2)))
    print("总的负收益：" + str(round(total_neg, 2)))

    # 每天统计
    for x in range(1, hold_days + 1):
        print(f"\n第 {x} 天：")
        res_list = ratio_map[x]
        if len(res_list) == 0:
            print("    无数据")
            continue

        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for ratio in res_list:
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

        if len(res_list) > 0:
            print_statistics("    第 {} 天收益统计：".format(x), res_list)

    # 总体统计
    if len(total_ratio) > 0:
        print("\n总体收益统计：")
        print_statistics('总收益：', total_ratio)
    if len(total_hold_days) > 0:
        print_statistics('总持有天数：', total_hold_days)
    if len(plus_list) > 0:
        print_statistics('正收益：', plus_list)
    if len(minus_list) > 0:
        print_statistics('负收益：', minus_list)


def main():
    """主函数：执行仙人指路选股策略"""
    print("=" * 60)
    print("仙人指路选股策略回测")
    print("=" * 60)
    print("策略条件：")
    print("1. TUPO：(收盘价+最高价)/2 > 60日内昨日收盘的最高价")
    print("2. SSQS：5日/10日均线均在60日均线之上")
    print("3. YINX：上影线占比>4.5%，实体<3.5%，上影线>2倍实体")
    print("4. QIANG：前一日相对6日涨幅在4%~18%（主板）或4%~27%（创业板等）")
    print("5. QIANK：前一日上影线小且非大阴线")
    print(f"持有天数：{hold_days}天，次日开盘价买入")
    print("=" * 60)

    # 获取所有股票代码
    all_symbols = get_daily_symbols()
    print(f"共 {len(all_symbols)} 只股票待筛选")
    print("=" * 60)

    for idx, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{idx + 1} / {len(all_symbols)}")

        try:
            df = get_local_stock_data(symbol, '2000-01-01')
            if df is None or len(df) < 70:
                continue

            # 根据股票代码自动判断板块选择强势条件
            get_xrlz_buy_point(symbol, df)

            if (idx + 1) % 100 == 0:
                print_console(idx + 1)

        except Exception as e:
            print(f"处理 {symbol} 时出错: {e}")
            import traceback
            traceback.print_exc()
            continue

    # 最终统计
    print_console()


if __name__ == '__main__':
    main()
