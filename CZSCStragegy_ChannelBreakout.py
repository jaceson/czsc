# coding: utf-8
"""
突破上涨通道选股 - 股票筛选器（pytdx 季度财务数据版）

核心逻辑（三通道+趋势确认）：
1. 上涨通道识别：股价在上升回归通道内运行，斜率>0
2. 通道突破：价格放量突破通道上轨（趋势线阻力）
3. 趋势确认：中长期均线多头排列，相对强度达标

财务数据基于 pytdx gpcw 季度财报，替代原 baostock 接口

使用方法：
    python CZSCStragegy_ChannelBreakout.py

输出：data/突破上涨通道.json + 控制台结果
"""
import os
import sys
import json
import time
import glob
import logging
import numpy as np
import pandas as pd
import baostock as bs
from datetime import datetime, timedelta
from lib.MyTT import *
from czsc_daily_util import (
    get_stock_pd, get_daily_symbols, get_symbols_name,
    get_data_dir, read_json, write_json, czsc_logger,
    get_latest_trade_date, get_financial_growth_tdx
)


# ──────────────────────────────────────────────
# 通道检测方法
# ──────────────────────────────────────────────

def detect_regression_channel(close, period=60, width=1.5):
    """
    线性回归通道
    - 对最近N日收盘价做线性回归，置信带作为通道
    - 通道上轨=回归线+width*σ，下轨=回归线-width*σ
    """
    x = np.arange(period)
    y = close[-period:]
    A = np.vstack([x, np.ones(period)]).T
    slope, intercept = np.linalg.lstsq(A, y, rcond=None)[0]
    reg = slope * x + intercept
    resid = y - reg
    std = float(np.std(resid)) or 1e-8
    return {
        'up': float(reg[-1] + width * std),
        'mid': float(reg[-1]),
        'down': float(reg[-1] - width * std),
        'slope': float(slope),
        'r2': float(1 - np.sum(resid**2) / max(np.sum((y - np.mean(y))**2), 1e-8)),
        'current_close': float(y[-1]),
    }


def detect_donchian_breakout(close, high, low, period=20):
    """
    唐奇安通道（N日高低通道）
    - 突破上轨=创N日新高，配合趋势方向
    """
    upper = HHV(high, period)
    lower = LLV(low, period)
    mid = (upper + lower) / 2
    slope = float(upper[-1] - upper[-min(5, len(upper))]) if len(upper) >= 5 else 0
    return {
        'up': float(upper[-1]) if not np.isnan(upper[-1]) else 0,
        'mid': float(mid[-1]) if not np.isnan(mid[-1]) else 0,
        'down': float(lower[-1]) if not np.isnan(lower[-1]) else 0,
        'slope': slope if not np.isnan(slope) else 0,
        'breakout_pct': float((close[-1] - upper[-1]) / upper[-1] * 100) if not np.isnan(upper[-1]) else 0,
    }


def detect_ma_trend(close):
    """
    均线趋势检测
    """
    ma5 = MA(close, 5)
    ma10 = MA(close, 10)
    ma20 = MA(close, 20)
    ma60 = MA(close, 60)
    ma120 = MA(close, 120) if len(close) >= 120 else ma60

    r = {'ma5': float(ma5[-1]), 'ma10': float(ma10[-1]), 'ma20': float(ma20[-1]),
         'ma60': float(ma60[-1]) if len(close) >= 60 else None,
         'ma120': float(ma120[-1]) if len(close) >= 120 else None}

    r['ma5_higher_ma10'] = ma5[-1] > ma10[-1] if not (np.isnan(ma5[-1]) or np.isnan(ma10[-1])) else False
    r['ma10_higher_ma20'] = ma10[-1] > ma20[-1] if not (np.isnan(ma10[-1]) or np.isnan(ma20[-1])) else False
    r['ma20_higher_ma60'] = ma20[-1] > ma60[-1] if not (np.isnan(ma20[-1]) or np.isnan(ma60[-1])) else False
    r['ma20_slope_up'] = ma20[-1] > ma20[-5] if not (np.isnan(ma20[-1]) or np.isnan(ma20[-5])) else False
    r['close_above_ma20'] = close[-1] > ma20[-1] if not np.isnan(ma20[-1]) else False
    r['close_above_ma60'] = close[-1] > ma60[-1] if len(close) >= 60 and not np.isnan(ma60[-1]) else False
    return r


def detect_volume_surge(volume):
    """
    成交量放大检测
    """
    ma5 = MA(volume, 5)
    ma20 = MA(volume, 20)
    v = float(volume[-1]) if not np.isnan(volume[-1]) else 0
    m5 = float(ma5[-1]) if not np.isnan(ma5[-1]) else v
    m20 = float(ma20[-1]) if not np.isnan(ma20[-1]) else v
    return {
        'volume': v,
        'ma5': m5,
        'ratio_v_ma5': v / m5 if m5 > 0 else 1,
        'ratio_v_ma20': v / m20 if m20 > 0 else 1,
        'surge_ma5': v > m5 * 1.3,
        'surge_ma20': v > m20 * 1.3,
    }


def check_market_environment(index_code='sh.000300', lookback=5):
    """
    大盘环境判断
    返回: 'uptrend' / 'downtrend' / 'sideways'
    """
    try:
        end_date = get_latest_trade_date()
        start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=lookback * 2)).strftime('%Y-%m-%d')
        df = get_stock_pd(index_code, start_date, end_date, 'd')
        if df is None or len(df) < lookback:
            return 'sideways'
        c = df['close'].values.astype(float)
        ma5 = MA(c, 5)
        ma10 = MA(c, 10)
        if ma5[-1] > ma10[-1] and ma5[-2] > ma10[-2] and ma5[-3] > ma10[-3]:
            return 'uptrend'
        elif ma5[-1] < ma10[-1] and ma5[-2] < ma10[-2] and ma5[-3] < ma10[-3]:
            return 'downtrend'
        return 'sideways'
    except Exception:
        return 'downtrend'


def calc_rps(stock_close, lookback=20):
    """
    简化RPS（相对强度）：个股过去N日涨幅
    后续可扩展为全市场百分位排名
    """
    if len(stock_close) < lookback + 1:
        return 0
    pct = (stock_close[-1] - stock_close[-lookback - 1]) / stock_close[-lookback - 1] * 100
    return pct


def calc_atr_stop(df, period=14, multiplier=1.5):
    """
    基于ATR的动态止损/止盈位
    """
    high = df['high'].values.astype(float)
    low = df['low'].values.astype(float)
    close = df['close'].values.astype(float)
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr = float(np.mean(tr[-period:]))
    atr = max(atr, 0.01)
    entry = float(close[-1])
    return {
        'atr': round(atr, 3),
        'stop_loss': round(entry - multiplier * atr, 2),
        'take_profit_1': round(entry + multiplier * atr, 2),
        'take_profit_2': round(entry + 2 * multiplier * atr, 2),
        'trailing_ma10': round(float(MA(close, 10)[-1]), 2),
    }


# ──────────────────────────────────────────────
# 财务数据查询
# ──────────────────────────────────────────────

def get_financial_growth(symbol):
    """
    获取最新一季度营收和利润同比增长率（基于 pytdx gpcw 财务数据）

    返回: dict {'revenue_yoy': %, 'profit_yoy': %, 'year':, 'quarter': }
          或 None（数据不可用）
    """
    return get_financial_growth_tdx(symbol)


# ──────────────────────────────────────────────
# 综合评分
# ──────────────────────────────────────────────

def score_channel_breakout(df, lookback=60, market_state='sideways', financial=None):
    """
    综合评分：检测个股是否处于上涨通道突破状态

    参数:
        financial: get_financial_growth 返回值，包含营收和利润增长率

    返回: dict 包含各项评分及明细，或 None（财务数据不合格）
    """
    c = df['close'].values.astype(float)
    h = df['high'].values.astype(float)
    l = df['low'].values.astype(float)
    v = df['volume'].values.astype(float) if 'volume' in df.columns else np.ones(len(c))
    o = df['open'].values.astype(float) if 'open' in df.columns else None

    if len(c) < max(lookback, 120):
        return None

    # 0. 成交额限制：日均成交额 >= 10亿
    if 'amount' in df.columns:
        amount_arr = df['amount'].values.astype(float)
        avg_amount = np.mean(amount_arr[-20:])
        if avg_amount < 1_000_000_000:
            return None

    # 1. 回归通道（自适应参数：选R²最高的组合）
    best_reg = None
    best_r2 = -1
    for p in [30, 45, 60]:
        for w in [1.0, 1.5, 2.0]:
            r = detect_regression_channel(c, period=min(p, len(c) - 1), width=w)
            if r['r2'] > best_r2:
                best_r2 = r['r2']
                best_reg = r
    reg = best_reg

    # 2. 唐奇安通道
    dnc = detect_donchian_breakout(c, h, l, period=20)
    # 3. 均线趋势
    ma = detect_ma_trend(c)
    # 4. 成交量
    vol = detect_volume_surge(v)
    # 5. ATR止损位
    atr_stop = calc_atr_stop(df)
    # 6. RPS相对强度
    rps = calc_rps(c, lookback=20)

    # ── 评分 ──
    s = 0
    details = []

    # ① 通道斜率 > 0（上涨通道）
    if reg['slope'] > 0:
        s += 15
        details.append('回归通道向上(+15)')
    else:
        details.append('回归通道向下(+0)')

    # ② 通道完整性（R² > 0.6 说明通道线性良好，短线要求更高）
    if reg['r2'] > 0.6:
        s += 10
        details.append(f'通道线性良好R²={reg["r2"]:.2f}(+10)')

    # ③ 突破回归通道上轨 + 突破质量校验
    reg_break = c[-1] > reg['up']
    if reg_break:
        s += 25
        details.append(f'突破回归上轨({c[-1]:.2f}>{reg["up"]:.2f})(+25)')
        # 突破质量：阳线实体占比 > 60%
        if o is not None:
            body = abs(c[-1] - o[-1])
            upper_shadow = h[-1] - max(c[-1], o[-1])
            quality = body / (body + upper_shadow + 0.01)
            if quality > 0.6:
                s += 8
                details.append(f'突破阳线实体占比{quality:.0%}(+8)')
    elif c[-1] > reg['mid']:
        s += 10
        details.append(f'在回归通道中轨上方(+10)')

    # ④ 唐奇安通道突破（20日新高）
    if dnc['breakout_pct'] > 0.5:
        s += 20
        details.append(f'创{20}日新高+{dnc["breakout_pct"]:.1f}%(+20)')
    elif dnc['breakout_pct'] > 0:
        s += 10
        details.append(f'接近{20}日新高({dnc["breakout_pct"]:.1f}%)(+10)')

    # ⑤ 唐奇安通道向上
    if dnc['slope'] > 0:
        s += 5
        details.append('唐奇安通道向上(+5)')

    # ⑥ 均线多头排列加分
    if ma['ma5_higher_ma10']:
        s += 5
        details.append('MA5>MA10(+5)')
    if ma['ma10_higher_ma20']:
        s += 5
        details.append('MA10>MA20(+5)')
    if ma['ma20_higher_ma60'] and ma['ma60'] is not None:
        s += 8
        details.append('MA20>MA60(+8)')
    if ma['ma20_slope_up']:
        s += 5
        details.append('MA20向上(+5)')
    if ma['close_above_ma20']:
        s += 3
        details.append('收盘>MA20(+3)')
    if ma['close_above_ma60'] and ma['ma60'] is not None:
        s += 4
        details.append('收盘>MA60(+4)')

    # ⑦ 成交量（短线要求更高：1.5倍起）
    ratio_v = vol['ratio_v_ma5']
    if vol['surge_ma5']:
        if ratio_v >= 2.0:
            s += 15
            details.append(f'倍量({ratio_v:.1f}xMA5)(+15)')
        elif ratio_v >= 1.5:
            s += 10
            details.append(f'放量({ratio_v:.1f}xMA5)(+10)')
        else:
            s += 5
            details.append(f'温和放量({ratio_v:.1f}xMA5)(+5)')

    # ⑧ 最近3日涨幅（收紧上限，防追高）
    if len(c) >= 4:
        pct_3d = (c[-1] - c[-4]) / c[-4] * 100
    else:
        pct_3d = 0
    if 1 < pct_3d < 10:
        s += 5
        details.append(f'3日涨幅{pct_3d:.1f}%温和(+5)')
    elif pct_3d >= 10:
        details.append(f'3日涨幅{pct_3d:.1f}%偏高(+0)')

    # ⑨ RPS相对强度（跑赢大盘）
    if rps > 10:
        s += 10
        details.append(f'RPS过去20日涨幅{rps:.1f}%(+10)')
    elif rps > 0:
        s += 3
        details.append(f'RPS过去20日涨幅{rps:.1f}%(+3)')

    # ⑩ 财务增长检查（前置到信号列表顶部，确保在格式输出中可见）
    if financial is not None:
        rev_ok = financial['revenue_yoy'] > 0
        profit_ok = financial['profit_yoy'] >= 20
        if rev_ok and profit_ok:
            s += 15
            details.insert(0, f"营收增长{financial['revenue_yoy']:.1f}%(+8)")
            details.insert(1, f"净利增长{financial['profit_yoy']:.1f}%(+7)")

    # ⑪ 大盘环境加权
    if market_state == 'uptrend':
        s += 5
        details.append('大盘处于上升趋势(+5)')
    elif market_state == 'downtrend':
        details.append('大盘处于下降趋势(+0)')

    return {
        'score': s,
        'regression': reg,
        'donchian': dnc,
        'ma': ma,
        'volume': vol,
        'atr_stop': atr_stop,
        'rps': round(rps, 2),
        'details': details,
        'close': float(c[-1]),
        'pre_close': float(c[-2]) if len(c) >= 2 else float(c[-1]),
        'high': float(h[-1]),
        'low': float(l[-1]),
        'ma5': float(ma['ma5']) if ma['ma5'] else float(c[-1]),
        'date': str(df['date'].iloc[-1]) if 'date' in df.columns else '',
    }


# ──────────────────────────────────────────────
# 结果输出
# ──────────────────────────────────────────────

def format_result(result_list):
    """格式化结果输出"""
    lines = []
    lines.append(f"\n{'=' * 90}")
    lines.append(f"突破上涨通道选股结果  |  共分析{sum(1 for r in result_list if r is not None)}只 "
                 f"|  筛选出{sum(1 for r in result_list if r and r['score'] >= 60)}只")
    lines.append(f"{'=' * 90}")
    lines.append(f"{'代码':>10} {'名称':>8} {'评分':>4} {'收盘':>8} {'涨幅%':>7} "
                 f"{'突破回上轨':>9} {'新高%':>6} {'量比':>5} {'信号摘要':<30}")
    lines.append("-" * 90)

    passed = [r for r in result_list if r and r['score'] >= 60]
    passed.sort(key=lambda x: x['score'], reverse=True)

    for r in passed:
        c = r['close']
        h = r['high']
        d = r['donchian']
        v = r['volume']
        reg = r['regression']
        reg_break = '✓' if c > reg['up'] else '△' if c > reg['mid'] else ''
        hi_pct = f"{d['breakout_pct']:.1f}%" if d['breakout_pct'] > 0 else "新低"
        vol_ratio = f"{v['ratio_v_ma5']:.1f}x"
        # 涨幅计算（前5日）
        lines.append(
            f"{r['symbol']:>10} {r['name']:>8} {r['score']:>4} "
            f"{c:>8.2f} {r.get('pct_5d', 0):>7.2f} "
            f"{reg_break:>9} {hi_pct:>6} {vol_ratio:>5} "
            f"{'|'.join(detail.split('(')[0] for detail in r['details'][:3]):<30}"
        )
    return '\n'.join(lines)


def format_result_markdown(result_list, md_out=None):
    """输出选股结果 Markdown 表格（可直接发布公众号）"""
    passed = [r for r in result_list if isinstance(r, dict) and r.get('score', 0) >= 60]
    passed.sort(key=lambda x: x['score'], reverse=True)

    lines = []
    lines.append(f"## 突破上涨通道选股结果")
    lines.append(f"")
    lines.append(f"> 共分析 {sum(1 for r in result_list if r is not None)} 只 | 筛选出 {len(passed)} 只\n")
    lines.append("| 代码 | 名称 | 评分 | 收盘 | 5日涨幅% | 突破 | 量比 | 信号摘要 |")
    lines.append("|------|------|------|------|----------|------|------|----------|")

    for r in passed:
        c = r['close']
        d = r['donchian']
        v = r['volume']
        reg = r['regression']
        reg_break = '✅ 突破上轨' if c > reg['up'] else '🔺 中轨上方' if c > reg['mid'] else ''
        hi_pct = f"{d['breakout_pct']:.1f}%" if d['breakout_pct'] > 0 else "新低"
        vol_ratio = f"{v['ratio_v_ma5']:.1f}x"
        sig = ' '.join(detail.split('(')[0] for detail in r['details'][:3])
        lines.append(
            f"| {r['symbol']} | {r['name']} | {r['score']} "
            f"| {c:.2f} | {r.get('pct_5d', 0):.2f} "
            f"| {reg_break} | {vol_ratio} | {sig} |"
        )

    md = '\n'.join(lines)
    if md_out:
        with open(md_out, 'w', encoding='utf-8') as f:
            f.write(md)
    return md


def format_daily_change_table(result_list):
    """输出今日涨跌幅表格（Markdown格式）"""
    lines = []
    valid = [r for r in result_list if isinstance(r, dict) and r.get('score', 0) >= 60]
    lines.append(f"\n## 今日涨跌幅明细")
    lines.append(f"共 {len(valid)} 只入选\n")
    lines.append("| 名称 | 代码 | 日期 | 今日收盘 | 昨日收盘 | 涨幅 |")
    lines.append("|------|------|------|----------|----------|------|")

    passed = sorted(valid, key=lambda x: x['score'], reverse=True)

    for r in passed:
        pre = r.get('pre_close', r['close'])
        change_pct = (r['close'] - pre) / pre * 100
        arrow = '📈' if change_pct > 0 else '📉' if change_pct < 0 else '➖'
        lines.append(
            f"| {r['name']} | {r['symbol']} | {r.get('date', '')} "
            f"| {r['close']:.2f} | {pre:.2f} "
            f"| {arrow}{change_pct:+.2f}% |"
        )
    return '\n'.join(lines)


def save_results(result_list, output_path, market_state='sideways'):
    """保存筛选结果到JSON"""
    passed = [r for r in result_list if r and r['score'] >= 60]
    passed.sort(key=lambda x: x['score'], reverse=True)

    data = {
        'update_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'market_state': market_state,
        'total_stocks': sum(1 for r in result_list if r is not None),
        'total_qualified': len(passed),
        'min_score': 60,
        'stocks': []
    }
    for r in passed:
        stop = r.get('atr_stop', {})
        pre = r.get('pre_close', r['close'])
        change_pct = round((r['close'] - pre) / pre * 100, 2)
        data['stocks'].append({
            'symbol': r['symbol'],
            'name': r['name'],
            'date': r.get('date', ''),
            'score': r['score'],
            'close': round(r['close'], 2),
            'pre_close': round(pre, 2),
            'change_pct': change_pct,
            'low': round(r['low'], 2),
            'ma5': round(r.get('ma5', 0), 2),
            'regression_breakout': bool(r['close'] > r['regression']['up']),
            'donchian_breakout_pct': round(r['donchian']['breakout_pct'], 2),
            'volume_ratio': round(r['volume']['ratio_v_ma5'], 2),
            'rps': round(r.get('rps', 0), 2),
            'stop_loss': stop.get('stop_loss'),
            'take_profit_1': stop.get('take_profit_1'),
            'take_profit_2': stop.get('take_profit_2'),
            'atr': stop.get('atr'),
            'financial': {
                'revenue_yoy': r.get('revenue_yoy'),
                'profit_yoy': r.get('profit_yoy'),
            } if r.get('revenue_yoy') is not None else None,
            'details': r['details'][:5],
        })
    write_json(data, output_path)
    return data


def _read_stock_cache(symbol, cache_dir):
    """从缓存目录读取股票最新两日数据，返回 (date, close, pre_close, low) 或 None"""
    pattern = os.path.join(cache_dir, f"{symbol}_*.csv")
    matches = sorted(glob.glob(pattern))
    if not matches:
        return None
    try:
        df = pd.read_csv(matches[-1])
        tail = df.tail(5)
        if len(tail) < 2:
            return None
        date = str(tail['date'].iloc[-1])
        close = float(tail['close'].iloc[-1])
        pre_close = float(tail['close'].iloc[-2])
        low = float(tail['low'].iloc[-1])
        return date, close, pre_close, low
    except Exception:
        return None


def format_daily_change_from_json(json_path):
    """从突破上涨通道.json + .cache 读取数据，输出涨跌幅 Markdown 表格"""
    if not os.path.isfile(json_path):
        return ""

    data = read_json(json_path)
    stocks = data.get('stocks', []) if isinstance(data, dict) else data
    if not stocks:
        return ""

    # 统一使用最新交易日
    latest_date = get_latest_trade_date()

    cache_dir = os.path.join(get_data_dir(), '.cache')
    lines = []
    lines.append(f"\n## 今日涨跌幅明细（{latest_date}）")
    lines.append(f"更新: {data.get('update_time', '')} | 大盘: {data.get('market_state', '')} | 共 {len(stocks)} 只入选\n")
    lines.append("| 名称 | 代码 | 日期 | 今日收盘 | 昨日收盘 | 涨幅 |")
    lines.append("|------|------|------|----------|----------|------|")

    for s in stocks:
        symbol = s['symbol']
        name = s['name']

        # 优先从 JSON 读取，缺失字段从缓存补全
        close = s['close']
        pre_close = s.get('pre_close')
        if pre_close is None:
            cached = _read_stock_cache(symbol, cache_dir)
            if cached:
                cached_date, close, pre_close, _ = cached

        if pre_close is not None and abs(close - pre_close) > 0.001:
            pct = (close - pre_close) / pre_close * 100
            arrow = '📈' if pct > 0 else '📉'
            lines.append(
                f"| {name} | {symbol} | {latest_date} "
                f"| {close:.2f} | {pre_close:.2f} "
                f"| {arrow}{pct:+.2f}% |"
            )
        else:
            lines.append(
                f"| {name} | {symbol} | {latest_date} "
                f"| {close:.2f} | — | (缓存缺失) |"
            )

    return '\n'.join(lines)


# ──────────────────────────────────────────────
# 主流程：扫描所有股票
# ──────────────────────────────────────────────

def scan_stocks(lookback=120, min_score=60, market_state='sideways'):
    """
    扫描全市场股票，筛选突破上涨通道的个股

    参数:
        lookback: 数据回溯天数
        min_score: 最低评分（默认60）
        market_state: 大盘状态，影响评分加权
    """
    symbols = get_daily_symbols()
    logger = czsc_logger()
    logger.info(f"开始扫描突破上涨通道，共{len(symbols)}只股票...")
    logger.info(f"大盘状态: {market_state}")

    results = []
    stock_count = 0
    start_ts = time.time()

    for symbol in symbols:
        stock_count += 1
        if stock_count % 100 == 0:
            elapsed = time.time() - start_ts
            fps = stock_count / elapsed if elapsed > 0 else 0
            logger.info(f"进度 {stock_count}/{len(symbols)} | "
                        f"{fps:.0f}只/秒 | "
                        f"已入选{sum(1 for r in results if r and r['score'] >= min_score)}只")

        try:
            start_date = '2024-01-01'
            end_date = get_latest_trade_date()
            df = get_stock_pd(symbol, start_date, end_date, 'd')
            if df is None or len(df) < max(lookback, 100):
                results.append(None)
                continue

            financial = get_financial_growth(symbol)

            # 财务数据存在但不达标（营收增长≤0或净利增长<20%）则直接剔除
            if financial is not None and (financial['revenue_yoy'] <= 0 or financial['profit_yoy'] < 20):
                results.append(None)
                continue

            r = score_channel_breakout(df, lookback=lookback, market_state=market_state, financial=financial)
            if r is None:
                results.append(None)
                continue

            r['symbol'] = symbol
            r['name'] = get_symbols_name(symbol)
            r['revenue_yoy'] = financial['revenue_yoy'] if financial else None
            r['profit_yoy'] = financial['profit_yoy'] if financial else None
            # 5日涨幅
            c_arr = df['close'].values
            if len(c_arr) >= 6:
                r['pct_5d'] = (c_arr[-1] - c_arr[-6]) / c_arr[-6] * 100
            else:
                r['pct_5d'] = 0
            results.append(r)

            # 动态打印入选结果
            if r['score'] >= min_score:
                reg_break = '突破上轨' if r['close'] > r['regression']['up'] else '通道内'
                logger.info(f"  ✓ {symbol} {r['name']} "
                            f"评分{r['score']} "
                            f"收盘{r['close']:.2f} "
                            f"{reg_break} "
                            f"量比{r['volume']['ratio_v_ma5']:.1f}x")

        except Exception as e:
            logger.error(f"处理{symbol}失败: {e}")
            results.append(None)

    elapsed = time.time() - start_ts
    logger.info(f"\n扫描完成！耗时{elapsed:.0f}秒，"
                f"共{len(symbols)}只，"
                f"入选{sum(1 for r in results if r and r['score'] >= min_score)}只")
    return results


def main():
    """入口"""
    print("=" * 60)
    print("突破上涨通道选股系统（pytdx 财务数据）")
    print("=" * 60)
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
        
    # 基于已有 JSON 输出昨日涨跌幅表格
    prev_json = os.path.join(get_data_dir(), '突破上涨通道.json')
    print(format_daily_change_from_json(prev_json))
    
    # 先判断大盘环境
    market_state = check_market_environment()
    print(f"大盘环境判断: {market_state}")

    min_score = 60
    if market_state == 'downtrend':
        min_score = 75
        print("⚠️ 大盘处于下降趋势，评分阈值提高至75")
    elif market_state == 'uptrend':
        print("✅ 大盘处于上升趋势")
    else:
        print("➖ 大盘处于震荡趋势")

    results = scan_stocks(lookback=120, min_score=min_score, market_state=market_state)
    
    output_path = os.path.join(get_data_dir(), '突破上涨通道.json')

    # 保存JSON
    save_results(results, output_path, market_state=market_state)
    print(f"\n结果已保存至: {output_path}")

    # 输出股票代码txt（纯代码，、分隔）
    passed = [r for r in results if r and r['score'] >= min_score]
    passed.sort(key=lambda x: x['score'], reverse=True)
    codes = [r['symbol'].split('.')[-1] for r in passed]
    txt_path = os.path.join(get_data_dir(), '突破上涨通道.txt')
    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write('、'.join(codes))
    print(f"股票代码已保存至: {txt_path} ({len(codes)}只)")

    # 控制台格式化输出（主表）
    output = format_result(results)
    print(output)

    # 保存 Markdown 表格（可直接复制到公众号）
    md_path = os.path.join(get_data_dir(), '突破上涨通道_表格.md')
    format_result_markdown(results, md_out=md_path)
    print(f"\nMarkdown 表格已保存至: {md_path}")

    # 今日涨跌幅明细表
    change_table = format_daily_change_table(results)
    print(change_table)

    print(f"\n{'=' * 90}")
    print(f"详细信号说明：")
    print(f"  突破回上轨: ✓=突破上轨  △=中轨上方  (空)=通道下方")
    print(f"  新高%: 正数=创N日新高 负数=新低")
    print(f"  量比: 当日成交量/MA5")
    print(f"  ATR止损: 基于波动率的动态止损位")
    print(f"  评分≥{min_score}为入选（根据大盘状态动态调整）")
    print(f"{'=' * 90}")
    bs.logout()

if __name__ == '__main__':
    main()
