# coding: utf-8
"""
回踩五日均线 一夜持股策略 - 回测版本（含大盘过滤）

策略描述：
  1) 连续三天上涨，且三天的最低价、最高价依次抬高
  2) 第4天盘中回踩5日线时买入（挂限价单）
  3) 买入后第二天卖出（支持多种卖出规则）
  4) 增加大盘环境过滤：只在指数站上20日均线时出手

数据：全部A股，日线缓存覆盖 2024-01-01 ~ 2026-09-04
"""
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

project_root = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(project_root, 'data')
CACHE_DIR = os.path.join(data_dir, '.cache')
from czsc_daily_util import (
    get_data_dir,
    get_symbols_name,
    get_stock_pd_tdx,
    get_latest_trade_date,
    read_json,
    write_json,
    czsc_logger,
)

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------
PARAMS = dict(
    up_days=3,                # 连续上涨天数
    require_dip_day=True,     # 第4天为回调日
    dip_max=0.01,             # 容忍开盘微涨1%
    touch_ratio=0.02,         # 回踩5日线允许偏离2%
    buy_mode='ma5',           # 买入价=买入当天实时5日均线（价格<=实时5日线时买入）
    
    # ===== 新增：大盘过滤参数 =====
    use_market_filter=True,   # 是否启用大盘过滤
    market_index='000001',    # 上证指数
    market_ma_period=20,      # 大盘均线周期
    market_min_ma5=False,     # 是否要求大盘也在5日线上方
    
    start_date='2024-01-01',
    end_date='2099-12-31',
    cache_start='2024-01-01',
    cache_end='2026-09-04',
)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_stock_df(symbol):
    fp = os.path.join(CACHE_DIR, f'{symbol}_{PARAMS["cache_start"]}_{PARAMS["cache_end"]}.csv')
    if not os.path.isfile(fp):
        return None
    df = pd.read_csv(fp)
    df = df.dropna(subset=['close', 'open', 'high', 'low'])
    df['date'] = pd.to_datetime(df['date'])
    df.sort_values('date', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def get_symbols():
    with open(os.path.join(data_dir, 'sh_sz_stock.json'), encoding='utf-8') as f:
        data = json.load(f)
    result = {}
    for item in data:
        for code, name in item.items():
            result[code] = name
    return result


# ===== NEW: 加载大盘指数数据 =====
def load_market_data():
    """从缓存加载上证指数日线数据"""
    # 上证指数代码通常是 000001
    idx_df = get_stock_pd_tdx('sh.000001', PARAMS["cache_start"], PARAMS["cache_end"], 'd', True)
    fp = os.path.join(CACHE_DIR, f'sh.000001_{PARAMS["cache_start"]}_{PARAMS["cache_end"]}.csv')
    if not os.path.isfile(fp):
        print('⚠️ 警告: 未找到大盘指数缓存文件，跳过市场过滤')
        return None
    df = pd.read_csv(fp)
    df = df.dropna(subset=['close'])
    df['date'] = pd.to_datetime(df['date'])
    df.sort_values('date', inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    # 计算大盘均线
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma20'] = df['close'].rolling(PARAMS['market_ma_period']).mean()
    df['ma5_prev'] = df['ma5'].shift(1)
    df['ma20_prev'] = df['ma20'].shift(1)
    
    return df


# ===== NEW: 检查大盘条件 =====
def check_market_condition(market_df, date_str):
    """
    检查指定日期的大盘环境是否符合买入条件
    返回: (bool, str) 是否符合条件及原因
    """
    if market_df is None:
        return True, '无大盘数据，跳过过滤'
    
    # 查找该日期的数据
    date_dt = pd.to_datetime(date_str)
    row = market_df[market_df['date'] == date_dt]
    if row.empty:
        # 尝试找前一个交易日
        market_df['date_diff'] = (market_df['date'] - date_dt).dt.days
        market_df['date_diff_abs'] = market_df['date_diff'].abs()
        closest = market_df.loc[market_df['date_diff_abs'].idxmin()]
        if closest['date_diff'] > 5:  # 超过5天没数据，跳过
            return True, f'无匹配日期，使用最接近数据: {closest["date"].strftime("%Y-%m-%d")}'
        row = pd.DataFrame([closest])
    
    row = row.iloc[0]
    close = row['close']
    ma20_prev = row['ma20_prev']
    ma5_prev = row['ma5_prev']
    
    # 条件1：收盘价 > 20日均线（指数在20日线上方）
    if close <= ma20_prev:
        return False, f'大盘收盘{close:.2f} <= MA20({ma20_prev:.2f})'
    
    # 条件2（可选）：大盘是否也在5日线上方
    if PARAMS.get('market_min_ma5', False):
        if close <= ma5_prev:
            return False, f'大盘收盘{close:.2f} <= MA5({ma5_prev:.2f})'
    
    return True, f'大盘收盘{close:.2f} > MA20({ma20_prev:.2f}) ✅'


# ---------------------------------------------------------------------------
# 信号计算
# ---------------------------------------------------------------------------
def compute_signals(symbol, name, df, market_df=None):
    n = len(df)
    if n < 20:
        return None

    close = df['close'].to_numpy(dtype=float)
    open_ = df['open'].to_numpy(dtype=float)
    high = df['high'].to_numpy(dtype=float)
    low = df['low'].to_numpy(dtype=float)

    up = PARAMS['up_days']
    dip_max = PARAMS['dip_max']
    require_dip = PARAMS['require_dip_day']

    # 条件：当日收盘价 > 60日均线（中期趋势向上）
    ma60_prev = np.full(n, np.nan)
    for i in range(60, n):
        ma60_prev[i] = np.mean(close[i-60:i])

    cond = np.zeros(n, dtype=bool)
    buy_px_arr = np.full(n, np.nan)     # 每笔信号的实际买入价
    ma5_rt_arr = np.full(n, np.nan)     # 买入当天“实时”5日均线的买入参考价
    cond_reasons = []  # 记录每个信号的大盘原因
    
    for i in range(up + 5, n):

        # 1) 连续 up_days 天上涨
        ok_up = True
        for j in range(up):
            if not (close[i - up + j] > close[i - up + j - 1]):
                ok_up = False
                break
        if not ok_up:
            continue

        # 连续三天上涨时，成交量是否逐步放大？
        volume = df['volume'].to_numpy(dtype=float)
        ok_volume = all(volume[i - up + j] > volume[i - up + j - 1] for j in range(1, up))

        # 2) 三天最低点、最高点依次抬高
        ok_low = all(low[i - up + j] > low[i - up + j - 1] for j in range(1, up))
        ok_high = all(high[i - up + j] > high[i - up + j - 1] for j in range(1, up))
        if not (ok_low and ok_high and ok_volume):
            continue

        # 3) 第4天为回调日：开盘价不高于前日收盘（容忍微涨）
        if require_dip and open_[i] > close[i - 1] * (1 + dip_max):
            continue

        # 4) 盘中回踩买入：买入当天实时计算的5日均线
        #    实时5日均线 = (前4日收盘之和 + 当日实时价) / 5
        #    当 价格 <= 实时5日均线 时买入，此时买入价即实时5日均线价
        #    即价格 p 满足: p <= (sum4 + p)/5  =>  p <= sum4/4
        sum4 = close[i-4] + close[i-3] + close[i-2] + close[i-1]
        rt_level = sum4 / 4.0   # 当天实时5日均线的买入参考价
        rt_level = (sum4+open_[i]) / 5.0   # 当天实时5日均线的买入参考价
        entry_px = min(open_[i], rt_level)  # 开盘已跌破实时5日线按开盘价，否则按5日线价
        if min(open_[i], low[i]) > rt_level:
            continue  # 当日价格始终高于实时5日均线，未回踩，放弃
        # 在循环中加入：
        if close[i] < ma60_prev[i]:
            continue  # 股价在60日线下方，说明中期趋势向下，放弃

        # ===== NEW: 5) 大盘环境过滤 =====
        if PARAMS.get('use_market_filter', False) and market_df is not None:
            date_str = df['date'].iloc[i].strftime('%Y-%m-%d')
            is_good, reason = check_market_condition(market_df, date_str)
            if not is_good:
                continue
        else:
            reason = '未启用大盘过滤'

        cond[i] = True
        buy_px_arr[i] = entry_px
        ma5_rt_arr[i] = rt_level
        cond_reasons.append(reason)

    idx = np.where(cond)[0]
    if len(idx) == 0:
        return None

    buy_price = buy_px_arr[idx]
    buy_date = df['date'].iloc[idx].dt.strftime('%Y-%m-%d').values

    next_high = np.full(n, np.nan)
    next_open = np.full(n, np.nan)
    next_close = np.full(n, np.nan)
    next_high[:-1] = high[1:]
    next_open[:-1] = open_[1:]
    next_close[:-1] = close[1:]

    # 次日（买入后第1个交易日）的日期，作为次日卖出时间
    next_date = np.full(n, None, dtype=object)
    next_date[:-1] = df['date'].iloc[1:].dt.strftime('%Y-%m-%d').values

    # 第3天（买入后第2个交易日）最高价：次日未卖出、再持一天的卖出价
    next2_high = np.full(n, np.nan)
    next2_high[:-2] = high[2:]

    # 第3天的日期，作为第3天最高价卖的卖出时间
    next2_date = np.full(n, None, dtype=object)
    next2_date[:-2] = df['date'].iloc[2:].dt.strftime('%Y-%m-%d').values

    out = pd.DataFrame({
        'date': buy_date,
        'buy_date': buy_date,
        'symbol': symbol,
        'name': name,
        'open': open_[idx],
        'low': low[idx],
        'rt_ma5': ma5_rt_arr[idx],      # 当天实时5日均线买入参考价
        'close': close[idx],
        'buy_price': buy_price,
        'next_high': next_high[idx],
        'next_open': next_open[idx],
        'next_close': next_close[idx],
        'next2_high': next2_high[idx],
        'buy_time': buy_date,          # 买入时间（信号日，按MA5成交）
        'sell_time_next': next_date[idx],   # 次日卖出时间
        'sell_time_next2': next2_date[idx],  # 第3天卖出时间
        'sell_price_open': next_open[idx],   # 次日开盘卖出价
        'sell_price_high': next_high[idx],   # 次日最高价卖出价
        'sell_price_close': next_close[idx], # 次日收盘卖出价
        'sell_price_next2': next2_high[idx], # 第3天最高价卖出价
        'same_day_ret': close[idx] / buy_price - 1.0,  # 当天买入(5日线)至收盘收益率
        'market_reason': cond_reasons,  # 记录大盘原因
    })
    return out


# ---------------------------------------------------------------------------
# 回测与统计
# ---------------------------------------------------------------------------
def run_backtest():
    symbols = get_symbols()
    print(f'股票总数: {len(symbols)}')

    # ===== NEW: 加载大盘数据 =====
    market_df = None
    if PARAMS.get('use_market_filter', False):
        market_df = load_market_data()
        if market_df is not None:
            print(f'✅ 大盘数据加载成功，范围: {market_df["date"].min()} ~ {market_df["date"].max()}')
        else:
            print('⚠️ 大盘数据加载失败，将跳过市场过滤')

    all_signals = []
    total = len(symbols)
    for i, (symbol, name) in enumerate(symbols.items()):
        if (i + 1) % 500 == 0:
            print(f'  进度: {i + 1}/{total} {datetime.now().strftime("%H:%M:%S")}')
        try:
            df = load_stock_df(symbol)
            if df is None:
                continue
            out = compute_signals(symbol, name, df, market_df)
            if out is not None and len(out):
                all_signals.append(out)
        except Exception as e:
            print(f'  处理 {symbol} 出错: {e}')
            continue

    if not all_signals:
        print('无任何信号')
        return

    sig = pd.concat(all_signals, ignore_index=True)
    sd = pd.to_datetime(PARAMS['start_date']).strftime('%Y-%m-%d')
    sig = sig[(sig['date'] >= sd) & (sig['date'] <= PARAMS['end_date'])]
    sig = sig.dropna(subset=['next_high'])

    fee = 0.001
    sig['ret_high'] = (sig['next_high'] / sig['buy_price'] - 1.0) * 100.0 - fee * 100
    sig['ret_open'] = (sig['next_open'] / sig['buy_price'] - 1.0) * 100.0 - fee * 100
    sig['ret_close'] = (sig['next_close'] / sig['buy_price'] - 1.0) * 100.0 - fee * 100
    sig = sig.dropna(subset=['ret_high', 'ret_open', 'ret_close'])

    # ===== 卖出信息：各卖出规则对应的盈利比率 =====
    sig['profit_ratio_open'] = sig['ret_open']     # 次日开盘卖 盈利率%
    sig['profit_ratio_high'] = sig['ret_high']     # 次日最高卖 盈利率%
    sig['profit_ratio_close'] = sig['ret_close']   # 次日收盘卖 盈利率%

    # ===== NEW: 统计大盘过滤效果 =====
    if 'market_reason' in sig.columns:
        filtered_cnt = sig['market_reason'].str.contains('✅').sum()
        total_cnt = len(sig)
        print(f'\n📊 大盘过滤统计: {filtered_cnt}/{total_cnt} 笔信号在大盘强势时产生')

    print(f'\n信号总笔数: {len(sig)}')
    print_stats(sig)
    print_sell_log(sig)
    save_results(sig)


def print_stats(tdf):
    print('\n' + '=' * 78)
    print(f'回踩5日线 一夜持股策略 回测统计（买入口径: {PARAMS["buy_mode"]}）')
    print(f'大盘过滤: {"启用" if PARAMS.get("use_market_filter", False) else "禁用"}')
    print('=' * 78)
    print(f'  交易笔数: {len(tdf)}')
    if len(tdf) == 0:
        return

    for label, col in [('次日最高价卖', 'ret_high'), ('次日开盘卖', 'ret_open'), ('次日收盘卖', 'ret_close')]:
        r = tdf[col].dropna()
        if len(r) == 0:
            continue
        wins = (r > 0).sum()
        wr = wins / len(r) * 100
        avg = r.mean()
        med = r.median()
        print(f'\n  【{label}】(含手续费0.1%)')
        print(f'    胜率: {wr:.2f}% ({wins}/{len(r)}) | 平均: {avg:+.2f}% | 中位数: {med:+.2f}% | 最大: {r.max():+.2f}% | 最小: {r.min():+.2f}%')

        streak_w, streak_l, best_w, best_l = 0, 0, 0, 0
        for x in r.values:
            if x > 0:
                streak_w += 1
                streak_l = 0
            else:
                streak_l += 1
                streak_w = 0
            best_w = max(best_w, streak_w)
            best_l = max(best_l, streak_l)
        print(f'    最大连胜: {best_w} 次 | 最大连亏: {best_l} 次')

        sub = tdf[['date', col]].copy()
        sub['month'] = sub['date'].str[:7]
        mon = sub.groupby('month')[col].agg(['count', 'mean', lambda s: (s > 0).sum()])
        mon.columns = ['count', 'avg', 'wins']
        mon['win_rate'] = (mon['wins'] / mon['count'] * 100).round(1)
        mon['avg'] = mon['avg'].round(2)
        print(f'\n  月份明细({label}):')
        for m, row in mon.iterrows():
            print(f'    {m}  次数={int(row["count"]):>4}  胜率={row["win_rate"]:>6.1f}%  平均={row["avg"]:>+6.2f}%')

    print('\n  最近15笔(次日开盘卖):')
    sub = tdf[['symbol', 'name', 'buy_time', 'sell_time_next',
               'buy_price', 'sell_price_open', 'ret_open']].dropna(subset=['ret_open']).tail(15)
    print(sub.to_string(index=False))


def print_sell_log(tdf):
    """逐笔打印卖出日志：股票代码、买入时间、卖出时间、买入价格、卖出价格、盈利比率"""
    print('\n' + '=' * 78)
    print('  逐笔卖出日志（卖出规则: 次日开盘卖）')
    print('=' * 78)
    if len(tdf) == 0:
        print('  无交易')
        return
    for _, row in tdf.iterrows():
        sell_closed = pd.notna(row.get('next_open'))
        if not sell_closed:
            continue
        pnl = row.get('profit_ratio_high', np.nan)
        win_flag = '✅' if pd.notna(pnl) and pnl > 0 else ('❌' if pd.notna(pnl) else '  ')
        print(f'  {win_flag} {row["symbol"]} {row.get("name", "")} '
              f'买入时间={row["buy_time"]} 卖出时间={row["sell_time_next"]} '
              f'买入价={row["buy_price"]:.3f} 卖出价(开盘)={row["sell_price_high"]:.3f} '
              f'盈利率={pnl:+.2f}%' if pd.notna(pnl) else
              f'  {row["symbol"]} {row.get("name", "")} '
              f'买入时间={row["buy_time"]} 卖出时间={row["sell_time_next"]} '
              f'买入价={row["buy_price"]:.3f} 卖出价(开盘)={row["sell_price_high"]:.3f} '
              f'盈利率=n/a')
    print('=' * 78)


def save_results(tdf):
    fp = os.path.join(data_dir, 'ma5_pullback_trades.csv')
    tdf.sort_values('date').to_csv(fp, index=False, encoding='utf-8-sig')
    print(f'\n交易明细已保存: {fp}')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib as mpl
        mpl.rcParams['font.sans-serif'] = ['PingFang SC', 'Arial Unicode MS', 'SimHei']
        mpl.rcParams['axes.unicode_minus'] = False
        sub = tdf[['date', 'ret_high', 'ret_open', 'ret_close']].dropna(subset=['ret_high']).sort_values('date').copy()
        sub['cum_high'] = ((sub['ret_high'] / 100.0 + 1)).cumprod()
        sub['cum_open'] = ((sub['ret_open'] / 100.0 + 1)).cumprod()
        sub['cum_close'] = ((sub['ret_close'] / 100.0 + 1)).cumprod()
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(sub['date'], sub['cum_high'], label='次日最高价卖')
        ax.plot(sub['date'], sub['cum_open'], label='次日开盘卖')
        ax.plot(sub['date'], sub['cum_close'], label='次日收盘卖')
        ax.axhline(1.0, color='gray', ls='--', lw=0.8)
        ax.set_title(f'回踩5日线一夜持股 | 交易{len(sub)}笔 | 次日最高卖胜率{(sub["ret_high"] > 0).mean() * 100:.1f}%')
        ax.set_ylabel('累计净值（1元起）')
        ax.legend()
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        out = os.path.join(data_dir, 'ma5_pullback_backtest.png')
        fig.savefig(out, dpi=110, bbox_inches='tight')
        plt.close(fig)
        print(f'收益曲线已保存: {out}')
    except Exception as e:
        print(f'绘图失败: {e}')


if __name__ == '__main__':
    run_backtest()