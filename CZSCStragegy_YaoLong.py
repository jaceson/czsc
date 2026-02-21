# coding: utf-8
"""
通达信妖股/金龙突破公式策略
参考 CZSCStragegy_Goldenline.py 的统计与主流程，实现公式：
  妖、妖股起飞、主力拉涨 三合一信号，信号日次日开盘价买入。
"""
import os
import sys
import pandas as pd
import numpy as np
from lib.MyTT import (
    REF, EMA, MA, HHV, LLV, STD, DMA, CROSS, IF, ABS, MAX, MIN,
)
from czsc_daily_util import get_daily_symbols
from czsc_sqlite import get_local_stock_data

# 统计变量（与 Goldenline / FormulaSignal 一致）
plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []


def calculate_yao_indicators(df):
    """
    计算通达信公式中所有中间变量及最终信号。
    df 需包含: open, high, low, close, date
    返回: 添加了指标列的 DataFrame，以及最终信号序列 signal_yao（妖 OR 妖股起飞 OR 主力拉涨）
    """
    C = df['close'].values
    O = df['open'].values
    H = df['high'].values
    L = df['low'].values
    n = len(C)

    # VAR1:=C/REF(C,1)>1.03;
    ref_c1 = REF(C, 1)
    VAR1 = (C / (ref_c1 + 1e-10)) > 1.03

    # VAR2:=EMA(C,9);
    VAR2 = EMA(C, 9)

    # VAR3:=EMA(VAR2*1.13,5); VAR5:=EMA(VAR2*1.12,5); VAR6:=EMA(VAR2*1.11,5);
    VAR3 = EMA(VAR2 * 1.13, 5)
    VAR5 = EMA(VAR2 * 1.12, 5)
    VAR6 = EMA(VAR2 * 1.11, 5)

    # VAR4:=C>=OPEN;
    VAR4 = C >= O

    # VAR7:=CROSS(C,VAR6); VAR8:=CROSS(C,VAR3); VAR9:=CROSS(C,VAR5);
    VAR7 = CROSS(C, VAR6)
    VAR8 = CROSS(C, VAR3)
    VAR9 = CROSS(C, VAR5)

    # VAR10:=(VAR8 OR VAR9 OR VAR7 AND VAR4 AND VAR1);
    VAR10 = VAR8 | VAR9 | (VAR7 & VAR4 & VAR1)

    # VAR11:=HHV(HHV(L,14),60);
    hhv_l_14 = HHV(L, 14)
    VAR11 = HHV(hhv_l_14, 60)

    # VAR12:=HHV(MA((L+H+C)/3,8),60);
    typ = (L + H + C) / 3.0
    ma_typ_8 = MA(typ, 8)
    VAR12 = HHV(ma_typ_8, 60)

    # VAR13:=EMA(EMA(VAR12,14)+2*STD(VAR11,14),4);
    VAR13 = EMA(EMA(VAR12, 14) + 2 * STD(VAR11, 14), 4)

    # 妖:=C>VAR12 AND C>VAR13 AND VAR10;
    yao = (C > VAR12) & (C > VAR13) & VAR10

    # 妖龙起飞A:=IF((C>REF(C,1)),88,0);
    yao_long_a = IF(C > ref_c1, 88, 0)

    # 妖龙起飞B:=IF((C/REF(C,1)>1.05) AND (HIGH/C<1.01) AND (妖龙起飞A>0),91,0);
    yao_long_b = IF(
        (C / (ref_c1 + 1e-10) > 1.05) & (H / (C + 1e-10) < 1.01) & (yao_long_a > 0),
        91, 0,
    )

    # 捉妖筹码:=(FILTER((妖龙起飞B>90),45));
    # FILTER 会原地修改，传入副本
    filter_input = np.array(yao_long_b > 90, dtype=float)
    zhuo_yao_chou_ma = _filter_copy(filter_input, 45)

    # 妖股起飞:=捉妖筹码>0;
    yao_gu_feixing = zhuo_yao_chou_ma > 0

    # 金龙突破相关
    # VAR21:=ABS(((3.48*C+H+L)/4-EMA(C,23))/EMA(C,23));
    ema_c_23 = EMA(C, 23)
    typ2 = (3.48 * C + H + L) / 4.0
    VAR21 = ABS((typ2 - ema_c_23) / (ema_c_23 + 1e-10))

    # VAR22:=DMA(((2.15*C+L+H)/4),VAR21);
    dma_input = (2.15 * C + L + H) / 4.0
    VAR22 = DMA(dma_input, VAR21)

    # 金龙突破:=EMA(VAR22,200)*1.118;
    jin_long_tupo = EMA(VAR22, 200) * 1.118

    # 条件:=(C-REF(C,1))/REF(C,1)*100>8;
    tiaojian = (C - ref_c1) / (ref_c1 + 1e-10) * 100 > 8

    # 金K线:=CROSS(C,金龙突破) AND 条件; 主力拉涨:=金K线;
    jin_kx = CROSS(C, jin_long_tupo) & tiaojian
    zhuli_lazhang = jin_kx

    # 最终信号: 妖 OR 妖股起飞 OR 主力拉涨
    signal_yao = yao and yao_gu_feixing and zhuli_lazhang

    ndf = df.copy()
    ndf['yao'] = yao
    ndf['yao_gu_feixing'] = yao_gu_feixing
    ndf['zhuli_lazhang'] = zhuli_lazhang
    ndf['signal_yao'] = signal_yao
    ndf['VAR12'] = VAR12
    ndf['VAR13'] = VAR13
    ndf['jin_long_tupo'] = jin_long_tupo
    return ndf, signal_yao


def _filter_copy(S, N):
    """FILTER 的副本版本，不修改原数组。S 为布尔或数值序列，返回同长度数组，满足条件且未被过滤的位置为 1 否则为 0。"""
    S = np.array(S, dtype=float)
    out = S.copy()
    for i in range(len(out)):
        if out[i]:
            out[i + 1 : i + 1 + N] = 0
    return out


def get_yao_signal_condition(symbol, df):
    """
    获取妖/妖股起飞/主力拉涨 信号条件（布尔序列）。
    需至少 250 根 K 线以计算 EMA(VAR22,200) 等。
    """
    if df is None or len(df) < 250:
        return pd.Series([False] * len(df), index=df.index) if df is not None else None
    ndf, signal_yao = calculate_yao_indicators(df)
    return pd.Series(signal_yao, index=df.index).fillna(False)


def get_yao_signal_buy_point(symbol, df):
    """
    信号日次日开盘价买入，统计 hold_days 内收益（与 Goldenline/FormulaSignal 一致）。
    """
    if df is None or len(df) < 250:
        return
    buy_con = get_yao_signal_condition(symbol, df)
    if not buy_con.any():
        return

    last_buy_index = -1
    ndf, _ = calculate_yao_indicators(df)

    for idx in df.index[buy_con]:
        # 信号日
        signal_index = df.index.get_loc(idx)
        buy_index = signal_index + 1
        if buy_index >= len(df):
            continue
        if last_buy_index >= 0 and (signal_index - last_buy_index) <= hold_days:
            continue

        buy_date = df['date'].iloc[buy_index]
        buy_price = df['open'].iloc[buy_index]
        signal_date = df['date'].iloc[signal_index]
        last_buy_index = signal_index

        # 标记信号类型
        yao = ndf['yao'].iloc[signal_index]
        yao_gu = ndf['yao_gu_feixing'].iloc[signal_index]
        zhuli = ndf['zhuli_lazhang'].iloc[signal_index]
        types = []
        if yao:
            types.append('妖')
        if yao_gu:
            types.append('妖股起飞')
        if zhuli:
            types.append('主力拉涨')
        type_str = '+'.join(types)

        print(
            "{} 信号:{} 日期:{} 买入:{} 价格:{:.2f}".format(
                symbol, type_str, signal_date, buy_date, buy_price
            )
        )

        max_val = -1000
        for d in range(1, hold_days + 1):
            sell_index = buy_index + d
            if sell_index < len(df):
                sell_close = df['close'].iloc[sell_index]
                ratio = round(100 * (sell_close - buy_price) / buy_price, 2)
                ratio_map[d].append(ratio)
                max_val = max(max_val, ratio)
        if max_val > 0:
            plus_list.append(max_val)
            print("  最大收益: {:.2f}%".format(max_val))
        else:
            minus_list.append(max_val)
            print("  最大亏损: {:.2f}%".format(max_val))


def print_console(title, arr):
    """与 Goldenline 一致的统计输出。"""
    if len(arr) == 0:
        print("{}: 无数据".format(title))
        return
    average = np.mean(arr)
    max_value = np.max(arr)
    min_value = np.min(arr)
    p50 = np.percentile(arr, 50)
    p95 = np.percentile(arr, 95)
    print(title)
    print("    平均值：{:.2f}".format(average))
    print("    最大值：{:.2f}".format(max_value))
    print("    最小值：{:.2f}".format(min_value))
    print("    50% 的百分位数：{:.2f}".format(p50))
    print("    95% 的百分位数：{:.2f}".format(p95))


def print_statistics():
    """打印妖股/金龙策略统计（参考 Goldenline）。"""
    print("=" * 80)
    print("通达信妖股/金龙突破策略统计结果")
    print("=" * 80)
    print("正收益次数：{}".format(len(plus_list)))
    total = len(plus_list) + len(minus_list)
    if total > 0:
        print("正收益占比：{:.2f}%".format(100 * len(plus_list) / total))
    total_plus = sum(plus_list)
    total_minus = sum(minus_list)
    print("总的正收益：{:.2f}".format(total_plus))
    print("总的负收益：{:.2f}".format(total_minus))

    all_returns = plus_list + minus_list
    if all_returns:
        print("\n总体收益统计：")
        print_console("总收益：", all_returns)
    if plus_list:
        print("\n正收益统计：")
        print_console("正收益：", plus_list)
    if minus_list:
        print("\n负收益统计：")
        print_console("负收益：", minus_list)

    print("\n" + "=" * 80)
    print("按天统计收益")
    print("=" * 80)
    for d in range(1, hold_days + 1):
        res_list = ratio_map[d]
        print("\n第 {} 天：".format(d))
        if not res_list:
            print("    无数据")
            continue
        plus_num = sum(1 for r in res_list if r > 0)
        minus_num = len(res_list) - plus_num
        plus_val = sum(r for r in res_list if r > 0)
        minus_val = sum(r for r in res_list if r <= 0)
        print("    正收益次数：{}".format(plus_num))
        if plus_num + minus_num > 0:
            print("    正收益占比：{:.2f}%".format(100 * plus_num / (plus_num + minus_num)))
        print("    总的正收益：{:.2f}".format(plus_val))
        print("    总的负收益：{:.2f}".format(minus_val))
        print_console("    第 {} 天收益统计：".format(d), res_list)


def main():
    """主函数：遍历全市场，信号日次日开盘价买入，统计 hold_days 收益。"""
    print("=" * 80)
    print("通达信妖股/金龙突破公式策略")
    print("=" * 80)
    print("信号：妖 OR 妖股起飞 OR 主力拉涨")
    print("买入：信号日次日开盘价")
    print("=" * 80)

    all_symbols = get_daily_symbols()
    print("共 {} 只股票待筛选".format(len(all_symbols)))
    print("=" * 80)

    for idx, symbol in enumerate(all_symbols):
        print(
            "[{}] 进度：{} / {}".format(
                pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), idx + 1, len(all_symbols)
            )
        )
        try:
            df = get_local_stock_data(symbol, "2000-01-01")
            if df is None or len(df) < 250:
                continue
            get_yao_signal_buy_point(symbol, df)
            if (idx + 1) % 100 == 0:
                print_statistics()
        except Exception as e:
            print("处理 {} 时出错: {}".format(symbol, e))
            import traceback
            traceback.print_exc()
            continue

    print_statistics()


if __name__ == "__main__":
    main()
