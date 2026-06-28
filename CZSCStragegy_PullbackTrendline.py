# coding: utf-8
"""
回踩上涨通道趋势线选股

核心逻辑（基于czsc缠论笔结构）：
1. 使用CZSC获取笔（bi）数据
2. 筛选一年内完成的向上笔
3. 找出2个向上笔——分别对应一年内股价最高点（最高点）和次高点（次高点）
4. 最高点必须出现在次高点之后（新高突破形态）
5. 当前股价在两点连线的5%范围内（回踩确认连线支撑）

技术含义：股价突破前高后回踩趋势线，测试连线支撑有效
"""
import os
import sys
import time
import logging
import numpy as np
import pandas as pd
import baostock as bs
from datetime import datetime, timedelta
from collections import OrderedDict

from lib.MyTT import *
from czsc.analyze import CZSC
from czsc.objects import RawBar, Direction, Freq
from czsc.enum import Mark
from czsc_daily_util import (
    get_stock_pd, get_daily_symbols, get_symbols_name,
    get_data_dir, read_json, write_json, czsc_logger,
    get_latest_trade_date
)


def bars_from_df(df, symbol):
    """DataFrame -> RawBar列表"""
    bars = []
    for i, row in df.iterrows():
        dt = pd.to_datetime(row['date']) if not isinstance(row['date'], datetime) else row['date']
        bars.append(RawBar(
            symbol=symbol, id=i, freq=Freq.D,
            open=row['open'], close=row['close'],
            high=row['high'], low=row['low'],
            vol=row['volume'], amount=row.get('amount', 0),
            dt=dt,
        ))
    return bars


def get_last_year_up_bis(bi_list, ref_date):
    """获取一年内完成的向上笔列表"""
    start = ref_date - timedelta(days=365)
    up_bis = [bi for bi in bi_list
              if bi.direction == Direction.Up
              and start <= bi.edt <= ref_date]
    return up_bis


def detect_trendline_pullback(bi_list, ref_date, current_close, current_bar_idx=None):
    """
    检测回踩趋势线模式

    条件：
    1. 一年内至少2个向上笔
    2. 次高点和最高点来自不同向上笔的顶分型（fx_b.fx = 笔顶点）
    3. 最高点在次高点之后形成（新高突破）
    4. 当前股价在连线附近5%范围内

    连线定义（二选一，任一满足即可）：
      a. 斜线：次高点→最高点的趋势线延伸至当前位置
      b. 水平位：次高点价格水平位（前高支撑=经典回踩位）

    返回 dict / None
    """
    up_bis = get_last_year_up_bis(bi_list, ref_date)
    if len(up_bis) < 2:
        return None

    peaks = []
    for bi in up_bis:
        bar_idx = bi.fx_b.elements[1].id if (bi.fx_b and bi.fx_b.elements and len(bi.fx_b.elements) > 1) else 0
        peaks.append({
            'price': bi.fx_b.fx,
            'date': bi.edt,
            'bar_idx': bar_idx,
        })

    peaks_by_price = sorted(peaks, key=lambda x: x['price'], reverse=True)
    highest = peaks_by_price[0]

    # 找在最高点之前的次高点
    second = None
    for p in peaks_by_price[1:]:
        if p['date'] < highest['date']:
            second = p
            break
    if second is None:
        return None

    if current_bar_idx is None:
        last_bi = bi_list[-1]
        if last_bi.fx_b and last_bi.fx_b.elements:
            current_bar_idx = last_bi.fx_b.elements[-1].id
        elif last_bi.fx_a and last_bi.fx_a.elements:
            current_bar_idx = last_bi.fx_a.elements[-1].id
        else:
            current_bar_idx = max(p['bar_idx'] for p in peaks)

    # 必须在最高点之后（回踩确认）
    if current_bar_idx <= highest['bar_idx']:
        return None
    if current_close >= highest['price']:
        return None

    # ── 方法A: 斜线趋势线延伸 ──
    slope = (highest['price'] - second['price']) / (highest['bar_idx'] - second['bar_idx']) if highest['bar_idx'] != second['bar_idx'] else 0
    line_diag = highest['price'] + (current_bar_idx - highest['bar_idx']) * slope

    # ── 方法B: 前高水平位 ──
    line_horiz = second['price']

    # 用离当前价最近的那个判断
    diff_diag = abs(current_close - line_diag) / line_diag * 100 if line_diag > 0 else 999
    diff_horiz = abs(current_close - line_horiz) / line_horiz * 100 if line_horiz > 0 else 999
    best_diff = min(diff_diag, diff_horiz)
    best_line = line_diag if diff_diag <= diff_horiz else line_horiz

    if best_diff > 5:
        return None

    pullback_pct = (highest['price'] - current_close) / highest['price'] * 100

    return {
        'highest_price': round(highest['price'], 2),
        'highest_date': highest['date'].strftime('%Y-%m-%d'),
        'second_price': round(second['price'], 2),
        'second_date': second['date'].strftime('%Y-%m-%d'),
        'line_price': round(best_line, 2),
        'line_method': 'diag' if diff_diag <= diff_horiz else 'horiz',
        'pct_diff': round(best_diff, 2),
        'pullback_pct': round(pullback_pct, 2),
        'up_bi_count': len(up_bis),
    }


def score_pullback(result):
    """对符合基本条件的股票评分"""
    s = 0
    details = []
    method = '斜线' if result.get('line_method') == 'diag' else '水平'

    # 1. 距连线越近越好（40分）
    pct = result['pct_diff']
    s += max(5, 40 - int(pct * 7))
    details.append(f'距{method}连线{pct:.1f}%')

    # 2. 两次高点差距（强度）
    pwr = (result['highest_price'] - result['second_price']) / result['second_price'] * 100
    if pwr > 15:
        s += 20
        details.append(f'高点差{pwr:.1f}%强(+20)')
    elif pwr > 8:
        s += 15
        details.append(f'高点差{pwr:.1f}%(+15)')
    elif pwr > 3:
        s += 10
        details.append(f'高点差{pwr:.1f}%(+10)')

    # 3. 回踩幅度适中
    pb = result['pullback_pct']
    if 3 <= pb <= 15:
        s += 25
        details.append(f'回踩{pb:.1f}%适度(+25)')
    elif pb < 3:
        s += 10
        details.append(f'回踩不足{pb:.1f}%(+10)')

    # 4. 向上笔数量（趋势持续性）
    if result['up_bi_count'] >= 4:
        s += 15
        details.append(f'{result["up_bi_count"]}个向上笔持续(+15)')
    elif result['up_bi_count'] >= 3:
        s += 10
        details.append(f'{result["up_bi_count"]}个向上笔(+10)')

    return min(s, 100), details


def analyze_stock(df, symbol, ref_date=None):
    """
    分析单只股票的回踩趋势线信号

    参数:
        df: OHLCV DataFrame
        symbol: 股票代码
        ref_date: 参考日期（默认最后交易日）

    返回: dict（含信号结果）/ None
    """
    if df is None or len(df) < 200:
        return None

    if ref_date is None:
        ref_date = pd.to_datetime(df['date'].iloc[-1])
    else:
        ref_date = pd.to_datetime(ref_date)

    bars = bars_from_df(df, symbol)
    c = CZSC(bars)
    bi_list = c.bi_list

    if len(bi_list) < 5:
        return None

    current_close = df['close'].values[-1]
    current_bar_idx = len(bars) - 1

    result = detect_trendline_pullback(bi_list, ref_date, current_close, current_bar_idx)
    if result is None:
        return None

    score_val, details = score_pullback(result)
    if score_val < 40:
        return None

    # 附加基本数据
    result['score'] = score_val
    result['details'] = details
    result['close'] = current_close
    result['high_52w'] = float(df['high'].values[-min(252, len(df)):].max()) if len(df) >= 20 else current_close
    result['low_52w'] = float(df['low'].values[-min(252, len(df)):].min()) if len(df) >= 20 else current_close
    result['date'] = ref_date.strftime('%Y-%m-%d') if hasattr(ref_date, 'strftime') else str(ref_date)
    return result


def format_output(results):
    """格式化控制台输出"""
    passed = [r for r in results if r and r.get('score', 0) >= 40]
    passed.sort(key=lambda x: x['score'], reverse=True)

    lines = [
        f"\n{'=' * 120}",
        f"回踩上涨通道趋势线选股  |  共分析{sum(1 for r in results if r is not None)}只"
        f"  |  入选{len(passed)}只",
        f"{'=' * 120}",
        f"{'代码':>10} {'名称':>8} {'评分':>4} {'收盘':>8} {'最高':>8} {'次高':>8} "
        f"{'连线':>8} {'偏差%':>6} {'回踩%':>6} {'高点差%':>7} {'方法':>4}",
        "-" * 120,
    ]

    for r in passed:
        pwr = (r['highest_price'] - r['second_price']) / r['second_price'] * 100
        method = '斜' if r.get('line_method') == 'diag' else '水'
        lines.append(
            f"{r['symbol']:>10} {r['name']:>8} {r['score']:>4} "
            f"{r['close']:>8.2f} {r['highest_price']:>8.2f} {r['second_price']:>8.2f} "
            f"{r['line_price']:>8.2f} {r['pct_diff']:>6.2f} {r['pullback_pct']:>6.2f} "
            f"{pwr:>6.1f}% {method:>4}"
        )
    lines.append("-" * 120)
    return '\n'.join(lines)


def scan_stocks(min_score=40):
    """扫描全市场"""
    symbols = get_daily_symbols()
    logger = czsc_logger()
    logger.info(f"开始扫描回踩趋势线信号，共{len(symbols)}只...")

    results = []
    count = 0
    t0 = time.time()
    ref_date = datetime.now()
    start_date = (ref_date - timedelta(days=720)).strftime('%Y-%m-%d')
    end_date = ref_date.strftime('%Y-%m-%d')

    for symbol in symbols:
        count += 1
        if count % 100 == 0:
            elapsed = time.time() - t0
            logger.info(f"进度 {count}/{len(symbols)} | "
                        f"{count / elapsed:.0f}只/秒 | "
                        f"入选{sum(1 for r in results if r and r['score'] >= min_score)}只")
        try:
            df = get_stock_pd(symbol, start_date, end_date, 'd')
            r = analyze_stock(df, symbol, ref_date)
            if r:
                r['symbol'] = symbol
                r['name'] = get_symbols_name(symbol)
                results.append(r)
                logger.info(f"  ✓ {symbol} {r['name']} 评分{r['score']} "
                            f"收盘{r['close']:.2f} 连线偏差{r['pct_diff']:.1f}% "
                            f"回踩{r['pullback_pct']:.1f}%")
            else:
                results.append(None)
        except Exception as e:
            logger.error(f"{symbol} 失败: {e}")
            results.append(None)

    elapsed = time.time() - t0
    qualified = sum(1 for r in results if r and r['score'] >= min_score)
    logger.info(f"完成！耗时{elapsed:.0f}s，{count}只，入选{qualified}只")
    return results


def save_results(results, output_path):
    """保存结果到JSON"""
    passed = [r for r in results if r and r.get('score', 0) >= 40]
    passed.sort(key=lambda x: x['score'], reverse=True)
    data = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total': sum(1 for r in results if r is not None),
        'qualified': len(passed),
        'stocks': [],
    }
    for r in passed:
        data['stocks'].append({
            'symbol': r['symbol'],
            'name': r['name'],
            'score': r['score'],
            'close': r['close'],
            'highest_price': r['highest_price'],
            'highest_date': r.get('highest_date', ''),
            'second_price': r['second_price'],
            'second_date': r.get('second_date', ''),
            'line_price': r['line_price'],
            'pct_diff': r['pct_diff'],
            'pullback_pct': r['pullback_pct'],
            'details': r.get('details', []),
        })
    write_json(data, output_path)
    return data


def main():
    print("=" * 60)
    print("回踩上涨通道趋势线选股系统")
    print("基于CZSC缠论笔结构")
    print("=" * 60)

    bs.login()
    try:
        results = scan_stocks(min_score=40)
    finally:
        bs.logout()

    output_path = os.path.join(get_data_dir(), '回踩趋势线.json')
    save_results(results, output_path)
    print(f"\n结果已保存至: {output_path}")

    output = format_output(results)
    print(output)

    print(f"\n{'=' * 110}")
    print(f"信号说明：")
    print(f"  评分≥40入选，最高100")
    print(f"  偏差% = |收盘价 - 趋势线值| / 趋势线值 × 100")
    print(f"  回踩% = (最高点 - 收盘价) / 最高点 × 100")
    print(f"  高点差% = (最高点 - 次高点) / 次高点 × 100")
    print(f"{'=' * 110}")


if __name__ == '__main__':
    main()
