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
    波段之王指标
'''
def get_longterm_turn_buy_point(symbol,df):
    ndf = get_rps_data(df)

    YIHA01 = ((ndf['close']-LLV(ndf['low'],25))/(HHV(ndf['high'],25)-LLV(ndf['low'],25))*100)
    YIHA02 = (SMA(YIHA01,3,1))
    YIHA03 = (SMA(YIHA02,3,1))
    YIHA04 = (3*YIHA02-2*YIHA03)
    YIHA05 = ((2*ndf['close']+ndf['high']+ndf['low'])/4)

    YIHA06 = (EMA(EMA(EMA(YIHA05,4),4),4))
    YIHA07 = ((YIHA06-REF(YIHA06,1))/REF(YIHA06,1)*100)
    YIHA08 = (MA(YIHA07,3)+0.03)
    YIHA09 = (MA(YIHA07,1))
    YIHA2 = ((ndf['close']-LLV(ndf['low'],9))/(HHV(ndf['high'],9)-LLV(ndf['low'],9))*100)

    YIHA3 = (SMA(YIHA2,3,1))
    YIHA4 = (SMA(YIHA3,3,1))
    YIHA5 = (3*YIHA3-2*YIHA4)

    YIHA6 = (100*((EMA((ndf['high']+ndf['low'])/2,3)-LLV(EMA((ndf['high']+ndf['low'])/2,5),30)-(EMA(ndf['high'],20)-EMA(ndf['low'],20)))/(LLV(EMA((ndf['high']+ndf['low'])/2,5),30)-(EMA(ndf['high'],20)-EMA(ndf['low'],20)))))
    YIHA1 = (EMA(SLOPE(ndf['close'],3)*20+ndf['close'],34))
    YIHA7 = (IF((EMA(ndf['close'],2)>YIHA1) & (YIHA6>0),EMA(ndf['close'],3),LLV(EMA((ndf['high']+ndf['low'])/2,5),30)))
    YIHA8 = (IF((EMA(ndf['close'],2)>YIHA1) & (YIHA6>0),LLV(EMA((ndf['high']+ndf['low'])/2,5),30),EMA(ndf['close'],5)))

    YIHA9 = (SMA(ndf['close'],6,1))
    YIHA10 = (SMA(ndf['close'],13,1))
    YIHA11 = (SMA(ndf['close'],3,1))
    YIHA12 = (SMA(ndf['close'],8,1))
    YIHA13 = (SMA(ndf['close'],3,1))

    YIHA14 = ((MA(ndf['close'],3)+MA(ndf['close'],6)+MA(ndf['close'],12)+MA(ndf['close'],25))/4)
    YIHA15 = (YIHA14+3*STD(YIHA14,13))
    YIHA16 = (YIHA14-3*STD(YIHA14,13))

    YIHA17 = (MA(ndf['close'],55))
    YIHA18 = (REF(ndf['close'],1))
    YIHA19 = (SMA(MAX(ndf['close']-YIHA18,0),6,1)/SMA(ABS(ndf['close']-YIHA18),6,1)*100)


    YIHA20 = ((2*ndf['close']+ndf['high']+ndf['low'])/4)
    YIHA21 = (MA(YIHA20,5))
    YIHA22 = (YIHA21*1.02)
    YIHA23 = (YIHA21*0.98)

    YIHA24 = (LLV(YIHA20,21))
    YIHA25 = (HHV(YIHA20,30))
    YIHA26 = (YIHA21>=REF(YIHA21,1))

    YIHA27 = (MAX(MAX(YIHA9,YIHA12),YIHA10))
    YIHA28 = (MIN(MIN(YIHA9,YIHA12),YIHA10))


# DRAWTEXT(CROSS(YIHA12,YIHA11),H*1.08,'压力'),COLORGREEN;

# DRAWTEXT(CROSS(82,YIHA19) AND CLOSE<YIHA11, HIGH*1.04,'高位'),COLORLICYAN;

# DRAWTEXT(CROSS(YIHA11,YIHA21) AND YIHA11<YIHA10 AND YIHA11<YIHA12 AND YIHA11<YIHA9 AND CLOSE>YIHA24, LOW*0.98,'见底'),COLORYELLOW;

# DRAWTEXT(CROSS(YIHA11,YIHA9) AND YIHA11>YIHA21, LOW*0.92,'买进'),COLORYELLOW;

# DRAWTEXT(CROSS(YIHA11,YIHA12)  AND YIHA11>YIHA21, LOW*0.98,'加仓'),  COLORYELLOW;

    # buy_con = (CROSS(YIHA11,YIHA21) & (YIHA11<YIHA10) & (YIHA11<YIHA12) & (YIHA11<YIHA9) & (ndf['close']>YIHA24))
    buy_con = (CROSS(YIHA11,YIHA9) & (YIHA11>YIHA21))
    if not df[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        for idx in selected_indexs:
            buy_date = ndf['date'][idx]
            print(symbol+" 见底日期："+buy_date)
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
        get_longterm_turn_buy_point(symbol,df)

    print_console(plus_list,minus_list,ratio_map)
        
    bs.logout()