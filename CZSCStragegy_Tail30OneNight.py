# coding: utf-8
"""
尾盘30分钟 一夜持股策略 - 回测版本
来源：{尾30个股-尾盘30分 全部A股收盘价 1日卖 胜率100.00%_金锅高胜率版20260602}

策略规则（每日 14:30 强中选强，买进后持1日卖出）：
   1) 涨幅 3% - 5%
   2) 换手率 5% - 10%
   3) 量比 1 - 5
   4) 流通市值 50 - 200 亿
   A) K线，成交量持续放大
   B) 均线上方无压力、下方有支撑（多头排列，均线全部在下方）
   C) 当日分时图，股价全日位于均线之上（收在日波幅上半部）
   D) 1月内有过涨停
   E) 分时图，股价于 2:30 左右创出当日新高，之后回落（近似：创20日新高后小幅回落）
   大盘环境不好时，不买入（上证指数站上20日线且当日不深跌）

数据说明：日线缓存覆盖 2024-01-01 ~ 2026-09-04（data/.cache/*.csv）
C/E 两项为分时条件，日线数据无法精确复现，以下为日线近似替代：
   - C) 收盘位于当日振幅上半部（近似分时全日站上均价线）
   - E) "2:30创当日新高后回落"近似为：收盘距当日高点回落不超过2%（当日新高附近收盘）
买入价为当日收盘价（近似 14:30 - 15:00 之间成交），卖出取次日开盘价/收盘价两种口径。
"""
import os
import sys
import json
import math
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict

try:
    import baostock as bs
    HAS_BAOSTOCK = True
except Exception:
    HAS_BAOSTOCK = False

project_root = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(project_root, 'data')
CACHE_DIR = os.path.join(data_dir, '.cache')

# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------
PARAMS = dict(
    # 每日 14:30 基本面条件
    gain_low=3.0,          # 涨幅下限（%）
    gain_high=5.0,         # 涨幅上限（%）
    turn_low=5.0,          # 换手率下限（%）
    turn_high=10.0,        # 换手率上限（%）
    vr_low=1.0,            # 量比下限
    vr_high=5.0,           # 量比上限
    mktcap_low=50.0,       # 流通市值下限（亿）
    mktcap_high=200.0,     # 流通市值上限（亿）

    # 技术条件
    vol_increase_days=3,   # 连续放量天数（今日起倒数）
    limit_up_days=20,      # 涨停回看天数（不含当日）
    limit_up_th=0.09,      # 涨停判定涨幅阈值
    pullback_pct=0.02,     # 创新高后允许的最大回落幅度（收盘距当日高点）
    range_position=0.6,    # 收盘需位于当日振幅上沿比例（近似分时均价上方）

    # 均线条件（下方支撑 / 上方无压力）
    ma_short=(5, 10, 20),  # 多头排列
    ma_long=60,            # 长期均线支撑（为 0 则不启用）

    # 大盘环境过滤（上证指数 sh.000001）
    market_filter=True,    # 是否启用大盘过滤
    index_ma=20,           # 指数20日线
    index_min_change=-0.5, # 指数当日跌幅下限（%），超过则不出手

    # 交易与排序
    rank_col='score',      # 排序字段: score/gain_pct/vol_ratio/amount_yi
    top_n=30,              # 每日最多买入数量（尾30）
    start_date='2024-05-01',
    end_date='2099-12-31',
    cache_start='2024-01-01',  # 缓存起止，用于定位缓存文件名
    cache_end='2026-09-04',
)


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def load_index(force_refresh=False):
    """加载上证指数日线（优先本地缓存，否则 baostock 拉取）"""
    cache_file = os.path.join(data_dir, 'sh.000001_daily.csv')
    if os.path.isfile(cache_file) and not force_refresh:
        return pd.read_csv(cache_file, parse_dates=['date'])

    if not HAS_BAOSTOCK:
        return None
    lg = bs.login()
    rs = bs.query_history_k_data_plus(
        'sh.000001', 'date,open,high,low,close,volume,amount',
        start_date=PARAMS['cache_start'], end_date=PARAMS['cache_end'],
        frequency='d', adjustflag='3')
    rows = []
    while rs.error_code == '0' and rs.next():
        rows.append(rs.get_row_data())
    bs.logout()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
    for c in ['open', 'high', 'low', 'close', 'volume', 'amount']:
        df[c] = df[c].astype(float)
    df['date'] = pd.to_datetime(df['date'])
    df.to_csv(cache_file, index=False)
    return df


def load_stock_df(symbol):
    """读取单只股票缓存数据"""
    fp = os.path.join(CACHE_DIR, f'{symbol}_{PARAMS["cache_start"]}_{PARAMS["cache_end"]}.csv')
    if not os.path.isfile(fp):
        return None
    df = pd.read_csv(fp)
    df = df.dropna(subset=['close', 'open', 'volume', 'amount', 'turn'])
    df['date'] = pd.to_datetime(df['date'])
    df.sort_values('date', inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def get_symbols():
    """从 sh_sz_stock.json 获取全部A股代码及名称"""
    with open(os.path.join(data_dir, 'sh_sz_stock.json'), encoding='utf-8') as f:
        data = json.load(f)
    result = {}
    for item in data:
        for code, name in item.items():
            result[code] = name
    return result


# ---------------------------------------------------------------------------
# 选股条件（日线近似）
# ---------------------------------------------------------------------------
def compute_signals(symbol, name, df):
    """在单只股票上计算每日信号。返回 DataFrame（每行一个满足条件的交易日）"""
    n = len(df)
    if n < 100:
        return None

    close = df['close'].to_numpy(dtype=float)
    open_ = df['open'].to_numpy(dtype=float)
    high = df['high'].to_numpy(dtype=float)
    low = df['low'].to_numpy(dtype=float)
    vol = df['volume'].to_numpy(dtype=float)
    amount = df['amount'].to_numpy(dtype=float)
    turn = df['turn'].to_numpy(dtype=float)

    # --- 条件1 涨幅 ---
    pct_change = np.full(n, np.nan)
    pct_change[1:] = (close[1:] / close[:-1] - 1.0) * 100.0
    cond_gain = (pct_change >= PARAMS['gain_low']) & (pct_change <= PARAMS['gain_high'])

    # --- 条件2 换手率 ---
    cond_turn = (turn >= PARAMS['turn_low']) & (turn <= PARAMS['turn_high'])

    # --- 条件3 量比（今量 / 昨5日均量） ---
    vr = np.full(n, np.nan)
    ma5_vol = np.full(n, np.nan)
    for i in range(5, n):
        avg5 = vol[i - 5:i].mean()
        if avg5 > 0:
            ma5_vol[i] = avg5
            vr[i] = vol[i] / avg5
    cond_vr = (vr >= PARAMS['vr_low']) & (vr <= PARAMS['vr_high'])

    # --- 条件4 流通市值（亿）= 成交额/换手率*100 / 1e8 ---
    with np.errstate(divide='ignore', invalid='ignore'):
        mktcap_yi = np.where(turn > 0, amount / turn * 100.0 / 1e8, 0.0)
    cond_mktcap = (mktcap_yi >= PARAMS['mktcap_low']) & (mktcap_yi <= PARAMS['mktcap_high'])
    amount_yi = amount / 1e8

    # --- A 成交量持续放大 ---
    k = PARAMS['vol_increase_days']
    cond_vol_up = np.full(n, True)
    for j in range(k):
        cond_vol_up = cond_vol_up & (vol >= np.roll(vol, j + 1))
    cond_vol_up[: k + 6] = False
    # 今日量须明显高于基准（放大）
    cond_vol_up_extra = vol > ma5_vol

    # --- B 均线支撑（上方无压力、下方有支撑，日线近似） ---
    cond_ma = np.full(n, True)
    prev_ma = None
    ma_list = []
    for period in PARAMS['ma_short']:
        ma = pd.Series(close).rolling(period).mean().to_numpy()
        ma_list.append(ma)
        # 收盘价在所有均线上方（上方无压力）
        cond_ma = cond_ma & (close > ma)
        if prev_ma is not None:
            # 多头排列：短周期均线在上、长周期在下（下方支撑）
            cond_ma = cond_ma & (prev_ma >= ma)
        prev_ma = ma
    # 中期趋势向上（20日线走平或向上）
    ma20 = ma_list[-1]
    ma20_prev = pd.Series(close).rolling(20).mean().shift(1).to_numpy()
    cond_ma = cond_ma & (ma20 >= ma20_prev)
    if PARAMS['ma_long']:
        ma_l = pd.Series(close).rolling(PARAMS['ma_long']).mean().to_numpy()
        ma_l_prev = pd.Series(close).rolling(PARAMS['ma_long']).mean().shift(1).to_numpy()
        cond_ma = cond_ma & (close > ma_l) & (ma_l >= ma_l_prev)
    cond_ma[: PARAMS['ma_long'] + max(PARAMS['ma_short']) + 5] = False

    # --- C 分时均价上方（日线近似：收盘位于日波幅上沿） ---
    rng = high - low
    rng_safe = np.where(rng > 0, rng, np.nan)
    pos_in_range = (close - low) / rng_safe
    cond_avg = (close > open_) & (pos_in_range >= PARAMS['range_position'])

    # --- D 1月内涨停（近 limit_up_days 日，不含今日） ---
    lim_up = np.zeros(n, dtype=bool)
    lim_up[1:] = close[1:] >= close[:-1] * (1 + PARAMS['limit_up_th'])
    c = np.convolve(lim_up, np.ones(PARAMS['limit_up_days'], dtype=int), mode='valid')
    win_sum = np.zeros(n, dtype=int)
    win_sum[PARAMS['limit_up_days']:] = c[: n - PARAMS['limit_up_days']]
    cond_limit = win_sum > 0

    # --- E 2:30创当日新高后回落（日线近似：收盘距当日高点回落很小） ---
    cond_e = ((high - close) / close >= 0) & ((high - close) / close <= PARAMS['pullback_pct'])

    # H) 评分（强中选强）
    score = np.full(n, 0.0)
    mask = cond_avg & cond_e
    score[mask] = pct_change[mask] * 1.0 + np.clip(vr[mask], 0, 10)

    cond = (cond_gain & cond_turn & cond_vr & cond_mktcap &
            cond_vol_up & cond_vol_up_extra & cond_ma &
            cond_avg & cond_limit & cond_e)

    idx = np.where(cond)[0]
    if len(idx) == 0:
        return None

    # 次日买卖价格
    next_open = np.full(n, np.nan)
    next_close = np.full(n, np.nan)
    next_open[:-1] = open_[1:]
    next_close[:-1] = close[1:]
    next_day_pct = np.full(n, np.nan)
    next_day_pct[:-1] = (close[1:] / close[:-1] - 1.0) * 100.0

    out = pd.DataFrame({
        'date': df['date'].iloc[idx].dt.strftime('%Y-%m-%d').values,
        'symbol': symbol,
        'name': name,
        'close': close[idx],
        'gain_pct': pct_change[idx],
        'vol_ratio': vr[idx],
        'turn': turn[idx],
        'amount_yi': amount_yi[idx],
        'mktcap_yi': mktcap_yi[idx],
        'score': score[idx],
        'next_open': next_open[idx],
        'next_close': next_close[idx],
        'next_day_pct': next_day_pct[idx],
    })
    return out


def _market_ok_series(index_df, dates):
    """返回 每个交易日是否允许买入（大盘环境）"""
    idx = index_df.copy()
    idx = idx.set_index('date').sort_index()
    idx['ma'] = idx['close'].rolling(PARAMS['index_ma']).mean()
    idx['pct'] = idx['close'].pct_change() * 100.0
    ok = (idx['close'] > idx['ma']) & (idx['pct'] >= PARAMS['index_min_change'])
    return ok.reindex(index=dates, fill_value=False).to_dict()


# ---------------------------------------------------------------------------
# 回测主流程
# ---------------------------------------------------------------------------
def run_backtest():
    symbols = get_symbols()
    print(f'股票总数: {len(symbols)}')

    print(f'加载上证指数...')
    index_df = load_index()
    if index_df is None:
        PARAMS['market_filter'] = False
        print('  上证指数加载失败, 关闭大盘过滤')

    all_signals = []
    total = len(symbols)
    for i, (symbol, name) in enumerate(symbols.items()):
        if (i + 1) % 500 == 0:
            print(f'  进度: {i + 1}/{total} {datetime.now().strftime("%H:%M:%S")}')
        try:
            df = load_stock_df(symbol)
            if df is None:
                continue
            out = compute_signals(symbol, name, df)
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
    ed = PARAMS['end_date']
    sig = sig[(sig['date'] >= sd) & (sig['date'] <= ed)]

    # 大盘过滤
    if PARAMS['market_filter'] and index_df is not None:
        dates = sorted(sig['date'].unique())
        ok_map = _market_ok_series(index_df, pd.to_datetime(dates))
        sig['market_ok'] = sig['date'].map(ok_map)
        sig = sig[sig['market_ok']]
        print(f'应用大盘过滤后剩余信号: {len(sig)}')

    # 每日排序选股
    trades = []
    for date, grp in sig.groupby('date'):
        grp = grp.sort_values(PARAMS['rank_col'], ascending=False)
        trades.append(grp.head(PARAMS['top_n']))
    trades = pd.concat(trades, ignore_index=True)
    print(f'全部条件信号: {len(sig)} 个, 每日Top{PARAMS["top_n"]}后交易: {len(trades)} 笔')

    # 收益口径（扣除手续费约 0.1%）
    fee = 0.001
    trades['ret_open'] = (trades['next_open'] / trades['close'] - 1.0) * 100.0 - fee * 100
    trades['ret_close'] = (trades['next_close'] / trades['close'] - 1.0) * 100.0 - fee * 100
    trades_valid = trades.dropna(subset=['ret_open', 'ret_close'])

    print_stats(trades_valid)
    save_results(trades_valid)


def print_stats(tdf):
    print('\n' + '=' * 78)
    print('尾盘30分钟 一夜持股策略 回测统计')
    print('=' * 78)
    print(f'  交易笔数: {len(tdf)}')
    if len(tdf) == 0:
        return

    for label, col in [('次日开盘卖', 'ret_open'), ('次日收盘卖', 'ret_close')]:
        r = tdf[col].dropna()
        if len(r) == 0:
            continue
        wins = (r > 0).sum()
        wr = wins / len(r) * 100
        avg = r.mean()
        med = r.median()
        mx = r.max()
        mn = r.min()
        print(f'\n  【{label}】(含手续费0.1%)')
        print(f'    胜率: {wr:.2f}% ({wins}/{len(r)})')
        print(f'    平均收益: {avg:+.2f}% | 中位数: {med:+.2f}% | 最大: {mx:+.2f}% | 最小: {mn:+.2f}%')

        # 连续表现
        streak_w, streak_l = 0, 0
        best_w, best_l = 0, 0
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

        # 按月
        sub = tdf[['date', col]].copy()
        sub['month'] = sub['date'].str[:7]
        mon = sub.groupby('month')[col].agg(['count', 'mean', lambda s: (s > 0).sum()])
        mon.columns = ['count', 'avg', 'wins']
        mon['win_rate'] = (mon['wins'] / mon['count'] * 100).round(1)
        mon['avg'] = mon['avg'].round(2)
        print(f'\n  月份明细:')
        for m, row in mon.iterrows():
            print(f'    {m}  次数={int(row["count"]):>4}  胜率={row["win_rate"]:>6.1f}%  平均={row["avg"]:>+6.2f}%')

    # 交易最靠前的明细示例
    print('\n  最近20笔(次日开盘卖):')
    sub = tdf[['date', 'symbol', 'name', 'close', 'next_open', 'ret_open']].dropna(subset=['ret_open']).tail(20)
    print(sub.to_string(index=False))


def save_results(tdf):
    fp = os.path.join(data_dir, 'tail30_trades.csv')
    tdf.sort_values('date').to_csv(fp, index=False, encoding='utf-8-sig')
    print(f'\n交易明细已保存: {fp}')
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib as mpl
        mpl.rcParams['font.sans-serif'] = ['PingFang SC', 'Arial Unicode MS', 'SimHei']
        mpl.rcParams['axes.unicode_minus'] = False
        sub = tdf[['date', 'ret_open', 'ret_close']].dropna(subset=['ret_open']).sort_values('date').copy()
        sub['cum_open'] = (sub['ret_open'] / 100.0 + 1).cumprod()
        sub['cum_close'] = (sub['ret_close'] / 100.0 + 1).cumprod()
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(sub['date'], sub['cum_open'], label='次日开盘卖')
        ax.plot(sub['date'], sub['cum_close'], label='次日收盘卖')
        ax.axhline(1.0, color='gray', ls='--', lw=0.8)
        ax.set_title(f'尾盘30分钟一夜持股 | 交易{len(sub)}笔 | 次日开盘卖胜率{(sub["ret_open"] > 0).mean() * 100:.1f}%')
        ax.set_ylabel('累计净值（1元起）')
        ax.legend()
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        out = os.path.join(data_dir, 'tail30_backtest.png')
        fig.savefig(out, dpi=110, bbox_inches='tight')
        plt.close(fig)
        print(f'收益曲线已保存: {out}')
    except Exception as e:
        print(f'绘图失败: {e}')


if __name__ == '__main__':
    run_backtest()