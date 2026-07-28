# coding: utf-8
"""
缠论三买 组合策略回测（无未来函数版）
参考 CZSCStragegy_OneBuyWBottom.py 模式实现

策略逻辑：
    缠论三买：下跌一笔突破中枢上高(zg)，满足：
        1. 当前下跌笔终点 > 中枢上高(zg)
        2. 中枢离开笔终点时间 <= 当前下跌笔终点时间
        3. 前上涨笔起点 < 中枢上高(zg)（从中枢内出发）

买入：信号出现次日开盘价买入
卖出：持有N日后收盘价卖出

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

plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []
last_day_signals = []


def check_three_buy(bi_list, zs_list):
    """
    检查缠论三买点（逻辑与 czsc_daily_util.get_buy_point_type 一致）

    条件：
        1. 存在有效中枢且笔数>4
        2. 当前最后一笔为下跌笔
        3. 当前下跌笔终点 > 中枢上高(zg)
        4. 中枢离开笔终点时间 <= 当前下跌笔终点时间
        5. 前上涨笔起点 < 中枢上高(zg)

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

    # 当前下跌笔终点 > 中枢上高(zg)
    if last_bi.fx_b.fx <= last_zs.zg:
        return False, None, None

    # 中枢离开笔终点时间 <= 当前下跌笔终点时间
    if zs_last_bi.fx_b.dt >= last_bi.fx_b.dt:
        return False, None, None

    # 前上涨笔起点 < 中枢上高(zg)
    if last_up_bi.fx_a.fx >= last_zs.zg:
        return False, None, None

    return True, last_bi, last_zs


def backtest(symbol, df):
    """
    对单只股票进行回测（无未来函数版本）：
    逐K线喂入CZSC，每次只用 finished_bis（已确认完成的笔）进行信号判断。
    """
    if df is None or len(df) < 300:
        return

    bars = []
    for i, row in df.iterrows():
        dt = row['dt'] if 'dt' in df.columns else pd.to_datetime(row['date'])
        bars.append(RawBar(
            symbol=symbol, id=i, freq=Freq.D,
            open=row['open'], dt=dt, close=row['close'],
            high=row['high'], low=row['low'],
            vol=row['volume'], amount=row['amount']
        ))

    date_to_index = {date: idx for idx, date in enumerate(df['date'])}
    last_buy_idx = -1

    c = CZSC.__new__(CZSC)
    c.verbose = False
    c.max_bi_num = 500
    c.bars_raw = []
    c.bars_ubi = []
    c.bi_list = []
    c.symbol = symbol
    c.freq = Freq.D
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

        is_buy, last_bi, last_zs = check_three_buy(finished, zs_list)
        if not is_buy:
            continue

        k1, k2, k3 = last_bi.fx_b.new_bars
        buy_date_str = k3.dt.strftime("%Y-%m-%d")
        if buy_date_str not in date_to_index:
            continue

        buy_idx = date_to_index[buy_date_str]
        if buy_idx >= len(df):
            continue

        is_last_day = (buy_idx >= (len(df) - 3))

        if is_last_day:
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
            print(f"{symbol} ★最后一天信号★ 三买 日期：{buy_date_str}，"
                  f"中枢中低：{last_zs.zd:.2f}，中枢中高：{last_zs.zg:.2f}，收盘价：{close_price:.2f}")
            continue

        next_day_idx = buy_idx + 1
        if next_day_idx >= len(df):
            continue
        buy_price = float(df['open'].iloc[next_day_idx])

        if last_buy_idx > 0 and (next_day_idx - last_buy_idx) <= hold_days:
            continue

        sell_end = next_day_idx + hold_days
        if sell_end >= len(df):
            continue

        print(f"{symbol} 三买 日期：{buy_date_str}，"
              f"中枢中低：{last_zs.zd:.2f}，中枢中高：{last_zs.zg:.2f}，次日开盘买入：{buy_price:.2f}")

        max_val = -1000.0
        last_buy_idx = buy_idx

        for day_offset in range(1, hold_days + 1):
            sell_idx = buy_idx + day_offset
            if sell_idx < len(df):
                stock_close = float(df['close'].iloc[sell_idx])
                ratio = round(100.0 * (stock_close - buy_price) / buy_price, 2)
                ratio_map[day_offset].append(ratio)
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
    print("\n" + "=" * 70)
    print("  缠论三买  策略（次日开盘价买入|持有5日） 统计结果")
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

    for x in range(1, hold_days + 1):
        res_list = ratio_map[x]
        if not res_list:
            continue

        plus_num = sum(1 for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)

        print(f"\n第 {x} 天（买入后第{x}个交易日收盘）：")
        print(f"    正收益次数：{plus_num}")
        if plus_num + minus_num > 0:
            print(f"    正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"    总的正收益：{round(sum(r for r in res_list if r > 0), 2)}")
        print(f"    总的负收益：{round(sum(r for r in res_list if r <= 0), 2)}")
        print_statistics(f"    第 {x} 天统计：", res_list)


def print_last_day_signals():
    print("\n" + "=" * 70)
    print("  最后一天出现三买信号的股票（明日可关注）")
    print("=" * 70)

    if not last_day_signals:
        print("  无信号")
        print("=" * 70)
        return

    print(f"\n  共 {len(last_day_signals)} 只股票出现信号\n")
    header = "  {:<12} {:<12} {:>8} {:>8} {:>8} {:>8}".format(
        "股票代码", "信号日期", "中枢中低", "中枢中高", "收盘价", "买入价"
    )
    print(header)
    print("  " + "-" * 62)

    for sig in sorted(last_day_signals, key=lambda x: x['symbol']):
        print("  {:<12} {:<12} {:>8.2f} {:>8.2f} {:>8.2f} {:>8.2f}".format(
            sig['symbol'], sig['date'],
            sig['zs_zd'], sig['zs_zg'],
            sig['close'], sig['buy_price']
        ))

    print("=" * 70)


if __name__ == '__main__':
    start_date = "2024-01-01"
    all_symbols = get_daily_symbols()
    total = len(all_symbols)
    print(f"共 {total} 只股票，开始回测...")
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)

    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] {i + 1}/{total} {symbol}")
        try:
            end_date = get_latest_trade_date()
            df = get_stock_pd(symbol, start_date, end_date, 'd')
            # df = get_local_stock_data(symbol, start_date)
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
        write_json(last_day_signals, os.path.join(data_dir, "三买.json"))
        print(f"\n最后一天信号已保存到 data/三买.json")
