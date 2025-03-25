# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
from Chan import *
from ChanConfig import *
from DataAPI.BaoStockAPI import *
from Common.CEnum import *
from datetime import datetime
import pandas as pd
import baostock as bs

plus_list = {BSP_TYPE.T1:[],BSP_TYPE.T1P:[],BSP_TYPE.T2:[],BSP_TYPE.T2S:[],BSP_TYPE.T3A:[],BSP_TYPE.T3B:[]}
minus_list = {BSP_TYPE.T1:[],BSP_TYPE.T1P:[],BSP_TYPE.T2:[],BSP_TYPE.T2S:[],BSP_TYPE.T3A:[],BSP_TYPE.T3B:[]}
hold_days = 5
ratio_map = {BSP_TYPE.T1:{},BSP_TYPE.T1P:{},BSP_TYPE.T2:{},BSP_TYPE.T2S:{},BSP_TYPE.T3A:{},BSP_TYPE.T3B:{}}
for k in ratio_map.keys():
    for x in range(1,hold_days+1):
        ratio_map[k][x] = []

def get_kl_data(data_list):
    fields = "date,open,high,low,close,volume,amount,turn"
    for row_data in data_list:
        yield CKLine_Unit(create_item_dict(row_data, GetColumnNameFromFieldList(fields)))

def get_chan_buy_point(symbol, start_date, end_date, frequency):
    config = CChanConfig({
        "trigger_step": True,
        "divergence_rate": 0.8,
        "min_zs_cnt": 1,
    })

    chan = CChan(
        code=symbol,
        begin_time=start_date,  # 已经没啥用了这一行
        end_time=end_date,  # 已经没啥用了这一行
        data_src=DATA_SRC.BAO_STOCK,  # 已经没啥用了这一行
        lv_list=[KL_TYPE.K_DAY],
        config=config,
        autype=AUTYPE.QFQ,  # 已经没啥用了这一行
    )

    data_list,fields = get_stock_data(symbol, start_date, end_date, frequency)
    while len(data_list) <= 0:
        lg = bs.login()
        print('login respond error_code:' + lg.error_code)
        print('login respond  error_msg:' + lg.error_msg)
        # 重新获取
        data_list,fields = get_stock_data(symbol, start_date, end_date, frequency)

    df = pd.DataFrame(data_list, columns=fields)
    df['low'] = df['low'].astype(float)
    df['high'] = df['high'].astype(float)
    df['open'] = df['open'].astype(float)
    df['close'] = df['close'].astype(float)
    df['volume'] = df['volume'].astype(float)
    df['amount'] = df['amount'].astype(float)
    df['turn'] = df['turn'].astype(float)
    df['datetime'] = pd.to_datetime(df['date'])

    buy_date_list = []
    for klu in get_kl_data(data_list):  # 获取单根K线
        chan.trigger_load({KL_TYPE.K_DAY: [klu]})  # 喂给CChan新增k线
        bsp_list = chan.get_bsp()
        if not bsp_list:
            continue
        last_bsp = bsp_list[-1]
        if not last_bsp.is_buy:
            continue

        buy_date = last_bsp.klu.time.toDateStr('-')
        if buy_date in buy_date_list:
            continue
        buy_date_list.append(buy_date)
        print(f'{symbol} {last_bsp.klu.time} {last_bsp.type}')
        
        buy_type = None
        if BSP_TYPE.T1 in last_bsp.type:
            buy_type = BSP_TYPE.T1
        elif BSP_TYPE.T1P in last_bsp.type:
            buy_type = BSP_TYPE.T1P
        elif BSP_TYPE.T2 in last_bsp.type:
            buy_type = BSP_TYPE.T2
        elif BSP_TYPE.T2S in last_bsp.type:
            buy_type = BSP_TYPE.T2S
        elif BSP_TYPE.T3A in last_bsp.type:
            buy_type = BSP_TYPE.T3A
        elif BSP_TYPE.T3B in last_bsp.type:
            buy_type = BSP_TYPE.T3B
        else:
            print('无法识别的买卖点类型')
            continue

        start_index = df.iloc[df['date'].values == buy_date].index[0]
        buy_price = df['close'].iloc[start_index]
        max_val = -1000
        for idx in range(start_index+1,start_index+hold_days+1):
            if idx<len(df['date']):
                stock_close = df['close'].iloc[idx]
                ratio = round(100*(stock_close-buy_price)/buy_price,2)
                ratio_map[buy_type][idx-start_index].append(ratio)
                max_val = max(max_val,ratio)

        if max_val>0:
            plus_list[buy_type].append(max_val)
        else:
            minus_list[buy_type].append(max_val)

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

    start_date = "2024-01-01"
    current_date = datetime.now()
    current_date_str = current_date.strftime('%Y-%m-%d')    
    df = get_stock_pd("sh.000001", start_date, current_date_str, 'd')
    end_date = df['date'].iloc[-1]
    
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        # if symbol != "sh.600562":
        #     continue
        get_chan_buy_point(symbol,start_date,end_date,'d')

    for buy_type in plus_list.keys():
        print('购买类型：{}'.format(buy_type))
        print_console(plus_list[buy_type],minus_list[buy_type],ratio_map[buy_type])
        
    bs.logout()

    """
    购买类型：BSP_TYPE.T1
正收益次数：61952
正收益占比：95.28%
总的正收益：448272.9899999877
总的负收益：-4055.359999999994
第 1 天：
     正收益次数：51684
     正收益占比：79.49%
     总的正收益：147959.04000000417
     总的负收益：-19173.499999999694
第 2 天：
     正收益次数：54588
     正收益占比：83.95%
     总的正收益：202459.53999998685
     总的负收益：-18313.54999999979
第 3 天：
     正收益次数：53814
     正收益占比：82.77%
     总的正收益：221002.93999999092
     总的负收益：-20842.41000000025
第 4 天：
     正收益次数：54835
     正收益占比：84.36%
     总的正收益：315473.7200000006
     总的负收益：-22991.439999999853
第 5 天：
     正收益次数：55454
     正收益占比：85.37%
     总的正收益：374432.7399999934
     总的负收益：-24972.92000000007
购买类型：BSP_TYPE.T1P
正收益次数：13897
正收益占比：95.18%
总的正收益：99873.28999999755
总的负收益：-671.7400000000019
第 1 天：
     正收益次数：11564
     正收益占比：79.21%
     总的正收益：30195.23999999987
     总的负收益：-3945.3400000000306
第 2 天：
     正收益次数：12262
     正收益占比：83.99%
     总的正收益：41643.30000000105
     总的负收益：-3318.3800000000006
第 3 天：
     正收益次数：12172
     正收益占比：83.37%
     总的正收益：45808.4100000005
     总的负收益：-4131.909999999999
第 4 天：
     正收益次数：12166
     正收益占比：83.35%
     总的正收益：69700.84999999896
     总的负收益：-4573.620000000013
第 5 天：
     正收益次数：12745
     正收益占比：87.32%
     总的正收益：87311.26999999897
     总的负收益：-4341.379999999993
购买类型：BSP_TYPE.T2
正收益次数：64974
正收益占比：96.66%
总的正收益：552884.089999973
总的负收益：-3800.110000000006
第 1 天：
     正收益次数：51051
     正收益占比：75.95%
     总的正收益：154790.76000001733
     总的负收益：-19915.51000000022
第 2 天：
     正收益次数：56197
     正收益占比：83.6%
     总的正收益：223743.2800000016
     总的负收益：-15341.360000000128
第 3 天：
     正收益次数：58705
     正收益占比：87.34%
     总的正收益：293615.5100000055
     总的负收益：-16334.239999999954
第 4 天：
     正收益次数：59645
     正收益占比：88.74%
     总的正收益：389019.86999997275
     总的负收益：-15701.530000000115
第 5 天：
     正收益次数：59352
     正收益占比：88.34%
     总的正收益：481013.62999999424
     总的负收益：-18032.73999999999
购买类型：BSP_TYPE.T2S
正收益次数：45337
正收益占比：95.08%
总的正收益：336097.31000000413
总的负收益：-15321.179999999958
第 1 天：
     正收益次数：38521
     正收益占比：80.81%
     总的正收益：117077.50999999722
     总的负收益：-12301.69000000008
第 2 天：
     正收益次数：39982
     正收益占比：83.88%
     总的正收益：158721.76999999565
     总的负收益：-14135.999999999962
第 3 天：
     正收益次数：40122
     正收益占比：84.19%
     总的正收益：206699.95000001317
     总的负收益：-15973.75999999987
第 4 天：
     正收益次数：38928
     正收益占比：81.86%
     总的正收益：228257.50999999343
     总的负收益：-21472.13000000003
第 5 天：
     正收益次数：38133
     正收益占比：80.69%
     总的正收益：272008.0099999982
     总的负收益：-25542.42000000008
购买类型：BSP_TYPE.T3A
正收益次数：5961
正收益占比：97.2%
总的正收益：60376.419999999904
总的负收益：-2372.940000000002
第 1 天：
     正收益次数：4646
     正收益占比：75.78%
     总的正收益：16265.640000000018
     总的负收益：-2019.4599999999746
第 2 天：
     正收益次数：5131
     正收益占比：83.69%
     总的正收益：25221.910000000084
     总的负收益：-2052.4800000000023
第 3 天：
     正收益次数：4916
     正收益占比：80.18%
     总的正收益：33281.49000000023
     总的负收益：-2847.1900000000246
第 4 天：
     正收益次数：5323
     正收益占比：87.45%
     总的正收益：42411.43000000034
     总的负收益：-2277.310000000016
第 5 天：
     正收益次数：5320
     正收益占比：88.06%
     总的正收益：50071.40000000055
     总的负收益：-3017.469999999999
购买类型：BSP_TYPE.T3B
正收益次数：4050
正收益占比：99.61%
总的正收益：47917.59999999969
总的负收益：-37.489999999999995
第 1 天：
     正收益次数：3233
     正收益占比：79.51%
     总的正收益：13297.64999999993
     总的负收益：-850.3599999999893
第 2 天：
     正收益次数：3600
     正收益占比：88.54%
     总的正收益：19811.960000000032
     总的负收益：-773.6099999999955
第 3 天：
     正收益次数：3618
     正收益占比：88.98%
     总的正收益：27250.03000000021
     总的负收益：-350.9399999999991
第 4 天：
     正收益次数：3846
     正收益占比：94.59%
     总的正收益：34070.899999999536
     总的负收益：-415.189999999999
第 5 天：
     正收益次数：3818
     正收益占比：93.9%
     总的正收益：41904.79999999964
     总的负收益：-395.1700000000006
"""
