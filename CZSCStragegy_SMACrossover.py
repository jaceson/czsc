# coding: utf-8
import os
import sys
import json
import math
import datetime
import pandas as pd
import backtrader as bt
from CZSCStragegy import *

# 创建策略类
class SMACrossover(CZSCStragegy):
    params = (
        ('short_sma_period', 50),  # 短期SMA周期
        ('long_sma_period', 200),  # 长期SMA周期
    )

    def __init__(self):
        super().__init__()
        # 创建两个SMA指标
        self.short_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.short_sma_period)
        self.long_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.params.long_sma_period)

    def next(self):
        # Check if an order is pending ... if yes, we cannot send a 2nd one
        if self.order:
            return

        if not self.position:
            # 当短期SMA穿越长期SMA时，执行买入操作
            if self.short_sma > self.long_sma and not self.position:
                self.order = self.buy()  # 买入
        else:
            # 当短期SMA下穿长期SMA时，执行卖出操作
            if self.short_sma < self.long_sma:
                self.order = self.sell()


if __name__ == '__main__':
    code = "sh.600000"  # 示例股票代码
    start_date = "2020-01-01"
    end_date = "2024-10-20"

    backtrader_symbol(code, start_date, end_date, SMACrossover)
