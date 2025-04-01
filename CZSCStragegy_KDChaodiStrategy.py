# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs

plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

def get_kd_buy_point(symbol,df,MIN_K=25,MIN_KD=-0.5,MIN_KR=-0.03):
    ndf = get_kd_data(df)
    buy_con = (
        (df['K0'] < MIN_K) & (df['K0'] < REF(df['K0'],1)) &
        (((df['K0']-REF(df['K0'],1))>=MIN_KD) | ((df['K0']-REF(df['K0'],1))/REF(df['K0'],1) >= MIN_KR)) & 
        (REF(df['K0'],1)<REF(df['K0'],2)) & 
        (REF(df['K0'],2)<REF(df['K0'],3)) & 
        (REF(df['K0'],3)<REF(df['K0'],4)) & 
        (REF(df['K0'],4)<REF(df['K0'],5)) & 
        (REF(df['K0'],5)<REF(df['K0'],6)) & 
        (REF(df['K0'],6)<REF(df['K0'],7)) & 
        (REF(df['K0'],7)<REF(df['K0'],8)) &
        (df['low'] <= REF(df['low'], 1)) &
        (df['high'] <= REF(df['high'], 1)) &
        (REF(df['low'], 1) <= REF(df['low'], 2)) &
        (REF(df['high'], 1) <= REF(df['high'], 2)) 
    )

    if not df[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        for idx in selected_indexs:
            buy_date = ndf['date'][idx]
            print(symbol+" 抄底日期："+buy_date)
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
        get_kd_buy_point(symbol,df)

    print_console(plus_list,minus_list,ratio_map)
        
    bs.logout()


