# coding: utf-8
import os
import sys
import json
import math
import baostock as bs
import datetime
import backtrader as bt
import pandas as pd
from czsc_daily_util import *
from lib.MyTT import *

def pandas_data(data):
    data_list = [data[i] for i in range(-data.buflen()+1, 1)]
    return pd.Series(data_list)

# 创建策略类
class CZSCStragegy(bt.Strategy):
    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        self.order = None
        self.buy_dt = None
        self.sell_dt = None
        self.buy_price = None
        self.sell_price = None

        self.datalow = self.datas[0].low
        self.datahigh = self.datas[0].high
        self.dataopen = self.datas[0].open
        self.dataclose = self.datas[0].close

        self.serieslow = pandas_data(self.datalow)
        self.serieshigh = pandas_data(self.datahigh)
        self.seriesopen = pandas_data(self.dataopen)
        self.seriesclose = pandas_data(self.dataclose)
        
        # K0
        self.datavar = (self.seriesclose - LLV(self.serieslow, 10)) / (HHV(self.serieshigh, 10) - LLV(self.serieslow, 10)) * 100
        self.datak0 = SMA(self.datavar, 10, 1)

    def notify(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Buy/Sell order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            if order.isbuy():
                self.log('买入, %.2f' % order.executed.price)
                self.buy_dt = self.datas[0].datetime.date(0)
                self.buy_price = order.executed.price
            elif order.issell():
                self.log('卖出, %.2f' % order.executed.price)
                self.sell_dt = self.datas[0].datetime.date(0)
                self.sell_price = order.executed.price
                if self.sell_price>self.buy_price:
                    print('正收益：%.2f%%'%(100*(self.sell_price/self.buy_price-1.0)))
                else:
                    print('负收益：%.2f%%'%(100*(self.sell_price/self.buy_price-1.0)))  

            self.bar_executed = len(self)

        # Write down: no pending order
        self.order = None

def backtrader_symbol(symbol,start_date,end_date,strategy,showplot=False):
    lg = bs.login()
    df = get_stock_pd(symbol,start_date,end_date,"d")
    df = get_kd_data(df)
    df = get_rps_data(df)

    # data['date'] = pd.to_datetime(data['date'])
    df.set_index('datetime', inplace=True)
    # data = data.astype(float)

    # Create a cerebro entity
    cerebro = bt.Cerebro()

    # Add a strategy
    cerebro.addstrategy(strategy)

    # Add the Data Feed to Cerebro
    bt_data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(bt_data)

    # Set our desired cash start
    cerebro.broker.setcash(100000.0)

    # 设置佣金
    cerebro.broker.setcommission(commission=0.001)

    # 设置订单大小
    # cerebro.addsizer(bt.sizers.FixedSize, stake=10000)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="_TradeAnalyzer")

    # Add analyze Ratio
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    # Print out the starting conditions
    print('初始资金: %.2f' % cerebro.broker.getvalue())

    # Run over everything
    result = cerebro.run()

    # Print out the final result
    print('最终资金: %.2f' % cerebro.broker.getvalue())

    # strat_result = result[0]
    # trade_analysis = strat_result.analyzers._TradeAnalyzer.get_analysis()
    # print(f"总交易次数: {trade_analysis['total']['closed']}")
    
    # print(trade_analysis)
    # for i, trade in enumerate(trade_analysis['trades']):
    #     print(f"交易 {i + 1}:")
    #     print(f"  盈利: {trade['pnl']['gross']}")
    #     print(f"  净盈利: {trade['pnl']['net']}")
    #     print(f"  交易持续时间: {trade['len']}")
    #     print(f"  开仓价格: {trade['price']['open']}")
    #     print(f"  平仓价格: {trade['price']['close']}")

    # Plot the result
    if showplot:
        cerebro.plot()
