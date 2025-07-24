# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
from CZSCStragegy_AllStrategy import *
from czsc_sqlite import get_local_stock_data

plus_list = []
minus_list = []
hold_days = 15
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

plus_list_1 = []
minus_list_1 = []
ratio_map_1 = {}
for x in range(1,hold_days+1):
    ratio_map_1[x] = []

plus_list_2 = []
minus_list_2 = []
ratio_map_2 = {}
for x in range(1,hold_days+1):
    ratio_map_2[x] = []

plus_list_3 = []
minus_list_3 = []
ratio_map_3 = {}
for x in range(1,hold_days+1):
    ratio_map_3[x] = []
'''
    多个指标相同买点
'''
def get_group_category_same_buy_point(symbol,df):
    buy_con1 = get_main_strong_join_condition(symbol,df)
    buy_con2 = get_longterm_turn_condition(symbol,df)
    if not df[buy_con1].empty and not df[buy_con2].empty:
        selected_indexs1 = df[buy_con1].index
        selected_indexs2 = df[buy_con2].index
        selected_indexs = intersection = list(set(selected_indexs1).intersection(selected_indexs2))
        for idx in selected_indexs:
            buy_date = df['date'][idx]
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

'''
    不同指标不同买点
'''
def get_group_category_after_buy_point(symbol,df):
    buy_con1 = get_pocket_pivot_condition(symbol,df)
    buy_con2_1,buy_con2_2,buy_con2_3 = get_swing_king_condition(symbol,df)

    # 见底
    if not df[buy_con1].empty and not df[buy_con2_1].empty:
        selected_indexs1 = df[buy_con1].index
        selected_indexs2 = df[buy_con2_1].index

        for i,idx1 in enumerate(selected_indexs1):
            for j,idx2 in enumerate(selected_indexs2):
                if idx2<idx1:
                    continue
                # if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1] and (idx2-idx1)<10):
                if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1]):
                    buy_date = df['date'][idx2]
                    print(symbol+" 转折日期："+df['date'][idx1]+"； 见底买入日期："+buy_date)
                    start_index = df.iloc[df['date'].values == buy_date].index[0]
                    buy_price = df['close'].iloc[start_index]
                    max_val = -1000
                    for idx in range(start_index+1,start_index+hold_days+1):
                        if idx<len(df['date']):
                            stock_close = df['close'].iloc[idx]
                        ratio = round(100*(stock_close-buy_price)/buy_price,2)
                        ratio_map[idx-start_index].append(ratio)
                        ratio_map_1[idx-start_index].append(ratio)
                        max_val = max(max_val,ratio)

                    if max_val>0:
                        plus_list.append(max_val)
                        plus_list_1.append(max_val)
                    else:
                        minus_list.append(max_val)
                        minus_list_1.append(max_val)
                break
    # 买进
    if not df[buy_con1].empty and not df[buy_con2_2].empty:
        selected_indexs1 = df[buy_con1].index
        selected_indexs2 = df[buy_con2_2].index

        for i,idx1 in enumerate(selected_indexs1):
            for j,idx2 in enumerate(selected_indexs2):
                if idx2<idx1:
                    continue
                # if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1] and (idx2-idx1)<10):
                if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1]):
                    buy_date = df['date'][idx2]
                    print(symbol+" 转折日期："+df['date'][idx1]+"； 买进买入日期："+buy_date)
                    start_index = df.iloc[df['date'].values == buy_date].index[0]
                    buy_price = df['close'].iloc[start_index]
                    max_val = -1000
                    for idx in range(start_index+1,start_index+hold_days+1):
                        if idx<len(df['date']):
                            stock_close = df['close'].iloc[idx]
                        ratio = round(100*(stock_close-buy_price)/buy_price,2)
                        ratio_map[idx-start_index].append(ratio)
                        ratio_map_2[idx-start_index].append(ratio)
                        max_val = max(max_val,ratio)

                    if max_val>0:
                        plus_list.append(max_val)
                        plus_list_2.append(max_val)
                    else:
                        minus_list.append(max_val)
                        minus_list_2.append(max_val)
                break

    # 加仓
    if not df[buy_con1].empty and not df[buy_con2_3].empty:
        selected_indexs1 = df[buy_con1].index
        selected_indexs2 = df[buy_con2_3].index

        for i,idx1 in enumerate(selected_indexs1):
            for j,idx2 in enumerate(selected_indexs2):
                if idx2<idx1:
                    continue
                # if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1] and (idx2-idx1)<10):
                if idx2 == idx1 or (i < (len(selected_indexs1)-1) and idx2 < selected_indexs1[i+1]):
                    buy_date = df['date'][idx2]
                    print(symbol+" 转折日期："+df['date'][idx1]+"； 加仓买入日期："+buy_date)
                    start_index = df.iloc[df['date'].values == buy_date].index[0]
                    buy_price = df['close'].iloc[start_index]
                    max_val = -1000
                    for idx in range(start_index+1,start_index+hold_days+1):
                        if idx<len(df['date']):
                            stock_close = df['close'].iloc[idx]
                        ratio = round(100*(stock_close-buy_price)/buy_price,2)
                        ratio_map[idx-start_index].append(ratio)
                        ratio_map_3[idx-start_index].append(ratio)
                        max_val = max(max_val,ratio)

                    if max_val>0:
                        plus_list.append(max_val)
                        plus_list_3.append(max_val)
                    else:
                        minus_list.append(max_val)
                        minus_list_3.append(max_val)
                break

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
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        # 打印进度
        print("进度：{} / {}".format(all_symbols.index(symbol),len(all_symbols)))
            
        # if symbol != "sz.300264":
        #     continue
        # df = get_stock_pd(symbol, start_date, current_date_str, 'd')
        df = get_local_stock_data(symbol,'2020-01-01')
        get_group_category_after_buy_point(symbol,df)

    print("======================== 整体 ========================")
    print_console(plus_list,minus_list,ratio_map)
    
    print("======================== 见底买入 ========================")
    print_console(plus_list_1,minus_list_1,ratio_map_1)

    print("======================== 买进买入 ========================")
    print_console(plus_list_2,minus_list_2,ratio_map_2)

    print("======================== 加仓买入 ========================")
    print_console(plus_list_3,minus_list_3,ratio_map_3)