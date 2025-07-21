# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs

plus_list = []
minus_list = []
hold_days = 15
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

'''
    主力进场指标
'''
def get_main_strong_join_buy_point(symbol,df):
    ndf = get_rps_data(df)

    YHCSXPXGTJ1 = (MA(ndf['close'], 5))
    YHCSXPXGTJ2 = (MA(ndf['close'], 10))
    YHCSXPXGTJ3 = (MA(ndf['close'], 20))
    YHCSXPXGTJ4 = (MA(ndf['close'], 60))

    YHCSXPXGTJ5 = (SLOPE(YHCSXPXGTJ1, 5))
    YHCSXPXGTJ6 = (SLOPE(YHCSXPXGTJ2, 5))
    YHCSXPXGTJ7 = (SLOPE(YHCSXPXGTJ3, 5))
    YHCSXPXGTJ8 = (SLOPE(YHCSXPXGTJ4, 5))
    YHCSXPXGTJ9 = ((YHCSXPXGTJ5 > 0) & (YHCSXPXGTJ6 > 0) & (YHCSXPXGTJ7 > 0) & (YHCSXPXGTJ8 > 0))

    YHCSXPXGTJ10 = (EMA(ndf['close'], 12) - EMA(ndf['close'], 26))
    YHCSXPXGTJ11 = (EMA(YHCSXPXGTJ10, 9))
    YHCSXPXGTJ12 = ((YHCSXPXGTJ10 - YHCSXPXGTJ11) * 2)
    YHCSXPXGTJ13 = ((YHCSXPXGTJ10 > YHCSXPXGTJ11) & (YHCSXPXGTJ12 > REF(YHCSXPXGTJ12, 1)))

    YHCSXPXGTJ14 = ((ndf['close'] - REF(ndf['close'], 1)) / REF(ndf['close'], 1) * 100 > 8)
    YHCSXPXGTJ15 = ((ndf['open'] - REF(ndf['close'], 1)) / REF(ndf['close'], 1) * 100 < 3)

    YHCSXPXGTJ16 = (ndf['close'] > ndf['open'])
    YHCSXPXGTJ17 = (REF(ndf['close'], 1) / REF(ndf['close'], 2) <= 1.05)

    YHCSXPXGTJ18 = (REF(ndf['close'], 1))
    YHCSXPXGTJ19 = (SMA(MAX(ndf['close'] - YHCSXPXGTJ18, 0), 14, 1) / SMA(ABS(ndf['close'] - YHCSXPXGTJ18), 14, 1) * 90)

    YHCSXPXGTJ20 = (YHCSXPXGTJ19 < 80)
    YHCSXPXGTJ21 = (ndf['volume'] > MA(ndf['volume'], 5))

    buy_con = (YHCSXPXGTJ9 & YHCSXPXGTJ13 & YHCSXPXGTJ14 & YHCSXPXGTJ15  & YHCSXPXGTJ16  & YHCSXPXGTJ17  & YHCSXPXGTJ20  & YHCSXPXGTJ21)
    if not df[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        for idx in selected_indexs:
            buy_date = ndf['date'][idx]
            print(symbol+" 主力进场日期："+buy_date)
            start_index = df.iloc[df['date'].values == buy_date].index[0]
            buy_price = df['close'].iloc[start_index]
            max_val = -1000
            for idx in range(start_index+1,start_index+hold_days+1):
                if idx<len(df['date']):
                    stock_close = df['close'].iloc[idx]
                    ratio = round(100*(stock_close-buy_price)/buy_price,2)
                    ratio_map[idx-start_index].append(ratio)
                    max_val = max(max_val,ratio)

            if max_val>0:
                plus_list.append(max_val)
            else:
                minus_list.append(max_val)

def print_console(s_plus_list,s_minus_list,s_ratio_map):
    print("正收益次数："+str(len(s_plus_list)))
    if len(s_minus_list)>0 or len(s_plus_list):
        print("正收益占比："+str(round(100*len(s_plus_list)/(len(s_minus_list)+len(s_plus_list)),2))+"%")
    total = 0
    for x in range(0,len(s_plus_list)):
        total += s_plus_list[x]
    print("总的正收益："+str(total))

    total = 0
    for x in range(0,len(s_minus_list)):
        total += s_minus_list[x]
    print("总的负收益："+str(total))
    
    # 每天
    for x in range(1,hold_days+1):
        print("第 {} 天：".format(x))
        res_list = s_ratio_map[x]
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
        if plus_num>0 or minus_num>0:
            print("     正收益占比："+str(round(100*plus_num/(plus_num+minus_num),2))+"%")
        print("     总的正收益："+str(plus_val))
        print("     总的负收益："+str(minus_val))

if __name__ == '__main__':
    lg = bs.login()

    start_date = "2020-01-01"
    current_date = datetime.now()
    current_date_str = current_date.strftime('%Y-%m-%d')    
    df = get_stock_pd("sh.000001", start_date, current_date_str, 'd')
    end_date = df['date'].iloc[-1]
    
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        # 打印进度
        print("进度：{} / {}".format(all_symbols.index(symbol),len(all_symbols)))
            
        # if symbol != "sz.300264":
        #     continue
        df = get_stock_pd(symbol, start_date, current_date_str, 'd')
        get_main_strong_join_buy_point(symbol,df)

    print_console(plus_list,minus_list,ratio_map)
        
    bs.logout()