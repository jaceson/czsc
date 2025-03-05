# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs

plus_list = []
minus_list = []
hold_days = 3
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

def get_buy_point(df,last_bi,threshold=2,klines=10,min_angle=30):
    if last_bi.fx_a.fx*threshold < last_bi.fx_b.fx:
        # 上一波涨幅必须超过10个交易
        up_kline_num = days_trade_delta(df,last_bi.sdt.strftime("%Y-%m-%d"),last_bi.edt.strftime("%Y-%m-%d"))
        if up_kline_num<klines:
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

            # 三天内上涨
            if stock_low <= min_val and (idx+3)<len(df['date']):
                # 调整到黄金点位时间太长
                # down_kline_num = days_trade_delta(df,last_bi.edt.strftime("%Y-%m-%d"),df['date'].iloc[idx])
                # if down_kline_num>=up_kline_num:
                #     break
                sdt = last_bi.sdt.strftime("%Y-%m-%d")
                edt = last_bi.edt.strftime("%Y-%m-%d")
                print("{} {}到{}笔：{}到黄金分割点".format(symbol,sdt,edt,df['date'].iloc[idx]))
                max_val = -1000
                # min_val = 1000
                for x in range(1,hold_days+1):
                    stock_high = df['high'].iloc[idx+x]
                    ratio = round(100*(stock_high-min_val)/min_val,2)
                    ratio_map[x].append(ratio)
                    max_val = max(max_val,ratio)
                    # min_val = min(min_val,ratio)
                    if ratio>0:
                        print("第 {} 天{}：正收益，{}".format(x, df['date'].iloc[idx+x],ratio))
                    else:
                        print("第 {} 天{}：负收益，{}".format(x, df['date'].iloc[idx+x],ratio))

                if max_val>0:
                    plus_list.append(max_val)
                else:
                    minus_list.append(max_val)
                break

if __name__ == '__main__':
    lg = bs.login()

    start_date = "2020-01-01"
    end_date = get_latest_trade_date()
    
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        df = get_stcok_pd(symbol,start_date,end_date,"d")
        while len(df) <= 0:
            lg = bs.login()
            print('login respond error_code:' + lg.error_code)
            print('login respond  error_msg:' + lg.error_msg)
            # 重新获取
            df = get_stcok_pd(symbol, START_TRADE_DATE, last_trade_date, 'd')

        bars = get_stock_bars(symbol=symbol,df=df)
        c = CZSC(bars, get_signals=None)
        for last_bi in c.bi_list:
            get_buy_point(df,last_bi)

    print("正收益次数："+str(len(plus_list)))
    print("正收益占比："+str(round(100*len(plus_list)/(len(minus_list)+len(plus_list)),2))+"%")
    total = 0
    for x in range(0,len(plus_list)):
        total += plus_list[x]
    print("总的正收益："+str(total))

    total = 0
    for x in range(0,len(minus_list)):
        total += minus_list[x]
    print("总的负收益："+str(total))
    
    # 每天
    for x in range(1,hold_days+1):
        print("第 {} 天：".format(x))
        res_list = ratio_map[x]
        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for idx in range(0,len(res_list)):
            ratio = res_list[idx]
            if ratio>0:
                plus_num += 1
                plus_val += ratio
            else:
                minus_num += 1
                minus_val += ratio
        print("     正收益次数："+str(plus_num))
        print("     正收益占比："+str(round(100*plus_num/(plus_num+minus_num),2))+"%")
        print("     总的正收益："+str(plus_val))
        print("     总的负收益："+str(minus_val))
        
    bs.logout()

