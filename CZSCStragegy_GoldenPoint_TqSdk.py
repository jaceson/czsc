# coding: utf-8
"""全市场期货主力黄金点回测；仅 TqBacktest + TqSim，不连接实盘账户。

日线黄金点做多，下一交易日执行；下一交易日低于上一笔买入价可等预算加仓。
默认固定保证金预算，整数手向下取整；每次实际成交后重计持有交易日。
开盘退出优先于加仓，收盘条件在下一交易日执行，不假设能成交在历史收盘价。
主力换月平旧仓，等待后续信号开新仓；到期未平仓按 TqSim 权益估值。
用法及期货/股票口径差异见 docs/golden_point_tqsdk.md。
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
try:
    from tqsdk import TqApi, TqAuth, TqBacktest, TqSim, BacktestFinished
except ImportError as exc:  # 允许离线工具函数和测试继续导入模块
    TqApi = TqAuth = TqBacktest = TqSim = BacktestFinished = None
    _TQSDK_IMPORT_ERROR = exc
else:
    _TQSDK_IMPORT_ERROR = None

import numpy as np
import pandas as pd

EXCHANGES = ('SHFE', 'DCE', 'CZCE', 'CFFEX', 'INE', 'GFEX')


@dataclass
class Config:
    start: str = '2024-01-01'
    end: str = '2026-01-01'
    init_capital: float = 1000000.
    position_amount: float = 40000.
    budget_mode: str = 'margin'
    hold_days: int = 10
    take_profit: float = .10
    stop_loss: float = .03
    history_length: int = 3000
    golden_threshold: float = 1.7
    golden_klines: int = 10
    golden_max_ratio: float = 1.1
    golden_min_angle: float = 20.
    golden_close_ratio: float = 1.1
    output: str = 'data/golden_point_tqsdk'

    def validate(self):
        if date.fromisoformat(self.start) >= date.fromisoformat(self.end):
            raise ValueError('开始日期必须早于结束日期')
        if not all(math.isfinite(x) and x > 0 for x in
                   (self.init_capital, self.position_amount, self.take_profit, self.stop_loss)):
            raise ValueError('资金、预算及止盈止损比例须为有限正数')
        if self.stop_loss >= 1 or self.hold_days < 1 or not 60 <= self.history_length <= 10000:
            raise ValueError('止损比例须小于 1，持有天数须为正，历史长度须在 60~10000')
        if self.budget_mode not in ('margin', 'notional'):
            raise ValueError('budget_mode 仅支持 margin 或 notional')


def ns_date(value):
    return pd.Timestamp(int(value), unit='ns', tz='UTC').tz_convert('Asia/Shanghai').strftime('%Y-%m-%d')


def trading_date(value):
    """与 TqBacktest 的 18 点换交易日、周末顺延规则一致，使用北京时间。"""
    dt = pd.Timestamp(value)
    if dt.tzinfo is not None:
        dt = dt.tz_convert('Asia/Shanghai').tz_localize(None)
    day = dt.normalize() + pd.Timedelta(days=int(dt.hour >= 18))
    while day.weekday() >= 5:
        day += pd.Timedelta(days=1)
    return day.strftime('%Y-%m-%d')


def lot_size(budget, mode, price, multiple, margin, commission, available):
    """返回 (整数手数, 所需保证金及开仓费)；资金不足不缩量。"""
    if not all(math.isfinite(x) for x in (budget, price, multiple, margin, commission, available)):
        return 0, 0.
    if min(budget, price, multiple, margin) <= 0 or commission < 0:
        return 0, 0.
    per_lot = (margin if mode == 'margin' else price * multiple) + commission
    lots = math.floor(budget / per_lot)
    required = lots * (margin + commission)
    if lots < 1 or available + 1e-8 < required:
        return 0, 0.
    return lots, required


def close_offsets(symbol, today, history):
    if symbol.split('.')[0] in ('SHFE', 'INE'):
        return [(offset, n) for offset, n in [('CLOSE', history), ('CLOSETODAY', today)] if n > 0]
    return [('CLOSE', today + history)] if today + history > 0 else []


def daily_frame(serial):
    frame = serial.loc[serial['datetime'] > 0].copy()
    frame = frame.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
    frame = frame[(frame[['open', 'high', 'low', 'close']] > 0).all(axis=1)]
    frame['date'] = frame['datetime'].map(ns_date)
    # 信号不使用成交额；RawBar 的 amount 为必填字段，未知时明确填 0。
    frame['amount'] = 0.
    return frame[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']].reset_index(drop=True)


def golden_signal(symbol, completed, cfg):
    """直接调用股票版使用的同一黄金点函数，只传已经结束的日线。"""
    if len(completed) < 60:
        return False
    import czsc_daily_util as util
    old_write, old_disabled = util.write_json, util.logger.disabled
    util.write_json = lambda *args, **kwargs: None
    util.logger.disabled = True
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return bool(util.is_golden_point(
                symbol, completed.copy(), threshold=cfg.golden_threshold,
                klines=cfg.golden_klines, max_ratio=cfg.golden_max_ratio,
                min_angle=cfg.golden_min_angle, close_ratio=cfg.golden_close_ratio))
    finally:
        util.write_json, util.logger.disabled = old_write, old_disabled
        util.stock_czsc_cache.clear()
        util.stock_bars_cache.clear()


@dataclass
class Campaign:
    symbol: str
    multiple: float
    entries: list = field(default_factory=list)
    lots: int = 0
    entry_value: float = 0.
    exit_value: float = 0.
    fees: float = 0.
    margin_invested: float = 0.
    peak: float = 0.
    due_id: int = 0
    observations: list = field(default_factory=list)

    @property
    def average(self):
        return self.entry_value / sum(e['lots'] for e in self.entries) / self.multiple

    def buy(self, price, lots, day_id, day, margin, fees, hold_days):
        self.entries.append({'date': day, 'day_id': day_id, 'price': price, 'lots': lots,
                             'margin': lots * margin, 'commission': fees})
        self.lots += lots
        self.entry_value += price * lots * self.multiple
        self.fees += fees
        self.margin_invested += lots * margin
        self.due_id = day_id + hold_days
        self.peak = self.average

    def reason(self, price, cfg):
        if price <= self.average * (1 - cfg.stop_loss):
            return '止损'
        if price >= self.average * (1 + cfg.take_profit):
            return '止盈'
        if self.peak > self.average and price <= self.peak * (1 - cfg.stop_loss):
            return '回撤止损'
        return None

    def observe(self, price, day):
        self.observations.append((day, 0, (price / self.average - 1) * 100))
        self.peak = max(self.peak, price)

    def can_add(self, day_id, price):
        last = self.entries[-1]
        return day_id == last['day_id'] + 1 and price < last['price']

    def finish(self, day, reason):
        gross = self.exit_value - self.entry_value
        pnl = gross - self.fees
        return {'symbol': self.symbol, 'entry_date': self.entries[0]['date'], 'exit_date': day,
                'entry_price': self.average, 'lots': sum(e['lots'] for e in self.entries),
                'entry_value': self.entry_value, 'exit_value': self.exit_value,
                'gross_pnl': gross, 'commission': self.fees, 'pnl': pnl,
                'ret': 100 * pnl / self.margin_invested, 'margin_invested': self.margin_invested,
                'add_count': len(self.entries) - 1, 'kind': reason,
                'entries': self.entries, 'observations': self.observations,
                'ever_profitable': any(r > 0 for _, _, r in self.observations) or pnl > 0}


@dataclass
class Product:
    continuous: str
    quote: object
    daily: object
    campaign: Campaign | None = None
    pending: dict | None = None
    closing_reason: str = ''
    handled_id: int = -1
    last_start_id: int = -1000000
    signal_errors: int = 0


class FuturesBacktest:
    def __init__(self, api, sim, cfg, symbols=None, signal_func=golden_signal):
        self.api, self.sim, self.cfg, self.signal_func = api, sim, cfg, signal_func
        self.account = api.get_account()
        self.products = []
        self.contracts = {}
        self.records, self.fills, self.skips = [], [], []
        self.curve = {}
        self.reserved = 0.
        # 主连自身的交易所标识不同于其标的交易所；SDK 对单个交易所字符串
        # 有特殊处理，但传交易所列表会直接发送服务端过滤，导致主连查询为空。
        # 先取全部主连，再从 KQ.m@ 后的真实交易所代码筛选。
        universe = list(symbols if symbols is not None else api.query_quotes(ins_class='CONT'))
        for symbol in sorted(set(universe)):
            if not symbol.startswith('KQ.m@') or symbol[5:].split('.')[0] not in EXCHANGES:
                if symbols is not None:
                    raise ValueError(f'请使用国内期货主力连续合约，例如 KQ.m@SHFE.rb：{symbol}')
                continue
            self.products.append(Product(symbol, api.get_quote(symbol),
                                         api.get_kline_serial(symbol, 86400, data_length=cfg.history_length)))
        if not self.products:
            raise ValueError(
                f'未发现可用的国内期货主力品种：合约列表返回 {len(universe)} 项，'
                f'国内主连筛选后为 0 项。返回样例：{universe[:5]}。'
                '请检查回测区间与行情权限，或使用 --symbols KQ.m@SHFE.rb 指定品种验证。')
        print(f'发现 {len(self.products)} 个期货品种；做多；每次 {cfg.position_amount:,.2f} 元 {cfg.budget_mode} 预算')

    def contract(self, symbol):
        if symbol not in self.contracts:
            self.contracts[symbol] = (self.api.get_quote(symbol),
                                      self.api.get_kline_serial(symbol, 86400, data_length=3),
                                      self.api.get_position(symbol))
        return self.contracts[symbol]

    def skip(self, product, day, reason):
        self.skips.append({'date': day, 'continuous': product.continuous, 'reason': reason})

    def submit_buy(self, product, symbol, day_id, day):
        quote, _, _ = self.contract(symbol)
        price, multiple = quote.ask_price1, quote.volume_multiple
        margin, commission = self.sim.get_margin(symbol), self.sim.get_commission(symbol)
        lots, required = lot_size(self.cfg.position_amount, self.cfg.budget_mode, price, multiple,
                                  margin, commission, self.account.available - self.reserved)
        if lots < 1:
            self.skip(product, day, '预算不足一手、可用保证金不足或合约费用未就绪')
            return
        minimum = max(1, int(quote.min_limit_order_volume))
        maximum = int(quote.max_limit_order_volume)
        if lots < minimum or (maximum > 0 and lots > maximum):
            self.skip(product, day, '手数超出合约限价委托范围')
            return
        order = self.api.insert_order(symbol, direction='BUY', offset='OPEN', volume=lots, limit_price=price)
        product.pending = {'action': 'buy', 'symbol': symbol, 'orders': [order], 'day_id': day_id,
                           'date': day, 'quote_time': quote.datetime, 'margin': margin,
                           'commission': commission, 'multiple': multiple, 'cancelled': False}
        self.reserved += required

    def submit_close(self, product):
        campaign = product.campaign
        quote, _, position = self.contract(campaign.symbol)
        if not math.isfinite(quote.bid_price1) or quote.bid_price1 <= 0:
            return
        orders = []
        maximum = max(1, int(quote.max_limit_order_volume))
        for offset, lots in close_offsets(campaign.symbol, position.pos_long_today, position.pos_long_his):
            # 连续加仓后的总手数可能超过单笔委托上限，平仓分单提交。
            while lots:
                chunk = min(lots, maximum)
                orders.append(self.api.insert_order(campaign.symbol, direction='SELL', offset=offset,
                                                    volume=chunk, limit_price=quote.bid_price1))
                lots -= chunk
        if orders:
            product.pending = {'action': 'sell', 'symbol': campaign.symbol, 'orders': orders,
                               'date': trading_date(quote.datetime), 'quote_time': quote.datetime,
                               'reason': product.closing_reason, 'commission': self.sim.get_commission(campaign.symbol),
                               'cancelled': False}

    def poll_orders(self, product):
        pending = product.pending
        if pending is None:
            return
        quote, _, _ = self.contract(pending['symbol'])
        if any(o.status != 'FINISHED' for o in pending['orders']):
            # 未在提交时成交的限价单，行情推进后撤销，避免次日意外成交重置计时。
            if quote.datetime != pending['quote_time'] and not pending['cancelled']:
                for order in pending['orders']:
                    if order.status != 'FINISHED':
                        self.api.cancel_order(order)
                pending['cancelled'] = True
            return
        trades = [t for o in pending['orders'] for t in o.trade_records.values()]
        lots = sum(t.volume for t in trades)
        if lots:
            price = sum(t.price * t.volume for t in trades) / lots
            fees = sum(t.get('commission', pending['commission'] * t.volume) for t in trades)
            last_ns = max(t.trade_date_time for t in trades)
            fill_day = trading_date(pd.Timestamp(last_ns, unit='ns', tz='UTC'))
            if pending['action'] == 'buy':
                if product.campaign is None:
                    product.campaign = Campaign(pending['symbol'], pending['multiple'])
                    product.last_start_id = pending['day_id']
                # 成交日期发生变化时使用此时的日线 id，不沿用原委托日期。
                day_id = pending['day_id'] if fill_day == pending['date'] else int(product.daily.iloc[-1]['id'])
                product.campaign.buy(price, lots, day_id, fill_day, pending['margin'], fees, self.cfg.hold_days)
            else:
                campaign = product.campaign
                campaign.exit_value += sum(t.price * t.volume * campaign.multiple for t in trades)
                campaign.fees += fees
                campaign.lots -= lots
                if campaign.lots == 0:
                    record = campaign.finish(fill_day, pending['reason'])
                    record['continuous'] = product.continuous
                    self.records.append(record)
                    print(f"{product.continuous} {campaign.symbol} {pending['reason']} 净盈亏:{record['pnl']:.2f} 加仓:{record['add_count']}")
                    product.campaign, product.closing_reason = None, ''
            for trade in trades:
                self.fills.append({'continuous': product.continuous, 'symbol': pending['symbol'],
                                   'datetime': str(pd.Timestamp(trade.trade_date_time, unit='ns', tz='UTC').tz_convert('Asia/Shanghai')),
                                   'order_id': trade.order_id, 'direction': trade.direction, 'offset': trade.offset,
                                   'price': trade.price, 'lots': trade.volume,
                                   'commission': trade.get('commission', pending['commission'] * trade.volume)})
        else:
            self.skip(product, pending['date'], '委托未成交：' + '; '.join(o.last_msg for o in pending['orders']))
            if (pending['action'] == 'buy' and product.campaign
                    and int(product.daily.iloc[-1]['id']) >= product.campaign.due_id):
                product.closing_reason = '到期开盘（加仓未成交）'
        product.pending = None

    def handle_product(self, product):
        self.poll_orders(product)
        if product.pending is not None:
            return
        if product.closing_reason and product.campaign:
            self.submit_close(product)
            return
        row = product.daily.iloc[-1]
        if row['datetime'] <= 0 or row['id'] < 0:
            return
        day_id, day = int(row['id']), ns_date(row['datetime'])
        if day_id == product.handled_id or day < self.cfg.start or day > self.cfg.end:
            return
        underlying = product.quote.underlying_symbol
        if not underlying:
            return
        campaign = product.campaign
        symbol = campaign.symbol if campaign else underlying
        quote, actual_daily, _ = self.contract(symbol)
        if not quote.datetime or trading_date(quote.datetime) != day:
            return  # 日线可能在 18 点创建，必须等到该合约当天实际交易行情。
        actual = actual_daily.iloc[-1]
        if actual['datetime'] <= 0 or ns_date(actual['datetime']) != day:
            return
        price = float(actual['open'])
        if not math.isfinite(price) or price <= 0:
            return
        product.handled_id = day_id
        if campaign:
            if symbol != underlying:
                product.closing_reason = '主力换月平旧仓'
            else:
                previous = actual_daily.iloc[-2]
                previous_day = ns_date(previous['datetime']) if previous['datetime'] > 0 else ''
                # 原策略买入当日不收盘全平，保持此口径；收盘条件确认后次日执行。
                if previous_day > campaign.entries[-1]['date'] and math.isfinite(previous['close']):
                    close_reason = campaign.reason(float(previous['close']), self.cfg)
                    campaign.observe(float(previous['close']), previous_day)
                    if close_reason:
                        product.closing_reason = '收盘' + close_reason + '（次日执行）'
                if not product.closing_reason:
                    product.closing_reason = ('开盘' + reason) if (reason := campaign.reason(price, self.cfg)) else ''
            if product.closing_reason:
                self.submit_close(product)
                return
            campaign.observe(price, day)
            if campaign.can_add(day_id, price):
                self.submit_buy(product, symbol, day_id, day)
                if product.pending:
                    return
            if day_id >= campaign.due_id:
                product.closing_reason = '到期开盘'
                self.submit_close(product)
            return
        if day_id - product.last_start_id <= self.cfg.hold_days:
            return
        # 始终排除当前尚未结束的日 K 线；不使用主连的价格计算真实持仓盈亏。
        completed = daily_frame(product.daily.iloc[:-1])
        try:
            signal = self.signal_func(product.continuous, completed, self.cfg)
        except (AttributeError, ValueError, IndexError, KeyError, AssertionError, TypeError, ZeroDivisionError) as exc:
            product.signal_errors += 1
            self.skip(product, day, f'信号计算失败：{type(exc).__name__}: {exc}')
            return
        if signal:
            self.submit_buy(product, underlying, day_id, day)

    def update(self):
        self.reserved = 0.
        # 确定顺序；实际持仓优先处理加仓和退出，然后处理空仓品种。
        for product in sorted(self.products, key=lambda p: (p.campaign is None, p.continuous)):
            self.handle_product(product)
        self.snapshot()

    def snapshot(self):
        stamps = [q.datetime for q, _, _ in self.contracts.values() if q.datetime]
        if not stamps:
            stamps = [p.quote.datetime for p in self.products if p.quote.datetime]
        if not stamps:
            return
        day = trading_date(max(stamps))
        if self.cfg.start <= day <= self.cfg.end:
            self.curve[day] = {'date': day, 'equity': float(self.account.balance),
                               'available': float(self.account.available), 'margin': float(self.account.margin),
                               'float_profit': float(self.account.float_profit),
                               'positions': sum(p.campaign is not None for p in self.products)}


def metrics(curve, records, initial):
    if not curve:
        return {}
    values = np.asarray([r['equity'] for r in curve], dtype=float)
    previous = np.r_[initial, values[:-1]]
    daily = np.divide(values - previous, previous, out=np.zeros_like(values), where=previous != 0)
    wins, losses = [r['pnl'] for r in records if r['pnl'] > 0], [r['pnl'] for r in records if r['pnl'] < 0]
    return {'total_return': values[-1] / initial - 1,
            'annual_return': (values[-1] / initial) ** (252 / len(values)) - 1 if values[-1] > 0 else np.nan,
            'sharpe': daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else np.nan,
            'max_drawdown': float(np.min(values / np.maximum.accumulate(np.r_[initial, values])[1:] - 1)),
            'profit_loss_ratio': np.mean(wins) / abs(np.mean(losses)) if wins and losses else np.nan,
            'profit_factor': sum(wins) / abs(sum(losses)) if losses else np.nan,
            'win_rate': len(wins) / (len(wins) + len(losses)) if wins or losses else np.nan,
            'trade_count': len(records),
            'positive_horizon_rate': np.mean([r['ever_profitable'] for r in records]) if records else np.nan,
            'avg_add_count': np.mean([r['add_count'] for r in records]) if records else np.nan,
            'max_add_count': max((r['add_count'] for r in records), default=np.nan)}


def save_report(runner, status):
    out = Path(runner.cfg.output)
    out.mkdir(parents=True, exist_ok=True)
    curve = [runner.curve[d] for d in sorted(runner.curve)]
    result = metrics(curve, runner.records, runner.cfg.init_capital)
    pd.DataFrame(curve, columns=['date', 'equity', 'available', 'margin', 'float_profit', 'positions']).to_csv(out / 'equity.csv', index=False)
    records = [{k: v for k, v in r.items() if k not in ('entries', 'observations')} for r in runner.records]
    pd.DataFrame(records, columns=['continuous', 'symbol', 'entry_date', 'exit_date', 'entry_price',
                                   'lots', 'entry_value', 'exit_value', 'gross_pnl', 'commission', 'pnl',
                                   'ret', 'margin_invested', 'add_count', 'kind', 'ever_profitable']).to_csv(out / 'trades.csv', index=False)
    pd.DataFrame(runner.fills, columns=['continuous', 'symbol', 'datetime', 'order_id', 'direction',
                                       'offset', 'price', 'lots', 'commission']).to_csv(out / 'fills.csv', index=False)
    pd.DataFrame(runner.skips, columns=['date', 'continuous', 'reason']).to_csv(out / 'skipped.csv', index=False)
    open_positions = [{'continuous': p.continuous, **asdict(p.campaign)} for p in runner.products if p.campaign]
    pending = [{'continuous': p.continuous, 'symbol': p.pending['symbol'], 'action': p.pending['action'],
                'orders': [{'order_id': o.order_id, 'status': o.status, 'volume_left': o.volume_left}
                           for o in p.pending['orders']]} for p in runner.products if p.pending]
    report = {'status': status, 'config': asdict(runner.cfg), 'metrics': result,
              'universe': [p.continuous for p in runner.products], 'open_positions': open_positions,
              'pending_orders': pending, 'signal_errors': sum(p.signal_errors for p in runner.products)}
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [clean(v) for v in value]
        if isinstance(value, (float, np.floating)):
            return float(value) if math.isfinite(value) else None
        if isinstance(value, np.integer):
            return int(value)
        return value
    (out / 'summary.json').write_text(json.dumps(clean(report), ensure_ascii=False, indent=2), encoding='utf-8')
    if curve:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        fig = Figure(figsize=(14, 8), layout='constrained')
        FigureCanvasAgg(fig)
        ax, dd = fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [3, 1]})
        dates = pd.to_datetime([r['date'] for r in curve])
        equity = np.asarray([r['equity'] for r in curve])
        ax.plot(dates, equity)
        ax.set_title('Golden Point Futures / TqSdk')
        ax.set_ylabel('Equity (CNY)')
        ax.text(.01, .98, '\n'.join(f'{k}: {v:.4f}' for k, v in result.items()),
                transform=ax.transAxes, va='top', fontsize=9)
        drawdown = equity / np.maximum.accumulate(np.r_[runner.cfg.init_capital, equity])[1:] - 1
        dd.fill_between(dates, drawdown * 100, 0, alpha=.3, color='red')
        dd.set_ylabel('Drawdown (%)')
        for axis in (ax, dd):
            axis.grid(alpha=.2)
        fig.savefig(out / 'equity.png', dpi=160)
        fig.clear()
    names = {'total_return': '总收益率', 'annual_return': '年化收益率', 'sharpe': '夏普比率',
             'max_drawdown': '最大回撤', 'profit_loss_ratio': '盈亏比', 'profit_factor': '盈利因子',
             'win_rate': '胜率', 'trade_count': '已平仓交易次数', 'positive_horizon_rate': '持仓期间正收益占比',
             'avg_add_count': '平均加仓次数', 'max_add_count': '最大加仓次数'}
    print(f'回测状态：{status}；未平仓：{len(open_positions)}；未完成委托：{len(pending)}')
    for key, value in result.items():
        pct = key.endswith('_rate') or key in ('total_return', 'annual_return', 'max_drawdown')
        shown = '--' if not math.isfinite(value) else f'{value * (100 if pct else 1):.2f}' + ('%' if pct else '')
        print(f'{names[key]}：{shown}')
    print(f'结果目录：{out.resolve()}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', default=Config.start)
    parser.add_argument('--end', default=Config.end)
    parser.add_argument('--symbols', nargs='+', help='默认全部国内期货主力品种；可指定 KQ.m@SHFE.rb 等')
    parser.add_argument('--init-capital', type=float, default=Config.init_capital)
    parser.add_argument('--position-amount', type=float, default=Config.position_amount)
    parser.add_argument('--budget-mode', choices=['margin', 'notional'], default=Config.budget_mode)
    parser.add_argument('--hold-days', type=int, default=Config.hold_days)
    parser.add_argument('--take-profit', type=float, default=Config.take_profit)
    parser.add_argument('--stop-loss', type=float, default=Config.stop_loss)
    parser.add_argument('--history-length', type=int, default=Config.history_length)
    parser.add_argument('--golden-threshold', type=float, default=Config.golden_threshold)
    parser.add_argument('--output', default=Config.output)
    args = vars(parser.parse_args(argv))
    symbols = args.pop('symbols')
    cfg = Config(**args)
    cfg.validate()

    if _TQSDK_IMPORT_ERROR is not None:
        parser.error('缺少 TqSdk，请安装 requirements-tqsdk.txt')
    user, password = os.environ.get('TQ_USER'), os.environ.get('TQ_PASSWORD')
    if not user or not password:
        parser.error('请先设置环境变量 TQ_USER、TQ_PASSWORD（快期账户）；不要将密码写入脚本')
    sim = TqSim(init_balance=cfg.init_capital)
    api = TqApi(sim, auth=TqAuth(user, password),
                backtest=TqBacktest(start_dt=date.fromisoformat(cfg.start), end_dt=date.fromisoformat(cfg.end)))
    runner, status = None, 'failed'
    try:
        runner = FuturesBacktest(api, sim, cfg, symbols)
        while True:
            api.wait_update()
            runner.update()
    except BacktestFinished:
        status = 'completed'
    finally:
        try:
            if runner:
                for product in runner.products:
                    runner.poll_orders(product)
                runner.snapshot()
                save_report(runner, status)
        finally:
            api.close()


if __name__ == '__main__':
    main()
