"""
    策略示例：顺势上车（CZSCStragegy_FormulaSignal_FollowTrend 迁移至CATS平台）
    使用日线数据回测

    通达信公式（顺势上车）：
    VAR1:=CLOSE;
    VAR2:=(EMA(VAR1,5)*7+EMA(VAR1,10)*3)/10;
    VAR6:=(C*3+H+L+O)/6;
    VAR7:=EMA(VAR6,13)-EMA(VAR6,21);
    VAR10:=EMA(VAR1,7)-EMA(VAR1,21);
    VAR11:=EMA(0.668*REF(VAR10,1)+0.333*VAR10,1);
    VAR13:=V/SUM(V,13);
    VAR14:=DMA(VAR1, VAR13);
    VAR15:=(VAR1-VAR14)/VAR14*40;
    VAR16:=MA(AMOUNT/V,13);   (本地/CATS量单位均为股，故不用/100)
    VAR17:=(VAR1-VAR16)/VAR16*100;
    VAR20:=IF(VAR10>=VAR11,VAR10,VAR11);
    VAR22:=VAR15>0 AND VAR20>0;
    VAR23:=VAR17>5;
    顺势上车:BARSLASTCOUNT(VAR23)=1 AND MA(VAR1,5)>MA(VAR1,10) AND L<MA(VAR1,10) AND VAR1>MA(VAR1,5);

    策略逻辑：
      买入  ：最新已完成日线出现买入信号，当日（next open语义）以开盘价买入
      卖出  ：当日收盘价较成本盈利即卖出；亏损超5%止损；持仓满 MAX_HOLD_DAYS 强制卖出
"""

import pandas as pd
import talib
import math
import numpy as np
import os,json
from lib.MyTT import *

universe = ['600030.SH'] # 回测标的
benchmark='000300.SH'    # 基准标的
start = '2024-01-01'     # 回测开始时间
end = '2026-09-01'       # 回测结束时间
frequency = "daily"      # 策略类型，'daily'表示日间策略使用日线回测

# ==================== 股票列表 ====================
cur_dir = os.getcwd()
symbol_file = os.path.join(cur_dir, 'sample/sh_sz_stock.json')
with open(symbol_file, 'r', encoding='utf-8') as file:
    result = json.load(file)
    file.close()
    universe = []
    for item in result:
        stock_code = list(item.keys())[0]
        stock_code_arr = stock_code.split('.')
        universe.append(stock_code_arr[1]+'.'+stock_code_arr[0].upper())

every_trade_cash = 40000
universe = universe[:1000]
# 设置回测股票账户， 账户需要在CATS系统中处于登录状态，sim_capital_base小于账户总资金
add_trade_account(CatsTradeAccount('CATS668', 'S0', sim_capital_base=1000000.0))
# 设置股票类每笔交易时的手续费：买入佣金万分之三，卖出佣金万分之三，卖出时千分之一印花税, 每笔交易佣金最低扣5块钱
set_commission_equity(AShareCommission(open_commission=0.0003,sell_commission=0.0003,open_tax=0.0,sell_tax=0.001,min_commission=5.0))

MAX_HOLD_DAYS = 2   # 最多持仓2个交易日，超过则强制卖出
STOP_LOSS_RATIO = 0.05  # 亏损超过5%即止损卖出


# ==================== 指标计算 ====================
def calc_signal(df):
    """
    计算顺势上车信号序列，返回与df等长的0/1数组。
    """
    if df is None or len(df) < 60:
        return None

    H = df['high'].astype(float).values
    L = df['low'].astype(float).values
    C = df['close'].astype(float).values
    O = df['open'].astype(float).values
    V = df['volume'].astype(float).values
    AMOUNT = df['turnover'].astype(float).values

    VAR1 = C
    VAR2 = (EMA(VAR1, 5) * 7 + EMA(VAR1, 10) * 3) / 10
    VAR6 = (C * 3 + H + L + O) / 6
    VAR7 = EMA(VAR6, 13) - EMA(VAR6, 21)
    VAR10 = EMA(VAR1, 7) - EMA(VAR1, 21)
    VAR11 = EMA(0.668 * REF(VAR10, 1) + 0.333 * VAR10, 1)

    with np.errstate(divide='ignore', invalid='ignore'):
        VAR13 = V / SUM(V, 13)
    VAR14 = DMA(VAR1, np.clip(np.where(np.abs(VAR13) > 1e-10, VAR13, 0), 0, 1))
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR15 = np.where(np.abs(VAR14) > 1e-10, (VAR1 - VAR14) / VAR14 * 40, 0)

    with np.errstate(divide='ignore', invalid='ignore'):
        VAR16 = MA(np.where(V > 1e-10, AMOUNT / V, C), 13)
    with np.errstate(divide='ignore', invalid='ignore'):
        VAR17 = np.where(np.abs(VAR16) > 1e-10, (C - VAR16) / VAR16 * 100, 0)

    VAR20 = np.where(VAR10 >= VAR11, VAR10, VAR11)
    VAR22 = (VAR15 > 0) & (VAR20 > 0)

    VAR23 = VAR17 > 5
    MA5 = MA(VAR1, 5)
    MA10 = MA(VAR1, 10)

    signal = np.where(
        (BARSLASTCOUNT(VAR23) == 1) &
        (MA5 > MA10) &
        (L < MA10) &
        (VAR1 > MA5),
        1, 0)
    return signal


def initialize(context): # 初始化
   context.buy_price = {}   # 记录买入价格
   context.hold_days = {}   # 记录持仓天数

def handle_data(context, data):
    for stkcode in context.universe:
        df = data.history(stkcode, ['open', 'close', 'high', 'low', 'volume', 'turnover'], 100, '1d')
        if df is None or len(df) < 60:  # 至少需要60根才能计算所有指标
            continue

        signal = calc_signal(df)
        if signal is None:
            continue

        # 买入信号取最新一根已完成日线，当日以下单框架的次日开盘语义执行
        buy_signal = signal[-1] == 1

        # 获取股票仓位，单个账户默认取下标为0的组合信息
        position = context.portfolio[0].positions[stkcode].amount

        # 更新持仓天数（有持仓则每天+1）
        if position > 0:
            context.hold_days[stkcode] = context.hold_days.get(stkcode, 0) + 1

        # 交易下单，出现买入信号且无持仓则买入
        if buy_signal and position == 0:
            cash = context.portfolio[0].cash
            if cash < every_trade_cash:
                continue
            open_price = get_current_data(stkcode).day_open_price			# 获取交易当日开盘价
            order_amount = math.floor(every_trade_cash / open_price / 100) * 100		# 用全部资金买入股票，数量为100的整数倍
            log.info("顺势上车买入：{},{},{},{},{}".format(stkcode, data.current_dt, open_price, cash, order_amount))
            order(stkcode, order_amount)
            context.buy_price[stkcode] = open_price			# 记录买入价格
            context.hold_days[stkcode] = 1				# 重置持仓天数（买入日计第1天）
        # 若持仓，按收盘盈利/止损/超期规则决定卖出
        elif position > 0:
            last_close = float(df['close'].iloc[-1])			# 最新已完成日线收盘价
            buy_price = context.buy_price.get(stkcode, 0)
            if buy_price <= 0:
                continue
            ret_pct = (last_close - buy_price) / buy_price * 100
            over_hold = context.hold_days.get(stkcode, 0) >= MAX_HOLD_DAYS
            stop_loss = ret_pct <= -STOP_LOSS_RATIO * 100

            if ret_pct > 0.0:
                sell_reason = "收盘盈利卖出（{:+.2f}%）".format(ret_pct)
            elif stop_loss:
                sell_reason = "止损（亏损超过{}%）".format(STOP_LOSS_RATIO * 100)
            elif over_hold:
                sell_reason = "持仓满{}个交易日".format(MAX_HOLD_DAYS)
            else:
                sell_reason = None

            if sell_reason is not None:
                log.info("顺势上车卖出：{},{},原因:{},持仓天数:{},收益率:{:+.2f}%".format(
                    stkcode, data.current_dt, sell_reason, context.hold_days.get(stkcode, 0), ret_pct))
                order_target(stkcode, 0)
                if stkcode in context.buy_price:
                    del context.buy_price[stkcode]
                if stkcode in context.hold_days:
                    del context.hold_days[stkcode]