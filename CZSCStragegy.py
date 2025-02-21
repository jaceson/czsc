# coding: utf-8
import os
import sys
import json
import math
import baostock as bs
import datetime
import backtrader as bt
import pandas as pd

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
    rs = bs.query_history_k_data_plus(
            symbol,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="3"  # 后复权
    )
    data_list = []
    while rs.error_code == "0" and rs.next():
        data_list.append(rs.get_row_data())
    bs.logout()
    data = pd.DataFrame(data_list, columns=rs.fields)
    data['date'] = pd.to_datetime(data['date'])
    data.set_index('date', inplace=True)
    data = data.astype(float)

    # Create a cerebro entity
    cerebro = bt.Cerebro()

    # Add a strategy
    cerebro.addstrategy(strategy)

    # Add the Data Feed to Cerebro
    bt_data = bt.feeds.PandasData(dataname=data)
    cerebro.adddata(bt_data)

    # Set our desired cash start
    cerebro.broker.setcash(100000.0)

    # 设置佣金
    cerebro.broker.setcommission(commission=0.001)

    # 设置订单大小
    # cerebro.addsizer(bt.sizers.FixedSize, stake=10000)

    # Add analyze Ratio
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

    # Print out the starting conditions
    print('初始资金: %.2f' % cerebro.broker.getvalue())

    # Run over everything
    result = cerebro.run()

    # Print out the final result
    print('最终资金: %.2f' % cerebro.broker.getvalue())
    # print('夏普比率:', result[0].analyzers.sharpe.get_analysis())
    # print('最大回撤:', result[0].analyzers.drawdown.get_analysis())
    # Plot the result
    if showplot:
        cerebro.plot()
