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

class TestStrategy(bt.Strategy):
    def log(self, txt, dt=None):
        ''' Logging function fot this strategy'''
        dt = dt or self.datas[0].datetime.date(0)
        print('%s, %s' % (dt.isoformat(), txt))

    def __init__(self):
        # Keep a reference to the "close" line in the data[0] dataseries
        self.dataclose = self.datas[0].close
        # To keep track of pending orders
        self.order = None

    def notify(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            # Buy/Sell order submitted/accepted to/by broker - Nothing to do
            return

        # Check if an order has been completed
        # Attention: broker could reject order if not enougth cash
        if order.status in [order.Completed, order.Canceled, order.Margin]:
            if order.isbuy():
                self.log('BUY EXECUTED, %.2f' % order.executed.price)
            elif order.issell():
                self.log('SELL EXECUTED, %.2f' % order.executed.price)

            self.bar_executed = len(self)

        # Write down: no pending order
        self.order = None

    def next(self):
        # Simply log the closing price of the series from the reference
        self.log('Close, %.2f' % self.dataclose[0])

        # Check if an order is pending ... if yes, we cannot send a 2nd one
        if self.order:
            return

        # Check if we are in the market
        if not self.position:

            # Not yet ... we MIGHT BUY if ...
            if self.dataclose[0] < self.dataclose[-1]:
                # current close less than previous close

                if self.dataclose[-1] < self.dataclose[-2]:
                    # previous close less than the previous close

                    # BUY, BUY, BUY!!! (with default parameters)
                    self.log('BUY CREATE, %.2f' % self.dataclose[0])

                    # Keep track of the created order to avoid a 2nd order
                    self.order = self.buy()

        else:

            # Already in the market ... we might sell
            if len(self) >= (self.bar_executed + 5):
                # SELL, SELL, SELL!!! (with all possible default parameters)
                self.log('SELL CREATE, %.2f' % self.dataclose[0])

                # Keep track of the created order to avoid a 2nd order
                self.order = self.sell()


def get_my_analyzer(result):
    analyzer = {}
    # 返回参数
    # analyzer['period1'] = result.params.period1
    # analyzer['period2'] = result.params.period2
    # 提取年化收益
    analyzer['年化收益率'] = result.analyzers._Returns.get_analysis()['rnorm']
    analyzer['年化收益率（%）'] = result.analyzers._Returns.get_analysis()['rnorm100']
    # 提取最大回撤(习惯用负的做大回撤，所以加了负号)
    analyzer['最大回撤（%）'] = result.analyzers._DrawDown.get_analysis()['max']['drawdown'] * (-1)
    # 提取夏普比率
    analyzer['年化夏普比率'] = result.analyzers._SharpeRatio_A.get_analysis()['sharperatio']
    
    return analyzer

if __name__ == '__main__':
    # Create a cerebro entity
    cerebro = bt.Cerebro()

    # Add a strategy
    cerebro.addstrategy(TestStrategy)

    # Create a Data Feed
    # 本地数据，笔者用Wind获取的东风汽车数据以csv形式存储在本地。
    # parase_dates = True是为了读取csv为dataframe的时候能够自动识别datetime格式的字符串，big作为index
    # 注意，这里最后的pandas要符合backtrader的要求的格式
    dataframe = pd.read_csv('/Users/wj/Downloads/dfqc.csv', index_col=0, parse_dates=True)
    dataframe['openinterest'] = 0
    data = bt.feeds.PandasData(dataname=dataframe,
                        fromdate = datetime(2015, 1, 1),
                        todate = datetime(2016, 12, 31)
                        )
    # Add the Data Feed to Cerebro
    cerebro.adddata(data)

    # Set our desired cash start
    cerebro.broker.setcash(100000.0)

    # Print out the starting conditions
    print('Starting Portfolio Value: %.2f' % cerebro.broker.getvalue())

    # 添加分析指标
    # 返回年初至年末的年度收益率
    # cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='_AnnualReturn')
    # # 计算最大回撤相关指标
    # cerebro.addanalyzer(bt.analyzers.DrawDown, _name='_DrawDown')
    # # 计算年化收益
    # cerebro.addanalyzer(bt.analyzers.Returns, _name='_Returns', tann=252)
    # # 计算年化夏普比率
    # cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name='_SharpeRatio_A')
    # # 返回收益率时序
    # cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='_TimeReturn')

    # Run over everything
    result = cerebro.run()
    print(result)
    # ret = []
    # for i in result:
    #     ret.append(get_my_analyzer(i[0]))
    
    # pd.DataFrame(ret)

    # Print out the final result
    print('Final Portfolio Value: %.2f' % cerebro.broker.getvalue())
    # Plot the result
    cerebro.plot()
