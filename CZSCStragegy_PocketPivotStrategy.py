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
    口袋支点指标
'''
# BARSLAST 实现：从当前行往前找最近一次 True 的位置间隔
def bars_last(s):
    """返回每行的 BARSLAST 值"""
    out = np.empty(len(s))
    out[:] = np.nan
    idx = np.where(s)[0]
    for i in range(len(s)):
        if len(idx) == 0:
            out[i] = np.nan
        else:
            # 最后一个 <= i 的 True 的索引
            pos = idx[idx <= i].max() if len(idx[idx <= i]) else np.nan
            out[i] = i - pos if not np.isnan(pos) else np.nan
    return out.astype('int64') 
    
def get_pocket_pivot_buy_point(symbol,df):
    ndf = get_rps_data(df)

    YIHAOCA36 = 20
    YIHAOCA37 = (MA(ndf['close'],YIHAOCA36))
    YIHAOCA38 = (STD(ndf['close'],YIHAOCA36))
    YIHAOCA39 = (YIHAOCA37+2*YIHAOCA38)
    YIHAOCA40 = (YIHAOCA37-2*YIHAOCA38)
    YIHAOCA41 = (LLV(ndf['low'],250))
    YIHAOCA42 = (HHV(ndf['high'],250))
    YIHAOCA43 = ((ndf['close']-YIHAOCA41)/YIHAOCA41*100)
    YIHAOCA44 = ((YIHAOCA42-ndf['close'])/(YIHAOCA42-YIHAOCA41)*100)
    YIHAOCA45 = (YIHAOCA43>85)
    YIHAOCA46 = (YIHAOCA44<=60)

    # 假设 cross_today 是布尔 Series，索引为连续整数 0..n-1
    cond1 = (YIHAOCA45 & YIHAOCA46).astype(int)
    cross_today = (cond1.diff() == 1) & (cond1 == 1)   # 当前发生金叉

    cond = cross_today.values          # 转成 bool ndarray
    idx  = np.arange(len(cond))

    # 计算 BARSLAST（每行往前找最近一次 True 的间隔）
    bars = np.empty(len(cond))
    bars[:] = -1
    true_pos = np.where(cond)[0]
    for i in range(len(cond)):
        if len(true_pos[true_pos <= i]):
            bars[i] = i - true_pos[true_pos <= i][-1]

    # 构造 ref_cross：把 bars 作为 shift 步数，逐行取值
    # 当 bars[i] = k 时，取 cond[i-k]，若 k 越界则置 False
    ref_cross = np.full(len(cond), False, dtype=bool)
    mask = bars >= 0
    ref_cross[mask] = cond[idx[mask] - bars[mask].astype(int)]

    # 转成 Series 方便后续使用
    ref_cross = pd.Series(ref_cross, index=cross_today.index)

    # 最终信号
    YIHAOCA47 = (bars < 60) & ref_cross

    # YIHAOCA47 = (BARSLAST((CROSS(YIHAOCA45 & YIHAOCA46,0.5))<60) & (REF(CROSS(YIHAOCA45 & YIHAOCA46,0.5),BARSLAST(CROSS(YIHAOCA45 & YIHAOCA46,0.5)))==1)
    YIHAOCA48 = (MA(ndf['close'],10))
    YIHAOCA49 = (MA(ndf['close'],30))
    YIHAOCA50 = (MA(ndf['close'],60))
    YIHAOCA51 = (MA(ndf['close'],120))
    YIHAOCA52 = (SLOPE(YIHAOCA48,5))
    YIHAOCA53 = (SLOPE(YIHAOCA49,5))
    YIHAOCA54 = (SLOPE(YIHAOCA50,5))
    YIHAOCA55 = (SLOPE(YIHAOCA51,5))
    YIHAOCA56 = ((YIHAOCA52>0) & (YIHAOCA53>0) & (YIHAOCA54>0) & (YIHAOCA55>0))

    buy_con = (YIHAOCA45 & YIHAOCA46 & YIHAOCA47 & YIHAOCA56)
    if not df[buy_con].empty:
        selected_indexs = ndf[buy_con].index
        for idx in selected_indexs:
            buy_date = ndf['date'][idx]
            print(symbol+" 口袋支点日期："+buy_date)
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
        get_pocket_pivot_buy_point(symbol,df)

    print_console(plus_list,minus_list,ratio_map)
        
    bs.logout()