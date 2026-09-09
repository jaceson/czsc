# coding: utf-8
"""
出水芙蓉 - 增强过滤版
参考通达信公式实现

选股条件（通达信公式）：
    N1 := 5;  N2 := 10;  N3 := 20;
    VOL_RATIO_LOW := 1.5;   { 放量下限 }
    VOL_RATIO_HIGH := 3.5;  { 放量上限（防止异常天量） }
    MA1 := MA(CLOSE, N1);   MA2 := MA(CLOSE, N2);  MA3 := MA(CLOSE, N3);

    1. 前日收盘价贴近均线簇（放宽至3%）
       COND_BREAK := REF(CLOSE,1) <= MAX3*1.03 AND REF(CLOSE,1) >= MIN3*0.97;
    2. 今日收盘价站上所有均线
       COND_CROSS := CLOSE>MA1 AND CLOSE>MA2 AND CLOSE>MA3;
    3. 涨幅大于4%
       COND_LONG := CLOSE/OPEN > 1.04;
    4. 均线趋势过滤（MA5>MA10>MA20 且三条均线均向上）
       COND_MA_UP := MA1>MA2 AND MA2>MA3 AND MA1>REF(MA1,1) AND MA2>REF(MA2,1) AND MA3>REF(MA3,1);
    5. K线质量：实体占振幅70%以上
       COND_KQL := (CLOSE-OPEN)/(HIGH-LOW) > 0.7;
    6. 温和放量（放大1.5~3.5倍）
       COND_VOL := VOL>MA(VOL,5)*1.5 AND VOL<MA(VOL,5)*3.5;
    7. （可选）大盘过滤：大盘在20日均线之上
       MARKET_OK := INDEXC > MA(INDEXC,20);

买入：信号当日收盘价买入
卖出：最多持有 hold_days(5) 天，盈利超过5%止盈
"""
import os
import sys
import pandas as pd
import numpy as np
from czsc_daily_util import *
from lib.MyTT import *
from czsc_sqlite import get_local_stock_data

# ========== 参数设置 ==========
N1 = 5
N2 = 10
N3 = 20
VOL_RATIO_LOW = 1.5   # 放量下限
VOL_RATIO_HIGH = 3.5  # 放量上限（防止异常天量）
TAKE_PROFIT = 5.0     # 止盈百分比（%）
hold_days = 5         # 最多持有天数
USE_MARKET_FILTER = True  # 是否启用大盘过滤（True=启用，False=关闭）

# 大盘指数代码（上证指数）
大盘指数代码 = "sh.000001"

# 全局变量：大盘指数数据缓存
_index_data_cache = None

# 收益统计变量
plus_list = []
minus_list = []
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

# 止盈/到期统计
take_profit_count = 0
expire_count = 0


def print_console(title, arr):
    """打印统计信息"""
    if len(arr) == 0:
        print(f"{title}：无数据")
        return

    average = np.mean(arr)
    max_value = np.max(arr)
    min_value = np.min(arr)
    p50 = np.percentile(arr, 50)
    p95 = np.percentile(arr, 95)

    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 百分位：{p50:.2f}")
    print(f"    95% 百分位：{p95:.2f}")


def get_index_data(start_date='2000-01-01'):
    """获取大盘指数数据（缓存）"""
    global _index_data_cache
    if _index_data_cache is None:
        try:
            _index_data_cache = get_local_stock_data(大盘指数代码, start_date)
            if _index_data_cache is None or len(_index_data_cache) == 0:
                print(f"警告：无法获取大盘指数数据 {大盘指数代码}，大盘过滤将被禁用")
                _index_data_cache = pd.DataFrame()
        except Exception as e:
            print(f"获取大盘指数数据失败：{e}")
            _index_data_cache = pd.DataFrame()
    return _index_data_cache


def calculate_market_filter(df):
    """
    计算大盘过滤条件
    MARKET_OK := INDEXC > MA(INDEXC, 20);
    无法获取指数数据时返回全 True（不进行过滤）
    """
    index_df = get_index_data()
    if index_df is None or len(index_df) == 0:
        return pd.Series([True] * len(df), index=df.index)

    merged_df = pd.merge(df[['date']], index_df[['date', 'close']], on='date', how='left')
    merged_df = merged_df.sort_values('date').reset_index(drop=True)

    INDEXC = merged_df['close'].values
    INDEXC_MA20 = MA(INDEXC, 20)
    大盘过滤 = INDEXC > INDEXC_MA20

    市场过滤 = pd.Series([True] * len(df), index=df.index)
    for i, date in enumerate(df['date']):
        idx = merged_df[merged_df['date'] == date].index
        if len(idx) > 0:
            j = idx[0]
            if j < len(大盘过滤):
                市场过滤.iloc[i] = 大盘过滤[j]

    return 市场过滤.fillna(True)


def get_formula_condition(df):
    """
    计算出水芙蓉-增强版选股条件
    Returns:
        pd.Series: 布尔序列，True 表示满足选股条件
    """
    close = df['close'].values.astype(float)
    open_ = df['open'].values.astype(float)
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    vol = df['volume'].values.astype(float)

    # 均线
    MA1 = MA(close, N1)
    MA2 = MA(close, N2)
    MA3 = MA(close, N3)

    MAX3 = MAX(MAX(MA1, MA2), MA3)
    MIN3 = MIN(MIN(MA1, MA2), MA3)

    # 1. 前日收盘价贴近均线簇（放宽至3%）
    COND_BREAK = (REF(close, 1) <= MAX3 * 1.03) & (REF(close, 1) >= MIN3 * 0.97)

    # 2. 今日收盘价站上所有均线
    COND_CROSS = (close > MA1) & (close > MA2) & (close > MA3)

    # 3. 涨幅大于4%
    COND_LONG = close / (open_ + 1e-10) > 1.04

    # 4. 均线趋势过滤（MA5>MA10>MA20 且三条均线均向上）
    COND_MA_UP = ((MA1 > MA2) & (MA2 > MA3) &
                  (MA1 > REF(MA1, 1)) & (MA2 > REF(MA2, 1)) & (MA3 > REF(MA3, 1)))

    # 5. K线质量：实体占振幅70%以上
    COND_KQL = (close - open_) / (high - low + 1e-10) > 0.7

    # 6. 温和放量（放大1.5~3.5倍，排除主力对倒放量出货）
    VOL_MA5 = MA(vol, 5)
    COND_VOL = (vol > VOL_MA5 * VOL_RATIO_LOW) & (vol < VOL_MA5 * VOL_RATIO_HIGH)

    condition = (COND_BREAK & COND_CROSS & COND_LONG &
                 COND_MA_UP & COND_KQL & COND_VOL)

    # 7. （可选）大盘过滤
    if USE_MARKET_FILTER:
        market_ok = calculate_market_filter(df)
        condition = condition & market_ok

    return pd.Series(condition, index=df.index)


def backtest(symbol, df):
    """
    对单只股票进行回测
    信号当日收盘价买入，最多持有 hold_days 天，盈利超过 TAKE_PROFIT% 止盈
    """
    global take_profit_count, expire_count

    if df is None or len(df) < 300:
        return

    condition = get_formula_condition(df)
    if not condition.any():
        return

    signal_indices = df[condition].index
    last_buy_idx = -1

    for idx in signal_indices:
        # 持仓期间不再开新仓（最多持有 hold_days 天）
        if last_buy_idx > 0 and (idx - last_buy_idx) <= hold_days:
            continue

        if idx + hold_days >= len(df):
            continue

        buy_price = float(df['close'].iloc[idx])
        buy_date = df['date'].iloc[idx]

        print(f"{symbol} 信号日期：{buy_date}，买入价格：{buy_price:.2f}")

        max_val = -1000.0
        last_buy_idx = idx
        sell_type = "到期"

        realized = -1000.0
        for day_offset in range(1, hold_days + 1):
            sell_idx = idx + day_offset
            if sell_idx < len(df):
                stock_close = float(df['close'].iloc[sell_idx])
                ratio = round(100.0 * (stock_close - buy_price) / buy_price, 2)
                ratio_map[day_offset].append(ratio)
                max_val = max(max_val, ratio)
                realized = ratio

                # 止盈：盈利超过 5% 立即卖出，取实际成交收益率
                if ratio > TAKE_PROFIT:
                    sell_type = "止盈"
                    break

        # 用实际止盈收益率或到期最大收益作为交易结果
        trade_ret = realized if sell_type == "止盈" else max_val
        if trade_ret > 0:
            plus_list.append(trade_ret)
        else:
            minus_list.append(trade_ret)

        if sell_type == "止盈":
            take_profit_count += 1
        else:
            expire_count += 1


def print_console():
    """打印最终统计结果"""
    global take_profit_count, expire_count

    print("\n" + "=" * 70)
    print("  出水芙蓉 - 增强过滤版  统计结果")
    print("=" * 70)
    print(f"  持有天数上限：{hold_days} 天，止盈线：{TAKE_PROFIT}%")
    print(f"  大盘过滤：{'启用' if USE_MARKET_FILTER else '关闭'}")

    total_trades = len(plus_list) + len(minus_list)
    print(f"\n总交易次数：{total_trades}")
    print(f"正收益次数：{len(plus_list)}")

    if total_trades > 0:
        win_rate = round(100 * len(plus_list) / total_trades, 2)
        print(f"正收益占比：{win_rate}%")
        print(f"止盈次数：{take_profit_count}")
        print(f"到期卖出次数：{expire_count}")

    total_plus = sum(plus_list) if plus_list else 0
    total_minus = sum(minus_list) if minus_list else 0
    print(f"总的正收益：{total_plus:.2f}")
    print(f"总的负收益：{total_minus:.2f}")

    all_returns = plus_list + minus_list
    if all_returns:
        print_console("\n总收益：", all_returns)
    if plus_list:
        print_console("正收益：", plus_list)
    if minus_list:
        print_console("负收益：", minus_list)

    for x in range(1, hold_days + 1):
        res_list = ratio_map[x]
        if not res_list:
            continue

        plus_num = sum(1 for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)

        print(f"\n第 {x} 天：")
        print(f"    正收益次数：{plus_num}")
        if plus_num + minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(sum(r for r in res_list if r > 0), 2)}")
        print(f"    总的负收益：{round(sum(r for r in res_list if r <= 0), 2)}")
        print_console(f"    第 {x} 天统计：", res_list)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ('1', 'true', 'True'):
            USE_MARKET_FILTER = True
        elif arg in ('0', 'false', 'False'):
            USE_MARKET_FILTER = False

    print(f"大盘过滤启用状态：{USE_MARKET_FILTER}")

    start_date = "2015-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    print(f"共 {total} 只股票，开始回测...")

    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] {i + 1}/{total} {symbol}")
        try:
            df = get_local_stock_data(symbol, start_date)
            backtest(symbol, df)
        except Exception as e:
            print(f"处理 {symbol} 出错：{e}")
            import traceback
            traceback.print_exc()
            continue

        if (i + 1) % 100 == 0:
            print_console()

    print_console()
