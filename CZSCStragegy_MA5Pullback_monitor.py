#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回踩5日均线 一夜持股策略 - 盘中买入/卖出预警（与新版回测 CZSCStragegy_MA5Pullback.py 同步）

策略描述：
  1) 连续3天上涨，且三天的最低点、最高点依次抬高（低点抬升、高点抬升）
     同时成交量和价格一样在三天内逐步放大
  2) 第4天盘中回踩5日线时买入（挂单5日线，回踩不破位）
  3) 买入后第二天以最高价卖出（次日卖出口径下执行）
  4) 过滤条件（与回测一致）：
     - 信号日收盘价 > 60日均线（中期趋势向上）
     - 大盘环境过滤：上证指数收盘 > 20日均线（可选：指数是否也在5日线上方）

预警逻辑（每次运行扫描一遍，与 golden_stock_monitor.py 相同，适合 cron 每5分钟调度）：
  [买入预警] 观察池内个股当日实时回踩5日线时，提示按5日线挂限价单买入
  [卖出预警] 前一交易日发出买入信号的个股（今日为持有卖出日）：
      a) 开盘卖出提醒（09:15~10:30，或首次检测）
      b) 盘中冲高提醒（创当日新高且达到最小盈利阈值）
      c) 尾盘卖出提醒（14:40 之后仍未卖出）

数据源：
  - 观察池：data/.cache/*.csv 日线缓存（3连阳+低点/高点抬升+成交量放大）作为预筛
  - 实时确认：通达信日K（含当日进行中的K线，前复权）实时校验全部条件
"""
import os
import sys
import json
import time
import numpy as np
import pandas as pd

from datetime import datetime, timedelta

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from czsc_daily_util import (
    get_data_dir,
    get_symbols_name,
    get_stock_pd_tdx,
    get_latest_trade_date,
    read_json,
    write_json,
    czsc_logger,
)
from lib.email_sender_163 import send_html_email_163

# ---------------------------------------------------------------------------
# 参数（与回测 CZSCStragegy_MA5Pullback.py 保持一致）
# ---------------------------------------------------------------------------
PARAMS = dict(
    up_days=3,            # 连续上涨天数
    require_dip_day=True, # 第4天为回调日：开盘价不高于昨收（容忍微涨）
    dip_max=0.01,         # 开盘价相对昨收最大容忍涨幅
    touch_ratio=0.02,     # 回踩幅度：最多跌破5日线2%；开盘不得低于5日线2%
    buy_mode='ma5',       # 买入价固定为5日线
    sell_min_profit=0.005,# 盘中冲高提醒的最小盈利（相对买入价）
    history_days=120,     # 实时拉取的日历天数（需保证信号日之前至少60个交易日）

    # ===== 大盘过滤（与回测一致） =====
    use_market_filter=True,   # 是否启用大盘过滤
    market_index='sh.000001', # 上证指数
    market_ma_period=20,      # 大盘均线周期
    market_min_ma5=False,     # 是否要求大盘也在5日线上方
)

# 中期趋势均线周期（与回测一致，硬编码60）
MA60_PERIOD = 60

# 日志
logger = czsc_logger()

# 通知记录文件（当日去重）
NOTIFICATION_LOG_FILE = os.path.join(get_data_dir(), 'ma5_pullback_monitor_log.json')

# 邮件接收人
EMAIL_RECEIVER = "13311566853@163.com"


# ---------------------------------------------------------------------------
# 实时数据
# ---------------------------------------------------------------------------
def get_live_df(symbol, today):
    """获取最近 history_days 天的日K（含今日进行中的实时K线，前复权），升序"""
    start = (datetime.now() - timedelta(days=PARAMS['history_days'])).strftime('%Y-%m-%d')
    df = get_stock_pd_tdx(symbol, start, today, 'd')
    if df is None or len(df) == 0:
        return None
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = df['date'].astype(str)
    return df


def get_index_df(today):
    """获取最近 history_days 天的大盘指数日K（含今日进行中K线）"""
    start = (datetime.now() - timedelta(days=PARAMS['history_days'])).strftime('%Y-%m-%d')
    df = get_stock_pd_tdx(PARAMS['market_index'], start, today, 'd', True)
    if df is None or len(df) == 0:
        return None
    df = df.dropna(subset=['open', 'high', 'low', 'close'])
    df = df.sort_values('date').reset_index(drop=True)
    df['date'] = df['date'].astype(str)
    return df


def market_ok_live(index_df, ref_date):
    """
    大盘环境过滤（与回测 check_market_condition 一致）：
    以 ref_date（须为已收盘交易日）当日指数收盘 > 前 market_ma_period 日均线
    大盘数据缺失时跳过过滤（返回True），避免误伤
    """
    if not PARAMS['use_market_filter'] or index_df is None or len(index_df) == 0:
        return True
    dates = index_df['date'].astype(str).tolist()
    idx = [k for k, x in enumerate(dates) if x == ref_date]
    if not idx:
        return True  # 无匹配日期，跳过过滤
    i = idx[-1]
    close = index_df['close'].to_numpy(dtype=float)
    period = PARAMS['market_ma_period']
    if i < period:
        return True
    ma = float(np.mean(close[i - period:i]))
    if close[i] <= ma:
        return False
    if PARAMS['market_min_ma5'] and i >= 5:
        ma5 = float(np.mean(close[i - 5:i]))
        if close[i] <= ma5:
            return False
    return True


# ---------------------------------------------------------------------------
# 信号判定（与回测 compute_signals 完全对应）
# ---------------------------------------------------------------------------
def signal_at(i, open_, high, low, close, volume, market_ok=True):
    """判断第 i 条K线当日是否触发"回踩5日线买入"信号，返回买入价或 None"""
    up = PARAMS['up_days']
    touch = PARAMS['touch_ratio']
    dip_max = PARAMS['dip_max']

    if i < up + 5:
        return None

    ma5 = float(np.mean(close[i - 5:i]))

    # 1) 连续3天上涨
    for j in range(up):
        if not close[i - up + j] > close[i - up + j - 1]:
            return None

    # 2) 三天成交量逐步放大（与回测 ok_volume 一致）
    for j in range(1, up):
        if not volume[i - up + j] > volume[i - up + j - 1]:
            return None

    # 3) 三天最低点、最高点依次抬高
    for j in range(1, up):
        if not (low[i - up + j] > low[i - up + j - 1] and high[i - up + j] > high[i - up + j - 1]):
            return None

    # 4) 第4天为回调日：开盘价不高于昨收（容忍微涨）
    if PARAMS['require_dip_day'] and open_[i] > close[i - 1] * (1 + dip_max):
        return None

    # 5) 盘中回踩5日线：最低价已触及（允许小幅刺破），开盘未破位
    if low[i] > ma5 * (1 + touch):
        return None
    if open_[i] < ma5 * (1 - touch):
        return None

    # 6) 收盘价 > 60日均线（中期趋势向上）
    if i < MA60_PERIOD:
        return None
    ma60 = float(np.mean(close[i - MA60_PERIOD:i]))
    if close[i] < ma60:
        return None

    # 7) 大盘环境过滤
    if not market_ok:
        return None

    # 买入价 = 5日线（挂限价单）
    return ma5


# ---------------------------------------------------------------------------
# 观察池构建（日线缓存预筛：3连阳+低点/高点抬升+成交量放大）
# ---------------------------------------------------------------------------
def _has_three_up(df, cat_date):
    """缓存里 cat_date 当日是否满足：3天连续上涨（含成交量放大）且低点/高点依次抬高（以 cat_date 为第3根阳线，模式截止 cat_date 当日）"""
    dates = df['date'].astype(str).tolist()
    idx_arr = [i for i, x in enumerate(dates) if x == cat_date]
    if len(idx_arr) == 0:
        return False
    i = idx_arr[-1]
    up = PARAMS['up_days']
    if i < up + 1:
        return False
    close = df['close'].to_numpy(dtype=float)
    low = df['low'].to_numpy(dtype=float)
    high = df['high'].to_numpy(dtype=float)
    volume = df['volume'].to_numpy(dtype=float)
    for j in range(up):
        if not close[i - up + 1 + j] > close[i - up + j]:
            return False
    for j in range(1, up):
        if not (low[i - up + 1 + j] > low[i - up + j] and high[i - up + 1 + j] > high[i - up + j]):
            return False
    for j in range(1, up):
        if not volume[i - up + 1 + j] > volume[i - up + j]:
            return False
    return True


def build_watchlist(last_completed, second_last):
    """
    返回 (buy_candidates, sell_candidates)
      buy_candidates: 3连阳以 last_completed 为第3天 → 今日可能回踩（买入预警候选）
      sell_candidates: 3连阳以 second_last 为第3天 → 昨日可能触发信号 → 今日卖出（卖出预警候选）
    """
    cache_dir = os.path.join(get_data_dir(), '.cache')
    if not os.path.isdir(cache_dir):
        logger.error(f'缓存目录不存在: {cache_dir}')
        return set(), set()

    buy_candidates, sell_candidates = set(), set()

    files = [f for f in os.listdir(cache_dir) if f.endswith('.csv') and not f.startswith('sh.000001')]
    logger.info(f'缓存文件数: {len(files)}，last_completed={last_completed}, second_last={second_last}')

    for f in files:
        symbol = f.split('_')[0]
        try:
            df = pd.read_csv(os.path.join(cache_dir, f))
            if df.empty:
                continue
            df = df.dropna(subset=['open', 'high', 'low', 'close'])
            if df['date'].astype(str).iloc[-1] != last_completed:
                # 缓存最后日期不是 last_completed（缓存未更新），预筛不可信，跳过
                continue
            if _has_three_up(df, last_completed):
                buy_candidates.add(symbol)
            if _has_three_up(df, second_last):
                sell_candidates.add(symbol)
        except Exception as e:
            logger.debug(f'解析缓存 {f} 失败: {e}')
            continue

    logger.info(f'观察池: 买入候选 {len(buy_candidates)} 只，卖出候选 {len(sell_candidates)} 只')
    with open(os.path.join(get_data_dir(), f'ma5_watchlist_{last_completed}.json'), 'w', encoding='utf-8') as fp:
        json.dump({
            'date': last_completed,
            'buy_candidates': list(buy_candidates),
            'sell_candidates': list(sell_candidates),
        }, fp, ensure_ascii=False, indent=2)
    return buy_candidates, sell_candidates


# ---------------------------------------------------------------------------
# 通知记录（参照 golden_stock_monitor.py，当日去重）
# ---------------------------------------------------------------------------
def load_notification_log():
    today = datetime.now().strftime('%Y-%m-%d')
    if os.path.exists(NOTIFICATION_LOG_FILE):
        all_data = read_json(NOTIFICATION_LOG_FILE) or {}
        today_data = {k: v for k, v in all_data.items()
                      if isinstance(v, dict) and v.get('last_notify_date') == today}
        if len(today_data) != len(all_data):
            write_json(today_data, NOTIFICATION_LOG_FILE)
        return today_data
    return {}


def should_notify_today(key, log_data):
    today = datetime.now().strftime('%Y-%m-%d')
    rec = log_data.get(key)
    return not (rec and rec.get('last_notify_date') == today)


def record_alert(log_data, key, extra=None):
    today = datetime.now().strftime('%Y-%m-%d')
    record = {'last_notify_date': today,
              'last_notify_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    if extra:
        record.update(extra)
    log_data[key] = record
    write_json(log_data, NOTIFICATION_LOG_FILE)


# ---------------------------------------------------------------------------
# 预警处理
# ---------------------------------------------------------------------------
def save_alert_archive(alert_items):
    if not alert_items:
        return
    today = datetime.now().strftime('%Y-%m-%d')
    fp = os.path.join(get_data_dir(), f'ma5_alerts_{today}.json')
    old = read_json(fp)
    old = old if isinstance(old, dict) else {}
    old['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    items = old.get('items', [])
    items.extend(alert_items)
    old['items'] = items
    write_json(old, fp)


def send_alert_email(alert_items):
    if not alert_items:
        return
    rows = ''
    for a in alert_items:
        color = '#a11' if a['type'] == '买入' else '#1a5'
        rows += f'''
        <tr>
            <td style="padding-left:1em;text-align:left;background-color:#F3F3F3;height:26px;">
                <font color="{color}">{a['type']}</font>
            </td>
            <td style="padding-left:1em;text-align:left;background-color:#F3F3F3;height:26px;">
                {a['name']}&nbsp;({a['symbol']})
            </td>
            <td style="padding-left:1em;text-align:left;background-color:#F3F3F3;height:26px;">{a['msg']}</td>
        </tr>'''

    html_content = f'''
    <html>
    <head><meta charset="utf-8"></head>
    <body>
        <h2>回踩5日均线 一夜持股 预警</h2>
        <p>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 监测到以下信号：</p>
        <table style="border-collapse:collapse;">
            <tr>
                <th style="text-align:left;padding:0 8px;">类型</th>
                <th style="text-align:left;padding:0 8px;">股票</th>
                <th style="text-align:left;padding:0 8px;">说明</th>
            </tr>
            {rows}
        </table>
        <p>（观察池由昨日日线缓存预筛，信号由通达信实时K线确认）</p>
    </body>
    </html>'''
    try:
        subject = f"回踩5日线预警({len(alert_items)}条) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        send_html_email_163("13311566853", EMAIL_RECEIVER, subject, html_content)
        logger.info(f"已发送预警邮件，包含 {len(alert_items)} 条")
    except Exception as e:
        logger.error(f"发送邮件失败: {e}")


def process_buy_alerts(buy_candidates, today, now, market_ok=True):
    """盘中回踩5日线 → 买入预警"""
    alerts, log = [], load_notification_log()
    for symbol in sorted(buy_candidates):
        if not should_notify_today(f'{symbol}|buy', log):
            continue
        df = get_live_df(symbol, today)
        if df is None or len(df) < PARAMS['up_days'] + 5:
            continue
        dates = df['date'].tolist()
        if dates[-1] != today:
            continue  # 今日尚无实时K线（未开盘）
        i = len(df) - 1
        ma5 = signal_at(i, df['open'].to_numpy(dtype=float),
                        df['high'].to_numpy(dtype=float),
                        df['low'].to_numpy(dtype=float),
                        df['close'].to_numpy(dtype=float),
                        df['volume'].to_numpy(dtype=float),
                        market_ok)
        if ma5 is None:
            continue
        name = get_symbols_name(symbol)
        cur = float(df['close'].iloc[i])
        low = float(df['low'].iloc[i])
        msg = f'盘中回踩5日线 {ma5:.2f}，可挂限价单买入（现价 {cur:.2f}，最低 {low:.2f}）'
        logger.info(f'【买入预警】{name}({symbol}) {msg}')
        alert = {'type': '买入', 'symbol': symbol, 'name': name, 'msg': msg,
                 'time': now.strftime('%H:%M:%S')}
        alerts.append(alert)
        record_alert(log, f'{symbol}|buy', {'buy_price': round(ma5, 2)})
        time.sleep(0.2)
    return alerts


def process_sell_alerts(sell_candidates, today, now, market_ok=True):
    """昨日买入信号 → 今日卖出预警（次日最高价卖出）"""
    alerts, log = [], load_notification_log()
    hour = now.hour * 100 + now.minute

    for symbol in sorted(sell_candidates):
        df = get_live_df(symbol, today)
        if df is None or len(df) < PARAMS['up_days'] + 5:
            continue
        dates = df['date'].tolist()
        if dates[-1] != today:
            continue  # 今日尚无实时K线
        completed = [i for i, x in enumerate(dates) if x < today]
        if not completed:
            continue
        i = completed[-1]
        ma5 = signal_at(i, df['open'].to_numpy(dtype=float),
                        df['high'].to_numpy(dtype=float),
                        df['low'].to_numpy(dtype=float),
                        df['close'].to_numpy(dtype=float),
                        df['volume'].to_numpy(dtype=float),
                        market_ok)
        if ma5 is None:
            continue

        name = get_symbols_name(symbol)
        buy_price = ma5
        cur = float(df['close'].iloc[-1])
        cur_high = float(df['high'].iloc[-1])
        profit = (cur / buy_price - 1) * 100
        profit_high = (cur_high / buy_price - 1) * 100

        # a) 开盘/当日卖出提醒
        if hour <= 1030:
            if should_notify_today(f'{symbol}|sell_open', log):
                msg = f'昨回踩信号({dates[i]})，今日持有到期需卖出；买价 {buy_price:.2f}，现价 {cur:.2f}（{profit:+.2f}%）'
                logger.info(f'【卖出预警-开盘】{name}({symbol}) {msg}')
                alerts.append({'type': '卖出', 'symbol': symbol, 'name': name, 'msg': msg,
                               'time': now.strftime('%H:%M:%S')})
                record_alert(log, f'{symbol}|sell_open')
        elif should_notify_today(f'{symbol}|sell_day', log):
            # 错过早盘提醒，补一次当日卖出提醒
            msg = f'昨回踩信号({dates[i]})，今日需卖出；买价 {buy_price:.2f}，现价 {cur:.2f}（{profit:+.2f}%）'
            logger.info(f'【卖出预警】{name}({symbol}) {msg}')
            alerts.append({'type': '卖出', 'symbol': symbol, 'name': name, 'msg': msg,
                           'time': now.strftime('%H:%M:%S')})
            record_alert(log, f'{symbol}|sell_day')

        # b) 盘中冲高提醒（创当日新高且达最小盈利）
        if profit_high >= PARAMS['sell_min_profit'] * 100:
            key = f'{symbol}|sell_high|{cur_high:.2f}'
            if should_notify_today(key, log):
                msg = f'盘中冲高 {cur_high:.2f}（{profit_high:+.2f}%），可考虑高点卖出'
                logger.info(f'【卖出预警-冲高】{name}({symbol}) {msg}')
                alerts.append({'type': '卖出', 'symbol': symbol, 'name': name, 'msg': msg,
                               'time': now.strftime('%H:%M:%S')})
                record_alert(log, key)

        # c) 尾盘卖出提醒
        if hour >= 1440 and should_notify_today(f'{symbol}|sell_close', log):
            msg = f'临近收盘，若尚未卖出建议尾盘现价卖出（现价 {cur:.2f}，{profit:+.2f}%）'
            logger.info(f'【卖出预警-尾盘】{name}({symbol}) {msg}')
            alerts.append({'type': '卖出', 'symbol': symbol, 'name': name, 'msg': msg,
                           'time': now.strftime('%H:%M:%S')})
            record_alert(log, f'{symbol}|sell_close')

        time.sleep(0.2)
    return alerts


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def monitor():
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    if today != get_latest_trade_date():
        logger.info(f'今天({today})不是交易日，最近交易日为 {get_latest_trade_date()}，程序退出')
        return

    # 指数日K（含今日进行中的K线）：既用于求已完成交易日，也用于大盘过滤
    idx_df = get_index_df(today)

    # 求已完成的最近交易日及倒数第二交易日（剔除今日进行中的K线）
    idx_dates = [str(x) for x in idx_df['date'].tolist()] if idx_df is not None else []
    completed = sorted([x for x in idx_dates if x < today])
    if len(completed) < 2:
        logger.error('无法取得最近两个已完成交易日')
        return
    last_completed = completed[-1]
    second_last = completed[-2]
    logger.info(f'今日={today}，最近已完成交易日={last_completed}，前一个={second_last}')

    # 大盘环境（以最近已完成交易日为基准；买入当日盘中以昨收为准，收盘后才按当日判定）
    market_ok = market_ok_live(idx_df, last_completed)
    logger.info(f'大盘过滤: {"通过" if market_ok else "未通过（指数<=MA%d）"}'
                % PARAMS['market_ma_period'])

    # 构建观察池（缓存预筛，每日一次）
    buy_candidates, sell_candidates = build_watchlist(last_completed, second_last)

    alerts = []
    alerts += process_buy_alerts(buy_candidates, today, now, market_ok)
    alerts += process_sell_alerts(sell_candidates, today, now, market_ok)

    save_alert_archive(alerts)
    send_alert_email(alerts)
    logger.info(f'本次扫描完成，共 {len(alerts)} 条预警')


if __name__ == '__main__':
    import baostock as bs
    try:
        lg = bs.login()
        monitor()
    finally:
        bs.logout()