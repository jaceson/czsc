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
import baostock as bs
from lib.MyTT import *
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data

plus_list = []
minus_list = []
total_ratio = []
total_hold_days = []
exit_kind_counts = {}          # 卖出方式分布：开盘价 / 收盘价 / 到期收盘价
hold_days = 10
# 默认使用优化后的信号。将其设为 False 可恢复原公式信号，便于做前后对照。
USE_OPTIMIZED_SIGNAL = True
SIGNAL_COLUMN = '总共振优化'

TAKE_PROFIT_RATE = 0.02        # 优化后的止盈收益率：2% 更贴近信号的短线持有周期
RAW_TAKE_PROFIT_RATE = 0.03    # 原公式对照组保持原脚本的 3% 止盈口径
MAX_ENTRY_GAP = 0.03           # 次日开盘相对信号日收盘最多跳空 3%，避免追高
MIN_PRICE_ABOVE_MA = 0.02      # 收盘至少高于 MA20 / MA60 2%
MIN_MA20_SLOPE = 0.005         # 5 日 MA20 斜率至少为 0.5%
MAX_SIGNAL_RANGE = 0.08        # 信号日振幅不超过 8%
MIN_CLOSE_POSITION = 0.50      # 收盘不低于当日振幅中点
MAX_VOLUME_RATIO = 3.0         # 信号日量比前一日不超过 3 倍
CHANNEL_EQUAL_ATOL = 1e-8      # 通道触碰判断的价格绝对容差
CHANNEL_EQUAL_RTOL = 1e-8      # 通道触碰判断的价格相对容差

# 逐笔交易明细，供组合资金曲线使用：
#   {symbol, entry_date, exit_date, entry_price, exit_price, ret, kind, marks}
#   marks 是 {日期: 收盘价}，覆盖整个持有期，用于逐日估值
trade_records = []

# 全部交易日的并集（由 backtest_strategy 填充），用于逐日结算时补全空白日
trading_calendar = set()

# 是否逐笔打印买卖明细
VERBOSE_TRADES = True

# ---------------- 组合资金曲线参数 ----------------
INIT_CAPITAL = 400000.0     # 初始资金
POSITION_SIZE = 0.05            # 每笔交易占用「入场时组合权益」的比例
FEE_RATE = 0.0                 # 单边手续费率（买入、卖出各收一次），如 0.0003
BACKTEST_START_DATE = os.getenv('CZSC_START_DATE', '2026-01-01')

ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

_symbol_name_map = None


def _is_excluded_symbol(symbol):
    """实现公式中的排除 ST 和科创板 688 条件。"""
    code = str(symbol).split('.')[-1].strip()
    if code.startswith('688'):
        return True

    global _symbol_name_map
    if _symbol_name_map is None:
        _symbol_name_map = {}
        try:
            symbol_file = os.path.join(get_data_dir(), 'sh_sz_stock.json')
            for item in read_json(symbol_file):
                _symbol_name_map.update(item)
        except Exception:
            # 名称文件不可用时仍可执行回测，保留 688 代码过滤。
            _symbol_name_map = {}
    return 'ST' in str(_symbol_name_map.get(symbol, '')).upper()

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

    # 公式中的“=”是通道触碰判断；使用极小容差避免浮点运算漏掉等价触碰。
    买入 = np.isclose(
        REF(下轨线A, 1), REF(趋势线, 1),
        rtol=CHANNEL_EQUAL_RTOL, atol=CHANNEL_EQUAL_ATOL,
    ) & (下轨线A < 趋势线)
    ndf['买入'] = 买入

    加仓 = np.isclose(
        REF(下轨线B, 1), REF(趋势线, 1),
        rtol=CHANNEL_EQUAL_RTOL, atol=CHANNEL_EQUAL_ATOL,
    ) & (下轨线B < 趋势线)
    ndf['加仓'] = 加仓

    强势条件 = (ndf['close'] > REF(ndf['close'], 1) * 1.03) & (MA(ndf['volume'], 5) > MA(ndf['volume'], 30))
    ndf['强势条件'] = 强势条件

    # 优化过滤器：原公式只看单日突破，容易在下降趋势、巨量长波动 K 线上追高。
    # 这些条件全部使用信号日及之前的数据，不引入未来数据；次日跳空过滤在回测入场时执行。
    close = ndf['close'].to_numpy(dtype=float)
    high = ndf['high'].to_numpy(dtype=float)
    low = ndf['low'].to_numpy(dtype=float)
    open_ = ndf['open'].to_numpy(dtype=float)
    volume = ndf['volume'].to_numpy(dtype=float)
    ma20 = MA(close, 20)
    ma60 = MA(close, 60)
    ma20_prev5 = REF(ma20, 5)
    candle_range = np.divide(
        high - low,
        close,
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(close) > 1e-12,
    )
    close_position = np.divide(
        close - low,
        high - low,
        out=np.full(len(ndf), 0.5, dtype=float),
        where=(high - low) > 1e-12,
    )
    volume_ratio = np.divide(
        volume,
        REF(volume, 1),
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(REF(volume, 1)) > 1e-12,
    )
    trend_filter = (
        (close > ma20 * (1 + MIN_PRICE_ABOVE_MA))
        & (close > ma60 * (1 + MIN_PRICE_ABOVE_MA))
        & (ma20 > ma20_prev5 * (1 + MIN_MA20_SLOPE))
    )
    candle_filter = (
        (close > open_)
        & (close_position >= MIN_CLOSE_POSITION)
        & (candle_range <= MAX_SIGNAL_RANGE)
        & (volume_ratio <= MAX_VOLUME_RATIO)
    )
    ndf['MA20'] = ma20
    ndf['MA60'] = ma60
    ndf['MA20斜率'] = np.divide(
        ma20 - ma20_prev5,
        ma20_prev5,
        out=np.full(len(ndf), np.nan, dtype=float),
        where=np.abs(ma20_prev5) > 1e-12,
    )
    ndf['信号振幅'] = candle_range
    ndf['收盘位置'] = close_position
    ndf['信号量比'] = volume_ratio
    ndf['趋势过滤'] = trend_filter
    ndf['K线过滤'] = candle_filter

    上轨线_cross = CROSS(ndf['close'].values, 上轨线)
    突破信号 = 上轨线_cross & 强势条件
    optimized_breakout = 上轨线_cross & 强势条件 & trend_filter & candle_filter
    ndf['突破信号'] = 突破信号
    ndf['突破信号优化'] = optimized_breakout

    共振买入 = 买入 & 突破信号
    ndf['共振买入'] = 共振买入

    共振加仓 = 加仓 & 突破信号
    ndf['共振加仓'] = 共振加仓

    总共振 = 共振买入 | 共振加仓
    ndf['总共振'] = 总共振

    # 保留 S29/S30 的买入/加仓结构，仅替换突破确认条件。
    ndf['共振买入优化'] = 买入 & optimized_breakout
    ndf['共振加仓优化'] = 加仓 & optimized_breakout
    ndf['总共振优化'] = ndf['共振买入优化'] | ndf['共振加仓优化']

    return ndf

def backtest_strategy(symbol, df):
    """对单只股票执行策略回测"""
    global plus_list, minus_list, total_ratio, total_hold_days, ratio_map, exit_kind_counts

    if df is None or len(df) < 100:
        return
    if _is_excluded_symbol(symbol):
        return

    ndf = calculate_indicators(df)
    last_start_index = -1

    trading_calendar.update(ndf['date'].tolist())

    signal_column = SIGNAL_COLUMN if USE_OPTIMIZED_SIGNAL else '总共振'
    if signal_column not in ndf.columns:
        signal_column = '总共振'
    buy_signals = ndf[signal_column]
    signal_indices = np.where(buy_signals.fillna(False))[0]

    for idx in signal_indices:
        # 买入日为 idx+1（第 0 天），最早只能在 idx+2 卖出，最多持有 hold_days 个交易日
        if idx + hold_days + 1 >= len(ndf):
            continue
        if last_start_index >= 0 and (idx - last_start_index) <= hold_days:
            continue

        # 信号次日开盘价买入
        entry_idx = idx + 1
        buy_price = float(ndf['open'].iloc[entry_idx])
        buy_date = ndf['date'].iloc[entry_idx]

        # 次日开盘是可执行时点，开盘跳空过大时放弃该信号，避免把突破溢价当成策略收益。
        signal_close = float(ndf['close'].iloc[idx])
        if (USE_OPTIMIZED_SIGNAL and
                (signal_close <= 0 or buy_price > signal_close * (1 + MAX_ENTRY_GAP))):
            continue

        signal_date = ndf['date'].iloc[idx]
        signal_type = []
        buy_column = '共振买入优化' if USE_OPTIMIZED_SIGNAL else '共振买入'
        add_column = '共振加仓优化' if USE_OPTIMIZED_SIGNAL else '共振加仓'
        if ndf[buy_column].iloc[idx]:
            signal_type.append("共振买入")
        if ndf[add_column].iloc[idx]:
            signal_type.append("共振加仓")

        if VERBOSE_TRADES:
            print(f"{symbol} 信号日期：{signal_date}，买入日期：{buy_date}，买入价格：{buy_price:.2f}，类型：{' + '.join(signal_type)}")

        last_start_index = idx
        max_val = -1000.0

        # 诊断用：假设一路持有到第 N 天收盘的收益（第 1 天 = 买入日的次一交易日）
        for day_offset in range(1, hold_days + 1):
            sell_idx = entry_idx + day_offset
            cur_close = float(ndf['close'].iloc[sell_idx])
            ratio = round(100 * (cur_close - buy_price) / buy_price, 2)
            ratio_map[day_offset].append(ratio)
            max_val = max(max_val, ratio)

        # 卖出规则：买入当日不卖出，从次一交易日起逐日判断
        #   开盘价 >= 止盈价 -> 以当日开盘价卖出
        #   否则收盘价 >= 止盈价 -> 以当日收盘价卖出
        #   超过持有天数限制仍未触发 -> 以最后一个交易日的收盘价卖出
        take_profit_rate = TAKE_PROFIT_RATE if USE_OPTIMIZED_SIGNAL else RAW_TAKE_PROFIT_RATE
        take_profit_price = buy_price * (1 + take_profit_rate)
        exit_idx, exit_price, exit_kind = None, None, None
        for day_offset in range(1, hold_days + 1):
            sell_idx = entry_idx + day_offset
            cur_open = float(ndf['open'].iloc[sell_idx])
            cur_close = float(ndf['close'].iloc[sell_idx])
            if cur_open >= take_profit_price:
                exit_idx, exit_price, exit_kind = sell_idx, cur_open, '开盘价'
                break
            if cur_close >= take_profit_price:
                exit_idx, exit_price, exit_kind = sell_idx, cur_close, '收盘价'
                break

        if exit_idx is None:
            exit_idx = entry_idx + hold_days
            exit_price = float(ndf['close'].iloc[exit_idx])
            exit_kind = '到期收盘价'

        realized = round(100 * (exit_price - buy_price) / buy_price, 2)
        total_ratio.append(realized)
        total_hold_days.append(exit_idx - entry_idx)
        exit_kind_counts[exit_kind] = exit_kind_counts.get(exit_kind, 0) + 1

        if realized > 0:
            plus_list.append(realized)
        else:
            minus_list.append(realized)

        # 记录逐笔明细（含持有期每日收盘价），供组合资金曲线逐日估值
        marks = {ndf['date'].iloc[d]: float(ndf['close'].iloc[d])
                 for d in range(entry_idx, exit_idx + 1)}
        trade_records.append({
            'symbol': symbol,
            'entry_date': buy_date,
            'exit_date': ndf['date'].iloc[exit_idx],
            'entry_price': buy_price,
            'exit_price': exit_price,
            'ret': realized,
            'kind': exit_kind,
            'marks': marks,
        })

        if VERBOSE_TRADES:
            print(f"  卖出日期：{ndf['date'].iloc[exit_idx]}，卖出价格：{exit_price:.2f}（{exit_kind}），"
                  f"收益：{realized:.2f}%，最大浮盈：{max_val:.2f}%")

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
    print("交易信号：{}".format(
        SIGNAL_COLUMN if USE_OPTIMIZED_SIGNAL else '总共振'))
    display_take_profit = TAKE_PROFIT_RATE if USE_OPTIMIZED_SIGNAL else RAW_TAKE_PROFIT_RATE
    print("卖出规则：信号次日开盘价买入，买入当日不卖出；从次一交易日起，"
          f"开盘价较买入价上涨至少 {display_take_profit:.0%} 时按开盘价止盈，"
          f"否则收盘价较买入价上涨至少 {display_take_profit:.0%} 时按收盘价止盈；"
          "最多持有 {} 个交易日，超过则按收盘价卖出".format(hold_days))

    total_cnt = len(plus_list) + len(minus_list)
    print("交易次数：" + str(total_cnt))
    print("正收益次数：" + str(len(plus_list)))
    if total_cnt > 0:
        print("正收益占比：" + str(round(100 * len(plus_list) / total_cnt, 2)) + "%")
        print("平均收益：" + str(round(sum(total_ratio) / total_cnt, 2)) + "%")

    total = sum(plus_list)
    print("总的正收益：" + str(round(total, 2)))

    total = sum(minus_list)
    print("总的负收益：" + str(round(total, 2)))

    if exit_kind_counts and total_cnt > 0:
        print("\n卖出方式分布：")
        for kind, cnt in sorted(exit_kind_counts.items(), key=lambda kv: -kv[1]):
            print("    {}：{} 笔（{:.1f}%）".format(kind, cnt, 100.0 * cnt / total_cnt))

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


# ============================================================
# 组合资金曲线：等权、逐日结算
# ============================================================

def simulate_portfolio(records=None, position_size=POSITION_SIZE, fee_rate=FEE_RATE,
                       init_capital=INIT_CAPITAL, save_path=None):
    """
    把逐笔交易合成为一条组合资金曲线。

    口径：
      - 每笔交易在买入日开盘建仓，仓位 = 当日组合权益 * position_size，现金不足时按可用现金缩减；
      - 持有期内每个交易日按收盘价对持仓估值（逐日结算）；
      - 卖出日按实际卖出价（开盘价 / 收盘价）结算，并扣减手续费；
      - 闲置资金不计收益，不考虑融资融券，不做再平衡。
    """
    records = trade_records if records is None else records
    if not records:
        print("\n没有交易记录，无法生成资金曲线")
        return None

    # 逐日结算要覆盖区间内的每一个交易日，空白日（无持仓）也要计入，
    # 否则年化收益和夏普会因为交易日数被低估而失真
    if trading_calendar:
        lo = min(r['entry_date'] for r in records)
        hi = max(r['exit_date'] for r in records)
        days = sorted(d for d in trading_calendar if lo <= d <= hi)
    else:
        days = sorted({d for r in records for d in r['marks']})
    new_trades = {}
    for r in records:
        new_trades.setdefault(r['entry_date'], []).append(r)

    cash = float(init_capital)
    open_positions = []
    curve = []
    skipped, reduced = 0, 0
    invested_sum = 0.0

    for day in days:
        # 1) 今日到期的持仓，按实际卖出价结算
        keep = []
        for pos in open_positions:
            if pos['rec']['exit_date'] == day:
                cash += pos['shares'] * pos['rec']['exit_price'] * (1 - fee_rate)
            else:
                keep.append(pos)
        open_positions = keep

        # 2) 今日新建仓位：等权（占当日权益固定比例），资金不足则缩减或跳过
        for rec in new_trades.get(day, []):
            equity_now = cash + sum(p['shares'] * p['last_close'] for p in open_positions)
            alloc = equity_now * position_size
            if alloc <= 0 or cash <= 1e-9:
                skipped += 1
                continue
            if cash < alloc:
                alloc = cash
                reduced += 1
            shares = alloc / rec['entry_price'] / (1 + fee_rate)
            cash -= shares * rec['entry_price'] * (1 + fee_rate)
            open_positions.append({'rec': rec, 'shares': shares,
                                   'last_close': rec['entry_price']})

        # 3) 收盘估值
        market_value = 0.0
        for pos in open_positions:
            close = pos['rec']['marks'].get(day)
            if close is not None:
                pos['last_close'] = close
            market_value += pos['shares'] * pos['last_close']

        equity = cash + market_value
        curve.append({'date': day, 'equity': equity, 'cash': cash,
                      'market_value': market_value, 'positions': len(open_positions)})
        if equity > 0:
            invested_sum += market_value / equity

    # ---- 统计 ----
    eq = np.array([c['equity'] for c in curve], dtype=float)
    n = len(eq)
    total_ret = eq[-1] / init_capital - 1
    with np.errstate(divide='ignore', invalid='ignore'):
        daily = np.diff(eq) / eq[:-1] if n > 1 else np.array([])
    daily = daily[np.isfinite(daily)]
    years = n / 252.0
    annual = (eq[-1] / init_capital) ** (1 / years) - 1 if years > 0 and eq[-1] > 0 else float('nan')
    max_dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) and daily.std() > 0 else float('nan')
    max_pos = max(c['positions'] for c in curve)

    print("\n" + "=" * 80)
    print("组合资金曲线（等权、逐日结算）")
    print("=" * 80)
    print("初始资金：{:.0f}    单笔仓位：入场时权益的 {:.1%}    单边手续费：{:.4%}".format(
        init_capital, position_size, fee_rate))
    print("回测区间：{} ~ {}（{} 个交易日）".format(curve[0]['date'], curve[-1]['date'], n))
    print("期末权益：{:.2f}".format(eq[-1]))
    print("组合总收益：{:.2f}%".format(total_ret * 100))
    print("年化收益：{:.2f}%".format(annual * 100))
    print("最大回撤：{:.2f}%".format(max_dd * 100))
    print("日收益夏普：{:.2f}".format(sharpe))
    print("最大同时持仓：{} 笔    平均资金占用：{:.1f}%".format(max_pos, invested_sum / n * 100))
    if reduced:
        print("因现金不足被缩减仓位的交易：{} 笔".format(reduced))
    if skipped:
        print("因现金不足被跳过的交易：{} 笔".format(skipped))

    if save_path:
        pd.DataFrame(curve).to_csv(save_path, index=False, encoding='utf-8-sig')
        print("资金曲线已保存到 {}".format(save_path))

    return curve

def main():
    print("=" * 80)
    print("趋势通道共振策略 (Trend Channel Resonance Strategy)")
    print("=" * 80)
    print("策略条件：")
    print("1. 买入信号：下轨线A(或下轨线B)触到趋势线后趋势线向上")
    print("2. 突破信号：收盘价上穿上轨线且强势条件成立")
    print("3. 强势条件：涨幅>3%且5日均量>30日均量")
    if USE_OPTIMIZED_SIGNAL:
        print("4. 优化过滤：收盘高于MA20/MA60至少2%，MA20五日抬升至少0.5%")
        print("5. 优化过滤：阳线、收盘位于振幅中点上方、振幅<=8%、量比<=3")
        print("6. 次日跳空超过3%时放弃入场")
    else:
        print("4. 使用原始总共振信号（不启用优化过滤）")
    print("=" * 80)

    all_symbols = get_daily_symbols()
    print(f"共 {len(all_symbols)} 只股票待筛选")

    for idx, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{idx + 1} / {len(all_symbols)}")
        try:
            df = get_local_stock_data(symbol, BACKTEST_START_DATE)
            if df is None or len(df) < 100:
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

    # 组合资金曲线（等权、逐日结算）
    simulate_portfolio(save_path=os.path.join(get_data_dir(), 'trend_channel_equity.csv'))

if __name__ == '__main__':
    main()

'''
================================================================================
趋势通道共振策略统计结果
================================================================================
正收益次数：2006
正收益占比：73.4%
总的正收益：11081.03
总的负收益：-1293.92

总体收益统计：
总收益：
    平均值：3.58
    最大值：60.98
    最小值：-11.86
    50% 的百分位数：2.09
    95% 的百分位数：14.99

正收益统计：
正收益：
    平均值：5.52
    最大值：60.98
    最小值：0.02
    50% 的百分位数：3.60
    95% 的百分位数：17.43

负收益统计：
负收益：
    平均值：-1.78
    最大值：0.00
    最小值：-11.86
    50% 的百分位数：-1.26
    95% 的百分位数：0.00

================================================================================
按天统计收益
================================================================================

第 1 天：
    正收益次数：1353
    正收益占比：49.51%
    总的正收益：3207.01
    总的负收益：-2636.84
    第 1 天收益统计：
    平均值：0.21
    最大值：19.07
    最小值：-11.86
    50% 的百分位数：0.00
    95% 的百分位数：5.45

第 2 天：
    正收益次数：1358
    正收益占比：49.69%
    总的正收益：4561.19
    总的负收益：-3851.39
    第 2 天收益统计：
    平均值：0.26
    最大值：28.06
    最小值：-18.65
    50% 的百分位数：0.00
    95% 的百分位数：7.77

第 3 天：
    正收益次数：1367
    正收益占比：50.02%
    总的正收益：5739.74
    总的负收益：-4698.55
    第 3 天收益统计：
    平均值：0.38
    最大值：41.01
    最小值：-19.26
    50% 的百分位数：0.02
    95% 的百分位数：9.58

第 4 天：
    正收益次数：1350
    正收益占比：49.4%
    总的正收益：6869.62
    总的负收益：-5390.87
    第 4 天收益统计：
    平均值：0.54
    最大值：46.42
    最小值：-19.68
    50% 的百分位数：0.00
    95% 的百分位数：11.43

第 5 天：
    正收益次数：1369
    正收益占比：50.09%
    总的正收益：7654.41
    总的负收益：-5913.56
    第 5 天收益统计：
    平均值：0.64
    最大值：60.98
    最小值：-25.02
    50% 的百分位数：0.05
    95% 的百分位数：12.34

总收益率：
    平均值：2.11
    最大值：19.07
    最小值：-15.42
    50% 的百分位数：1.46
    95% 的百分位数：7.15
总持有天数：
    平均值：21.47
    最大值：1049.00
    最小值：1.00
    50% 的百分位数：2.00
    95% 的百分位数：101.00
'''
