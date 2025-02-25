# coding: utf-8
import os
import sys
from CZSCStragegy import *
from lib.MyTT import *
from czsc.utils.sig import get_zs_seq
from czsc.analyze import *
from czsc.enum import *
from collections import *

class ThirdBuyStrategy(CZSCStragegy):
    def __init__(self):
        super().__init__()
        
        self.has_Profit = False
        self.has_over_three = False
        self.has_over_five = False
        # Keep a reference to the "close" line in the data[0] dataseries

    def get_datak0(self,idx):
        return self.datak0[self.dataclose.get_idx()+idx]

    def next(self):
        # Check if an order is pending ... if yes, we cannot send a 2nd one
        if self.order:
            return

        k0 = self.get_datak0(0)
        k1 = self.get_datak0(-1)
        k2 = self.get_datak0(-2)
        # Check if we are in the market
        if not self.position:
            self.has_Profit = False
            self.has_over_three = False
            self.has_over_five = False
        
            k3 = self.get_datak0(-3)
            k4 = self.get_datak0(-4)
            k5 = self.get_datak0(-5)
            k6 = self.get_datak0(-6)
            k7 = self.get_datak0(-7)
            k8 = self.get_datak0(-8)
            
            buy_con = (
                (k0 < 30) & (k1<k2) & (k2<k3) &
                (k3<k4) & (k4<k5) & (k5<k6) &
                (k6<k7) & (k7<k8) &
                (self.datalow[0]<=self.datalow[-1]) &
                (self.datahigh[0]<=self.datahigh[-1]) &
                (self.datalow[-1]<=self.datalow[-2]) &
                (self.datahigh[-2]<=self.datahigh[-2]) 
            )
            if buy_con:
                if k0-k1<0 and k0-k1>-0.5 and k0 < 20:
                    self.order = self.buy()
                elif (k0-k1)/k1>=-0.03:
                    self.order = self.buy()
        else:
            if not self.has_Profit:
                if self.dataclose[0]>self.buy_price:
                    self.has_Profit = True
                if self.dataclose[0]/self.buy_price<0.95:
                    self.order = self.sell()
            else:
                if self.dataclose[0]/self.buy_price>1.05:
                    if k0-k1<3:
                        self.order = self.sell()
                elif self.dataclose[0]/self.buy_price>1.03:
                    if self.has_over_five:
                        self.order = self.sell()
                    elif (k0-k1)<(k1-k2):
                        self.order = self.sell()
                else:
                    if self.has_over_three:
                        self.order = self.sell()
                    elif (k0-k1)<(k1-k2):
                        self.order = self.sell()
                    else:
                        if self.dataclose[0]<self.buy_price:
                            self.order = self.sell()

            if not self.has_over_three:
                if self.dataclose[0]/self.buy_price>1.03:
                    self.has_over_three = True
            if not self.has_over_five:
                if self.dataclose[0]/self.buy_price>1.05:
                    self.has_over_five = True            

if __name__ == '__main__':
    code = "sh.600699"  # 示例股票代码
    start_date = "2024-01-01"
    end_date = "2025-02-21"
    backtrader_symbol(code, start_date, end_date, KDChaodiStrategy)

