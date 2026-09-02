# coding: utf-8
"""
缠论二买 组合策略回测 — 15分钟版本（无未来函数版）

策略逻辑：
    缠论二买：一买之后的回调一笔，满足：
        1. 中枢离开一笔的终点 < 当前下跌笔终点（回调不创新低）
        2. 前上涨笔终点 < 中枢上高(zg)（未突破中枢）
        3. 前上涨笔起点 < 当前下跌笔终点（回调不破位）

买入：信号出现次根15分钟K线开盘价买入
卖出：持有 hold_days 根15分钟K线后收盘价卖出

防未来函数措施：
    使用 CZSC.update(bar) 逐K线喂入数据，每次只用 c.finished_bis
    （已确认完成的笔）进行信号判断，避免笔端点被未来数据修正。
"""
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import numpy as np
from czsc_sqlite import get_local_stock_data
from czsc.utils.sig import get_zs_seq
from czsc.objects import RawBar, Freq
from czsc.analyze import CZSC
from czsc.enum import Direction, Mark

hold_days = 80  # 15分钟K线数，80根 = 5个交易日（每天16根）
BARS_PER_DAY = 16  # 每个交易日16根15分钟K线
MIN_BARS = 1000  # 15分钟数据最少需要1000根K线
NUM_DAYS = hold_days // BARS_PER_DAY  # 持有交易日数

plus_list = []
minus_list = []
day_ratio_map = {}  # {交易日: [收益率列表]}，按天统计
for x in range(1, NUM_DAYS + 1):
    day_ratio_map[x] = []
last_day_signals = []


def check_two_buy(bi_list, zs_list):
    """
    检查缠论二买点

    条件：
        1. 存在有效中枢且笔数>4
        2. 当前最后一笔为下跌笔
        3. 中枢离开笔终点 < 当前下跌笔终点（回调不创新低）
        4. 前上涨笔终点 < 中枢上高(zg)
        5. 前上涨笔起点 < 当前下跌笔终点

    返回:
        (is_buy, last_bi, last_zs) 或 (False, None, None)
    """
    if not bi_list:
        return False, None, None

    last_bi = bi_list[-1]

    if last_bi.direction != Direction.Down:
        return False, None, None

    last_zs = None
    for zs in reversed(zs_list):
        if zs.is_valid:
            last_zs = zs
            break
    if last_zs is None or len(last_zs.bis) <= 4:
        return False, None, None

    zs_last_bi = last_zs.bis[-1]
    last_up_bi = bi_list[-2]

    # 中枢离开一笔终点 < 当前下跌笔终点（回调不创新低）
    if zs_last_bi.fx_b.fx >= last_bi.fx_b.fx:
        return False, None, None

    # 中枢离开笔终点时间 <= 当前下跌笔终点时间
    if zs_last_bi.fx_b.dt >= last_bi.fx_b.dt:
        return False, None, None

    # 前上涨笔终点 < 中枢上高(zg)
    if last_up_bi.fx_b.fx >= last_zs.zg:
        return False, None, None

    # 前上涨笔起点 < 当前下跌笔终点
    if last_up_bi.fx_a.fx >= last_bi.fx_b.fx:
        return False, None, None

    return True, last_bi, last_zs


def backtest(symbol, df):
    """
    对单只股票进行回测（无未来函数版本）：
    逐K线喂入CZSC，每次只用 finished_bis（已确认完成的笔）进行信号判断。
    """
    if df is None or len(df) < MIN_BARS:
        return

    bars = []
    for i, row in df.iterrows():
        dt = row['dt'] if 'dt' in df.columns else pd.to_datetime(row['date'])
        bars.append(RawBar(
            symbol=symbol, id=i, freq=Freq.F15,
            open=row['open'], dt=dt, close=row['close'],
            high=row['high'], low=row['low'],
            vol=row['volume'], amount=row['amount']
        ))

    # 用 datetime 字符串做索引，15分钟数据格式为 "2024-01-01 09:30:00"
    date_to_index = {str(d): idx for idx, d in enumerate(df['date'])}
    last_buy_idx = -1

    c = CZSC.__new__(CZSC)
    c.verbose = False
    c.max_bi_num = 500
    c.bars_raw = []
    c.bars_ubi = []
    c.bi_list = []
    c.symbol = symbol
    c.freq = Freq.F15
    c.get_signals = None
    c.signals = None
    from collections import OrderedDict
    c.cache = OrderedDict()

    prev_bi_count = 0

    for bar in bars:
        c.update(bar)

        if len(c.bi_list) <= prev_bi_count:
            continue
        prev_bi_count = len(c.bi_list)

        finished = c.finished_bis
        if len(finished) < 6:
            continue

        zs_list = get_zs_seq(finished)

        is_buy, last_bi, last_zs = check_two_buy(finished, zs_list)
        if not is_buy:
            continue
        k1, k2, k3 = last_bi.fx_b.new_bars
        buy_date_str = k3.dt.strftime("%Y-%m-%d %H:%M")
        if buy_date_str not in date_to_index:
            continue

        buy_idx = date_to_index[buy_date_str]
        if buy_idx >= len(df):
            continue

        is_last_bar = (buy_idx >= (len(df) - 3))

        if is_last_bar:
            close_price = float(df['close'].iloc[buy_idx])
            last_day_signals.append({
                'symbol': symbol,
                'date': buy_date_str,
                'zs_zd': round(last_zs.zd, 2),
                'zs_zg': round(last_zs.zg, 2),
                'buy_price': round(close_price, 2),
                'close': round(close_price, 2),
                'low': round(float(df['low'].iloc[-1]), 2),
                'high': round(float(df['high'].iloc[-1]), 2),
                'open': round(float(df['open'].iloc[-1]), 2),
            })
            print(f"{symbol} ★最后信号★ 二买 时间：{buy_date_str}，"
                  f"中枢中低：{last_zs.zd:.2f}，中枢中高：{last_zs.zg:.2f}，收盘价：{close_price:.2f}")
            continue

        next_bar_idx = buy_idx + 1
        if next_bar_idx >= len(df):
            continue
        buy_price = float(df['open'].iloc[next_bar_idx])

        if last_buy_idx > 0 and (next_bar_idx - last_buy_idx) <= hold_days:
            continue

        sell_end = next_bar_idx + hold_days
        if sell_end >= len(df):
            continue

        print(f"{symbol} 二买 时间：{buy_date_str}，"
              f"中枢中低：{last_zs.zd:.2f}，中枢中高：{last_zs.zg:.2f}，次根开盘买入：{buy_price:.2f}")

        max_val = -1000.0
        last_buy_idx = buy_idx

        for day_num in range(1, NUM_DAYS + 1):
            day_end_idx = buy_idx + day_num * BARS_PER_DAY
            if day_end_idx >= len(df):
                break
            stock_close = float(df['close'].iloc[day_end_idx])
            ratio = round(100.0 * (stock_close - buy_price) / buy_price, 2)
            day_ratio_map[day_num].append(ratio)
            max_val = max(max_val, ratio)

        if max_val > 0:
            plus_list.append(max_val)
        else:
            minus_list.append(max_val)


def print_statistics(title, arr):
    if len(arr) == 0:
        print(f"{title}: 无数据")
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


def print_console():
    days_str = f"{hold_days}根15分钟K线" if hold_days != 80 else "5个交易日(80根15分钟)"
    print("\n" + "=" * 70)
    print(f"  缠论二买 15分钟策略（次根开盘价买入|持有{days_str}） 统计结果")
    print("=" * 70)

    total_trades = len(plus_list) + len(minus_list)
    print(f"\n总交易次数：{total_trades}")
    print(f"正收益次数：{len(plus_list)}")

    if total_trades > 0:
        win_rate = round(100 * len(plus_list) / total_trades, 2)
        print(f"正收益占比：{win_rate}%")

    total_plus = sum(plus_list) if plus_list else 0
    total_minus = sum(minus_list) if minus_list else 0
    print(f"总的正收益：{total_plus:.2f}")
    print(f"总的负收益：{total_minus:.2f}")

    all_returns = plus_list + minus_list
    if all_returns:
        print_statistics("\n总收益：", all_returns)
    if plus_list:
        print_statistics("正收益：", plus_list)
    if minus_list:
        print_statistics("负收益：", minus_list)

    for day in range(1, NUM_DAYS + 1):
        res_list = day_ratio_map[day]
        if not res_list:
            continue

        plus_num = sum(1 for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)

        print(f"\n第 {day} 个交易日：")
        print(f"    正收益次数：{plus_num}")
        if plus_num + minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(sum(r for r in res_list if r > 0), 2)}")
        print(f"    总的负收益：{round(sum(r for r in res_list if r <= 0), 2)}")
        print_statistics(f"    统计：", res_list)


def print_last_day_signals():
    print("\n" + "=" * 70)
    print("  最后出现二买信号的股票（下次可关注）")
    print("=" * 70)

    if not last_day_signals:
        print("  无信号")
        print("=" * 70)
        return

    print(f"\n  共 {len(last_day_signals)} 只股票出现信号\n")
    header = "  {:<12} {:<22} {:>8} {:>8} {:>8} {:>8}".format(
        "股票代码", "信号时间", "中枢中低", "中枢中高", "收盘价", "买入价"
    )
    print(header)
    print("  " + "-" * 72)

    for sig in sorted(last_day_signals, key=lambda x: x['symbol']):
        print("  {:<12} {:<22} {:>8.2f} {:>8.2f} {:>8.2f} {:>8.2f}".format(
            sig['symbol'], sig['date'],
            sig['zs_zd'], sig['zs_zg'],
            sig['close'], sig['buy_price']
        ))

    print("=" * 70)


if __name__ == '__main__':
    start_date = "2024-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    print(f"共 {total} 只股票，15分钟二买回测开始...")
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)

    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] {i + 1}/{total} {symbol}")
        try:
            end_date = get_latest_trade_date()
            df = get_stock_pd(symbol, start_date, end_date, '15')
            # df = get_local_stock_data(symbol, start_date, frequency='15')
            backtest(symbol, df)
        except Exception as e:
            print(f"处理 {symbol} 出错：{e}")
            import traceback
            traceback.print_exc()
            continue

        if (i + 1) % 100 == 0:
            print_console()
            print_last_day_signals()

    print_console()
    print_last_day_signals()

    if last_day_signals:
        data_dir = get_data_dir()
        write_json(last_day_signals, os.path.join(data_dir, "二买15分钟.json"))
        print(f"\n最后信号已保存到 data/二买15分钟.json")
