# coding: utf-8
"""
季度散户化评分策略回测

RULES:
  1. 股票代码以688开头 → 排除
  2. 绝对阈值过滤: 股东人数>5万 OR 户均<10万 OR 股东人数环比>20% → 排除
  3. 分层阈值过滤:
       市值<50亿:  股东人数>4万 OR 户均<8万 → 排除
       50亿-200亿: 股东人数>8万 OR 户均<15万 → 排除
       市值>200亿:  股东人数>15万 OR 户均<30万 → 排除
  4. 综合评分过滤: 散户化评分<0.5 → 排除

买入时机:
  1. 03-31数据 → 5月第一个交易日买入, 7月第一个交易日卖出
  2. 06-30数据 → 9月第一个交易日买入, 10月第一个交易日卖出
  3. 09-30数据 → 11月第一个交易日买入, 下年1月第一个交易日卖出
"""
import os
import pandas as pd
import numpy as np
from datetime import datetime
from czsc_daily_util import get_daily_symbols, get_data_dir, write_json, czsc_logger
from czsc_sqlite import get_local_stock_data

CACHE_DIR = os.path.join(get_data_dir(), '.cache')
QUARTER_HOLDER_CACHE = os.path.join(CACHE_DIR, 'quarter_holder')


def _ensure_cache_dir():
    os.makedirs(QUARTER_HOLDER_CACHE, exist_ok=True)


def _get_holder_data(holder_date_str):
    _ensure_cache_dir()
    cache_file = os.path.join(QUARTER_HOLDER_CACHE, f'{holder_date_str}.csv')
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file)

    import akshare as ak
    try:
        df = ak.stock_zh_a_gdhs(symbol=holder_date_str)
        df.to_csv(cache_file, index=False)
        return df
    except Exception as e:
        czsc_logger().error(f"获取 {holder_date_str} 股东数据失败: {e}")
        return None


def _get_holder_dates():
    """生成季度末日期: 只保留 03-31, 06-30, 09-30（排除12-31）"""
    current_year = datetime.now().year
    current_month = datetime.now().month
    dates = []
    for y in range(2020, current_year + 1):
        for m in [3, 6, 9]:
            if y == current_year and m > current_month:
                continue
            day = 31 if m in [3] else 30
            dates.append(f"{y}{m:02d}{day}")
    return dates


def _holder_to_trade_months(holder_date_str):
    """根据股东数据日期返回(买入年,买入月,卖出年,卖出月)"""
    y = int(holder_date_str[:4])
    m = int(holder_date_str[4:6])
    if m == 3:
        return y, 5, y, 7
    elif m == 6:
        return y, 9, y, 10
    elif m == 9:
        return y + 1, 1, None, None  # sell is not directly the next trade
    return None, None, None, None


def _get_first_trade_day(df, year, month, day=1):
    target = f"{year}-{month:02d}-{day:02d}"
    mask = df['date'] >= target
    idx = mask.idxmax() if mask.any() else None
    return idx


def _filter_rule1(holder_df):
    """规则1: 排除688开头"""
    return holder_df[~holder_df['代码'].astype(str).str.startswith('688')]


def _filter_rule2(holder_df):
    """规则2: 绝对阈值过滤"""
    df = holder_df.copy()
    cond = (
        (df['股东户数-本次'] > 50000) |
        (df['户均持股市值'] < 100000) |
        (df['股东户数-增减比例'] > 20)
    )
    return df[~cond]


def _filter_rule3(holder_df):
    """规则3: 分层阈值过滤"""
    df = holder_df.copy()
    cap = df['总市值']
    holders = df['股东户数-本次']
    avg = df['户均持股市值']

    cond_small = (cap < 5e9) & ((holders > 40000) | (avg < 80000))
    cond_mid = (cap >= 5e9) & (cap <= 2e10) & ((holders > 80000) | (avg < 150000))
    cond_large = (cap > 2e10) & ((holders > 150000) | (avg < 300000))

    return df[~(cond_small | cond_mid | cond_large)]


def _calc_score(holder_df):
    """计算散户化评分并过滤<0.5的股票"""
    df = holder_df.copy()

    max_holders = df['股东户数-本次'].max()
    max_avg = df['户均持股市值'].max()

    df['持股集中度'] = df['股东户数-本次'] / max_holders if max_holders > 0 else 0
    df['户均浓度'] = 1 - (df['户均持股市值'] / max_avg) if max_avg > 0 else 1
    df['变化趋势'] = df['股东户数-增减比例'].clip(0, 100) / 100
    df['散户化评分'] = 0.3 * df['持股集中度'] + 0.4 * df['户均浓度'] + 0.3 * df['变化趋势']
    return df


def backtest():
    _ensure_cache_dir()
    all_symbols = get_daily_symbols()
    if not all_symbols:
        czsc_logger().error("没有股票数据，请先运行 update_daily_symbols()")
        return

    holder_dates = _get_holder_dates()
    czsc_logger().info(f"共 {len(holder_dates)} 个季度数据需要处理")

    all_records = []
    stock_cache = {}

    def _get_df(symbol):
        if symbol not in stock_cache:
            try:
                stock_cache[symbol] = get_local_stock_data(symbol, start_date='2019-01-01')
            except Exception:
                stock_cache[symbol] = None
        return stock_cache[symbol]

    for qi, holder_date_str in enumerate(holder_dates):
        czsc_logger().info(f"\n[{qi + 1}/{len(holder_dates)}] 处理: {holder_date_str}")

        buy_y, buy_m, sell_y, sell_m = _holder_to_trade_months(holder_date_str)
        if buy_y is None:
            czsc_logger().info(f"  跳过(无对应交易月份)")
            continue

        holder_df = _get_holder_data(holder_date_str)
        if holder_df is None or holder_df.empty:
            continue

        # 应用规则1-3
        df = _filter_rule1(holder_df)
        df = _filter_rule2(df)
        df = _filter_rule3(df)

        if df.empty:
            czsc_logger().info(f"  规则1-3后无剩余股票")
            continue

        # 规则4: 评分过滤
        df = _calc_score(df)
        df = df[df['散户化评分'] >= 0.5]

        if df.empty:
            czsc_logger().info(f"  规则4后无剩余股票")
            continue

        # 按评分升序取前10
        top10 = df.nsmallest(10, '散户化评分')
        czsc_logger().info(f"  入选: {top10['名称'].tolist()}")
        czsc_logger().info(f"  评分: {[round(s, 3) for s in top10['散户化评分'].tolist()]}")

        # 如果卖出月份没确定（09-30数据卖出在下年1月）
        if sell_y is None or sell_m is None:
            sell_y = buy_y + 1
            sell_m = 1

        current_year = datetime.now().year
        current_month = datetime.now().month
        if sell_y > current_year or (sell_y == current_year and sell_m > current_month):
            czsc_logger().info(f"  卖出月份 {sell_y}-{sell_m:02d} 尚未到来，跳过")
            continue

        for _, row in top10.iterrows():
            raw_code = str(row['代码'])
            name = row['名称']

            symbol = None
            for code in all_symbols:
                if code.endswith(raw_code):
                    symbol = code
                    break
            if symbol is None:
                continue

            df_stock = _get_df(symbol)
            if df_stock is None or len(df_stock) < 10:
                continue

            buy_idx = _get_first_trade_day(df_stock, buy_y, buy_m)
            sell_idx = _get_first_trade_day(df_stock, sell_y, sell_m)
            if buy_idx is None or sell_idx is None or sell_idx <= buy_idx:
                continue

            buy_price = float(df_stock['open'].iloc[buy_idx])
            sell_price = float(df_stock['open'].iloc[sell_idx])
            ret = round(100 * (sell_price - buy_price) / (buy_price + 1e-10), 2)
            buy_date = df_stock['date'].iloc[buy_idx]
            sell_date = df_stock['date'].iloc[sell_idx]

            all_records.append({
                'holder_date': holder_date_str,
                'symbol': symbol,
                'name': name,
                '散户化评分': round(row['散户化评分'], 4),
                '股东人数': int(row['股东户数-本次']),
                '户均持股市值': round(row['户均持股市值'], 2),
                '股东人数增减比例': round(row['股东户数-增减比例'], 2),
                '总市值': round(row['总市值'], 2),
                'buy_date': buy_date,
                'sell_date': sell_date,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'return': ret,
            })

    _print_results(all_records)
    return all_records


def _print_results(records):
    print("\n" + "=" * 70)
    print("  季度散户化评分策略 — 统计结果")
    print("=" * 70)
    if not records:
        print("  无交易记录")
        return

    df = pd.DataFrame(records)
    print(f"\n  总交易次数：{len(df)}")
    print(f"  涉及季度数：{df['holder_date'].nunique()}")
    print(f"  涉及股票数：{df['symbol'].nunique()}")

    returns = df['return'].values
    plus = returns[returns > 0]
    minus = returns[returns <= 0]
    print(f"\n  正收益次数：{len(plus)}  负收益次数：{len(minus)}")
    print(f"  胜率：{100 * len(plus) / len(returns):.2f}%")
    print(f"  平均收益：{np.mean(returns):.2f}%")
    print(f"  中位数收益：{np.median(returns):.2f}%")
    print(f"  最大收益：{np.max(returns):.2f}%  最小收益：{np.min(returns):.2f}%")
    print(f"  标准差：{np.std(returns):.2f}%")
    if len(plus) > 0:
        print(f"\n  正收益统计：平均 {np.mean(plus):.2f}%  最大 {np.max(plus):.2f}%  最小 {np.min(plus):.2f}%")
    if len(minus) > 0:
        print(f"  负收益统计：平均 {np.mean(minus):.2f}%  最大 {np.max(minus):.2f}%  最小 {np.min(minus):.2f}%")

    q_stats = df.groupby('holder_date').agg(
        数量=('symbol', 'count'),
        平均收益=('return', 'mean'),
        最大收益=('return', 'max'),
        最小收益=('return', 'min'),
        胜率=('return', lambda x: round(100 * np.sum(x > 0) / len(x), 1)),
    ).round(2)
    print(f"\n  --- 按季度统计 ---")
    print(q_stats.to_string())

    result_file = os.path.join(get_data_dir(), 'quarter_score_top10_backtest.csv')
    df.to_csv(result_file, index=False, encoding='utf-8-sig')
    print(f"\n  明细已保存至: {result_file}")


if __name__ == "__main__":
    records = backtest()
