# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs

def get_buy_point(df,last_bi,threshold=2,klines=10,max_ratio=1.1,min_angle=25):
    if last_bi.fx_a.fx*threshold < last_bi.fx_b.fx:
        # 上一波涨幅必须超过10个交易
        kline_num = days_trade_delta(df,last_bi.sdt.strftime("%Y-%m-%d"),last_bi.edt.strftime("%Y-%m-%d"))
        if kline_num<klines:
            return False
        # 笔的角度
        if bi_angle(last_bi)<30:
            return False
        # 是否在抄底区间内
        sqr_val = sqrt_val(last_bi.fx_a.fx, last_bi.fx_b.fx)
        gold_low_val = gold_val_low(last_bi.fx_a.fx, last_bi.fx_b.fx)
        min_val = min(sqr_val,gold_low_val)
        start_index = df.iloc[df['date'].values == last_bi.edt.strftime("%Y-%m-%d")].index[0]
        for idx in range(start_index,len(df['date'])):
            stock_open = df['open'].iloc[idx]
            stock_close = df['close'].iloc[idx]
            stock_high = df['high'].iloc[idx]
            stock_low = df['low'].iloc[idx]

            
            if stock_low <= min_val and (idx+3)<len(df['date']):
                sdt = last_bi.sdt.strftime("%Y-%m-%d")
                edt = last_bi.edt.strftime("%Y-%m-%d")
                for x in range(1,4):
                    stock_high = df['high'].iloc[idx+3]
                    ratio = round(100*(stock_high-min_val)/min_val,2)
                    if stock_high>min_val:
                        print("{}     {}到{}笔：正收益，{}".format(symbol,sdt,edt,ratio))
                    else:
                        print("{}     {}到{}笔：正收益，{}".format(symbol,sdt,edt,ratio))    
                return ratio
    return 0

if __name__ == '__main__':
    lg = bs.login()

    start_date = "2020-01-01"
    end_date = "2025-03-03"
    
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        df = get_stcok_pd(symbol,start_date,end_date,"d")
        bars = get_stock_bars(symbol=symbol,df=df)
        c = CZSC(bars, get_signals=None)
        for last_bi in c.bi_list:
            get_buy_point(df,last_bi)

    bs.logout()

