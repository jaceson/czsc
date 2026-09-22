"""
    策略示例：使用talib技术指标库计算双均线，使用日线数据回测
"""

import pandas as pd
import talib
import math
import numpy as np
import os,json
from lib.MyTT import *

universe = ['600030.SH'] # 回测标的
benchmark='000300.SH'    # 基准标的
start = '2026-01-01'     # 回测开始时间
end = '2026-09-01'       # 回测结束时间
frequency = "daily"      # 策略类型，'daily'表示日间策略使用日线回测，'minute'表示日内策略使用分钟线回测

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

period2=70
MAX_HOLD_DAYS = 10   # 最多持仓10个交易日，超过则强制卖出
STOP_LOSS_RATIO = 0.05  # 亏损超过5%即止损卖出
"""
通达信公式：生命线策略
VAR1:=HHV(HIGH,9)-LLV(LOW,9);
VAR2:=HHV(HIGH,9)-CLOSE;
VAR3:=CLOSE-LLV(LOW,9);
VAR4:=VAR2/VAR1*100-70;
VAR5:=(CLOSE-LLV(LOW,60))/(HHV(HIGH,60)-LLV(LOW,60))*100;
VAR6:=(2*CLOSE+HIGH+LOW)/4;
VAR7:=SMA(VAR3/VAR1*100,3,1);
VAR8:=LLV(LOW,34);
VAR9:=SMA(VAR7,3,1)-SMA(VAR4,9,1);
VAR10:=IF(VAR9>100,VAR9-100,0);
VAR11:=HHV(HIGH,34);
VAR12:=EMA((VAR6-VAR8)/(VAR11-VAR8)*100,13);
VAR13:=EMA(0.667*REF(VAR12,1)+0.333*VAR12,2);
STICKLINE(VAR12-VAR13>0,VAR12,VAR13,5,0),    COLORRED;
STICKLINE(VAR12-VAR13<0,VAR12,VAR13,5,0),COLOR00FF0F;
生命线:EMA(VAR13,5), COLORYELLOW;
买:IF(CROSS(VAR13,VAR12) AND VAR12<VAR13 AND VAR12>60,VAR13,88), COLORRED ;
卖:IF(CROSS(VAR12,VAR13) AND VAR12>VAR13 AND VAR12<18,38,18),  COLORGREEN;
"""
def initialize(context): # 初始化
   context.buy_date = {}    # 记录买入日期
   context.buy_price = {}   # 记录买入价格
   context.hold_days = {}   # 记录持仓天数

def handle_data(context, data):
    for stkcode in context.universe:
        df = data.history(stkcode, ['close','low','high'], period2, '1d')
        if len(df) < 60:  # 至少需要60根才能计算所有指标
            continue

        HIGH = df['high']
        LOW = df['low']
        CLOSE = df['close']

        VAR1 = HHV(HIGH,9)-LLV(LOW,9)
        VAR2 = HHV(HIGH,9)-CLOSE
        VAR3 = CLOSE-LLV(LOW,9)
        VAR4 = VAR2/VAR1*100-70
        VAR5 = (CLOSE-LLV(LOW,60))/(HHV(HIGH,60)-LLV(LOW,60))*100
        VAR6 = (2*CLOSE+HIGH+LOW)/4
        VAR7 = SMA(VAR3/VAR1*100,3,1)
        VAR8 = LLV(LOW,34)
        VAR9 = SMA(VAR7,3,1)-SMA(VAR4,9,1)
        VAR10 = IF(VAR9>100,VAR9-100,0)
        VAR11 = HHV(HIGH,34)
        VAR12 = EMA((VAR6-VAR8)/(VAR11-VAR8)*100,13)
        VAR13 = EMA(0.618*REF(VAR12,1)+0.382*VAR12,2)
        VAR14 = IF(VAR12>VAR13, 1, 0)
        VAR15 = REF(VAR14,1)
        VAR16 = EMA(VAR13,5)
        VAR17 = REF(VAR16,1)

        # 买入信号: CROSS(VAR13,VAR12) AND VAR12<VAR13 AND VAR12>60
        current_var12 = VAR12[-1]
        current_var13 = VAR13[-1]
        prev_var12 = VAR12[-2]
        prev_var13 = VAR13[-2]

        # cross_buy = (prev_var13 <= prev_var12 and current_var13 > current_var12)
        # buy_signal = cross_buy and current_var12 < current_var13 and current_var12 > 60
        VAR16_HHV30 = HHV(VAR16, 60)
        cond_var16_gt70 = VAR16_HHV30[-1] > 60
        buy_con1 = ((current_var12-current_var13)>2.5)
        buy_con2 = ((prev_var12-prev_var13)<=2.5)
        #buy_signal = buy_con1 & buy_con2 & (VAR16[-2] < 18) & cond_var16_gt70
        buy_signal = buy_con1 and buy_con2 and (VAR16[-2] < 18)
        # 卖出信号: CROSS(VAR12,VAR13) AND VAR12>VAR13 AND VAR12<18
        cross_sell = ((current_var12-current_var13)<=2)
        sell_signal = cross_sell and (VAR16[-1] > 60)
        
        # 获取股票仓位，单个账户默认取下标为0的组合信息
        position = context.portfolio[0].positions[stkcode].amount

        # 更新持仓天数（有持仓则每天+1）
        if position > 0:
            context.hold_days[stkcode] = context.hold_days.get(stkcode, 0) + 1

        # 交易下单，当短均线上穿长均线且无持仓，则买入
        if buy_signal and position == 0:
            cash = context.portfolio[0].cash
            if cash < every_trade_cash:
                continue
            open_price = get_current_data(stkcode).day_open_price			# 获取交易当日开盘价
            order_amount = math.floor(every_trade_cash / open_price / 100) * 100		# 用全部资金买入股票，数量为100的整数倍
            log.info("生命线买入：{},{},{},{},{}".format(stkcode, data.current_dt, open_price, cash, order_amount))
            order(stkcode, order_amount)
            context.buy_date[stkcode] = data.current_dt.strftime("%Y-%m-%d")	# 记录买入日期
            context.buy_price[stkcode] = open_price					# 记录买入价格
            context.hold_days[stkcode] = 1						# 重置持仓天数（买入日计第1天）
        # 若持仓且满足卖出条件（信号/持满10日/亏损超5%）则卖出
        elif position > 0:
            cur_price = get_current_data(stkcode).day_open_price
            if cur_price is None or cur_price <= 0:
                cur_price = get_current_data(stkcode).last_price
            buy_price = context.buy_price.get(stkcode, 0)
            ret_pct = (cur_price - buy_price) / buy_price * 100 if buy_price > 0 else 0.0
            over_hold = context.hold_days.get(stkcode, 0) >= MAX_HOLD_DAYS
            stop_loss = ret_pct <= -STOP_LOSS_RATIO * 100
            if sell_signal or over_hold or stop_loss:
                if stop_loss:
                    sell_reason = "止损（亏损超过{}%）".format(STOP_LOSS_RATIO * 100)
                elif over_hold:
                    sell_reason = "持仓满{}个交易日".format(MAX_HOLD_DAYS)
                else:
                    sell_reason = "生命线卖出信号"
                log.info("生命线卖出：{},{},原因:{},持仓天数:{},收益率:{:+.2f}%".format(
                    stkcode, data.current_dt, sell_reason, context.hold_days.get(stkcode, 0), ret_pct))
                order_target(stkcode, 0)
                if stkcode in context.buy_date:
                    del context.buy_date[stkcode]
                if stkcode in context.buy_price:
                    del context.buy_price[stkcode]
                if stkcode in context.hold_days:
                    del context.hold_days[stkcode]