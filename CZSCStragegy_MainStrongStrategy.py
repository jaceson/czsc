# coding: utf-8
import os
import sys
import time
from datetime import datetime, timedelta
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs
from czsc.utils.sig import get_zs_seq
from czsc.analyze import *
from czsc.enum import *
from czsc_sqlite import get_local_stock_data,get_local_stock_bars
from CZSCStragegy_AllStrategy import get_main_strong_join_condition

plus_list = []
minus_list = []
hold_days = 5
ratio_map = {}
for x in range(1,hold_days+1):
    ratio_map[x] = []

# 添加中枢相关的统计变量
zs_in_stats = {'count': 0, 'plus_list': [], 'minus_list': []}
zs_out_stats = {
    'above_zs': {
        'within_10pct': {'count': 0, 'plus_list': [], 'minus_list': []},  # 高于中枢10%以内
        'beyond_10pct': {'count': 0, 'plus_list': [], 'minus_list': []}   # 高于中枢10%以外
    },
    'below_zs': {
        'within_20pct': {'count': 0, 'plus_list': [], 'minus_list': []},  # 低于中枢20%以内
        'beyond_20pct': {'count': 0, 'plus_list': [], 'minus_list': []}   # 低于中枢20%以外
    }
}

def is_date_in_zs_interval(buy_date, zs_list, df):
    """
    判断buy_date相对于中枢的位置，进一步细化分类
    
    优化逻辑：
    1. buy_date必须在中枢开始时间(sdt)和结束时间(edt)之后
    2. 选择最靠近buy_date的中枢
    3. 如果找不到满足条件的中枢，返回'no_zs'
    
    Args:
        buy_date: 买入日期
        zs_list: 中枢列表
        df: 股票数据DataFrame
    
    Returns:
        tuple: (位置类型, 位置信息)
        位置类型: 
        - 'in_zs' - 在中枢内
        - 'above_zs_within_10pct' - 高于中枢10%以内
        - 'above_zs_beyond_10pct' - 高于中枢10%以外
        - 'below_zs_within_20pct' - 低于中枢20%以内
        - 'below_zs_beyond_20pct' - 低于中枢20%以外
        - 'no_zs' - 无有效中枢
    """
    if not zs_list:
        return 'no_zs', None
    
    # 找到buy_date在df中的索引
    try:
        date_idx = df[df['date'] == buy_date].index[0]
    except IndexError:
        return 'no_zs', None
    
    # 获取该日期的收盘价
    close_price = df.loc[date_idx, 'close']
    
    # 过滤出满足时间条件的中枢：buy_date必须在中枢结束时间之后
    valid_zs_list = []
    for zs in zs_list:
        if not zs.is_valid:
            continue
            
        # 将中枢的结束时间转换为字符串格式进行比较
        zs_end_date = zs.edt.strftime("%Y-%m-%d") if hasattr(zs.edt, 'strftime') else str(zs.edt)
        
        # 检查buy_date是否在中枢结束时间之后
        if buy_date > zs_end_date:
            valid_zs_list.append(zs)
    
    if not valid_zs_list:
        return 'no_zs', None
    
    # 找到最靠近buy_date的中枢（按时间距离排序）
    def get_date_distance(zs):
        """计算中枢结束时间与buy_date的时间距离"""
        zs_end_date = zs.edt.strftime("%Y-%m-%d") if hasattr(zs.edt, 'strftime') else str(zs.edt)
        # 将日期转换为datetime对象计算距离
        try:
            zs_end_dt = datetime.strptime(zs_end_date, "%Y-%m-%d")
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d")
            return abs((buy_dt - zs_end_dt).days)
        except:
            return float('inf')
    
    # 按时间距离排序，选择最靠近的中枢
    valid_zs_list.sort(key=get_date_distance)
    closest_zs = valid_zs_list[0]
    
    # 检查价格相对于最靠近中枢的位置
    if closest_zs.zd <= close_price <= closest_zs.zg:
        return 'in_zs', {
            'zs': closest_zs,
            'close_price': close_price,
            'zs_zd': closest_zs.zd,
            'zs_zg': closest_zs.zg,
            'zs_zz': closest_zs.zz,
            'zs_sdt': closest_zs.sdt,
            'zs_edt': closest_zs.edt,
            'position': 'in_zs'
        }
    elif close_price > closest_zs.zg:
        # 计算距离中枢上沿的百分比
        distance_pct = (close_price - closest_zs.zg) / closest_zs.zg * 100
        if distance_pct <= 10:
            return 'above_zs_within_10pct', {
                'zs': closest_zs,
                'close_price': close_price,
                'zs_zd': closest_zs.zd,
                'zs_zg': closest_zs.zg,
                'zs_zz': closest_zs.zz,
                'zs_sdt': closest_zs.sdt,
                'zs_edt': closest_zs.edt,
                'position': 'above_zs_within_10pct',
                'distance_from_zs': close_price - closest_zs.zg,
                'distance_pct': distance_pct
            }
        else:
            return 'above_zs_beyond_10pct', {
                'zs': closest_zs,
                'close_price': close_price,
                'zs_zd': closest_zs.zd,
                'zs_zg': closest_zs.zg,
                'zs_zz': closest_zs.zz,
                'zs_sdt': closest_zs.sdt,
                'zs_edt': closest_zs.edt,
                'position': 'above_zs_beyond_10pct',
                'distance_from_zs': close_price - closest_zs.zg,
                'distance_pct': distance_pct
            }
    elif close_price <= closest_zs.zd:
        # 计算距离中枢下沿的百分比
        distance_pct = (closest_zs.zd - close_price) / closest_zs.zd * 100
        if distance_pct <= 20:
            return 'below_zs_within_20pct', {
                'zs': closest_zs,
                'close_price': close_price,
                'zs_zd': closest_zs.zd,
                'zs_zg': closest_zs.zg,
                'zs_zz': closest_zs.zz,
                'zs_sdt': closest_zs.sdt,
                'zs_edt': closest_zs.edt,
                'position': 'below_zs_within_20pct',
                'distance_from_zs': closest_zs.zd - close_price,
                'distance_pct': distance_pct
            }
        else:
            return 'below_zs_beyond_20pct', {
                'zs': closest_zs,
                'close_price': close_price,
                'zs_zd': closest_zs.zd,
                'zs_zg': closest_zs.zg,
                'zs_zz': closest_zs.zz,
                'zs_sdt': closest_zs.sdt,
                'zs_edt': closest_zs.edt,
                'position': 'below_zs_beyond_20pct',
                'distance_from_zs': closest_zs.zd - close_price,
                'distance_pct': distance_pct
            }
    
    return 'no_zs', None

def get_zs_and_bi_info(buy_date, bi_list, df):
    """
    获取buy_date所在的中枢和笔信息
    
    Args:
        buy_date: 买入日期（字符串格式）
        bi_list: 笔列表
        df: 股票数据DataFrame（date列为字符串）
    
    Returns:
        tuple: (笔对象, 是否找到)
    """
    if not bi_list:
        return None, False
    
    try:
        date_idx = df[df['date'] == buy_date].index[0]
    except IndexError:
        return None, False

    for bi in bi_list:
        # 将bi.fx_a.dt和bi.fx_b.dt转换为字符串格式进行比较
        bi_start_date = bi.fx_a.dt.strftime("%Y-%m-%d") if hasattr(bi.fx_a.dt, 'strftime') else str(bi.fx_a.dt)
        bi_end_date = bi.fx_b.dt.strftime("%Y-%m-%d") if hasattr(bi.fx_b.dt, 'strftime') else str(bi.fx_b.dt)
        
        # 检查buy_date是否在笔的时间范围内
        if bi_start_date <= buy_date <= bi_end_date:
            return bi, True
    
    return None, False

def is_same_zs_bi(last_buy_date, current_buy_date, bi_list, df):
    """
    检查两个购买日期是否在同一个中枢的同一笔内
    
    Args:
        last_buy_date: 上次购买日期（字符串格式）
        current_buy_date: 本次购买日期（字符串格式）
        bi_list: 笔列表
        df: 股票数据DataFrame（date列为字符串）
    
    Returns:
        bool: True表示在同一个中枢的同一笔内，False表示不在
    """
    if not last_buy_date or not current_buy_date:
        return False
    
    # 获取上次购买的笔信息
    last_bi, last_found = get_zs_and_bi_info(last_buy_date, bi_list, df)
    if not last_found:
        return False
    
    # 获取本次购买的笔信息
    current_bi, current_found = get_zs_and_bi_info(current_buy_date, bi_list, df)
    if not current_found:
        return False
    
    # 检查是否在同一个中枢的同一笔内
    # 将datetime转换为字符串进行比较
    last_start_date = last_bi.fx_a.dt.strftime("%Y-%m-%d") if hasattr(last_bi.fx_a.dt, 'strftime') else str(last_bi.fx_a.dt)
    last_end_date = last_bi.fx_b.dt.strftime("%Y-%m-%d") if hasattr(last_bi.fx_b.dt, 'strftime') else str(last_bi.fx_b.dt)
    curr_start_date = current_bi.fx_a.dt.strftime("%Y-%m-%d") if hasattr(current_bi.fx_a.dt, 'strftime') else str(current_bi.fx_a.dt)
    curr_end_date = current_bi.fx_b.dt.strftime("%Y-%m-%d") if hasattr(current_bi.fx_b.dt, 'strftime') else str(current_bi.fx_b.dt)
    
    if (last_start_date == curr_start_date and last_end_date == curr_end_date):
        return True
    
    return False

'''
    主力进场指标
'''
def get_main_strong_join_buy_point(symbol,df):
    last_start_index = -1
    last_buy_date = None  # 记录上次购买日期
    buy_con = get_main_strong_join_condition(symbol=symbol,df=df,max_ratio=7,min_ratio=3,rsi_limit=70,days_delta=3)
    bars = get_local_stock_bars(symbol=symbol,df=df)
    c = CZSC(bars, get_signals=None)
    bi_list = c.bi_list
    if len(bi_list) <= 0:
        return
    zs_list = get_zs_seq(bi_list)
    if not df[buy_con].empty:
        selected_indexs = df[buy_con].index
        for idx in selected_indexs:
            buy_date = df['date'][idx]
            start_index = df.iloc[df['date'].values == buy_date].index[0]
            if last_start_index>0 and (start_index-last_start_index)<=hold_days:
                continue
            
            # 检查是否在同一个中枢的同一笔内
            if last_buy_date and is_same_zs_bi(last_buy_date, buy_date, bi_list, df):
                print(f"{symbol} 跳过购买 - {buy_date} 与上次购买日期 {last_buy_date} 在同一个中枢的同一笔内")
                continue
            
            # 判断buy_date是否在中枢区间内
            position_type, zs_info = is_date_in_zs_interval(buy_date, zs_list, df)
            
            print(symbol+" 主力进场日期："+buy_date)
            if position_type == 'in_zs':
                print(f"  ✓ 在中枢区间内 - 中枢区间[{zs_info['zs_zd']:.2f}, {zs_info['zs_zg']:.2f}], 收盘价:{zs_info['close_price']:.2f}")
                print(f"     中枢时间范围: {zs_info['zs_sdt']} 到 {zs_info['zs_edt']}")
                zs_in_stats['count'] += 1
            elif position_type == 'above_zs_within_10pct':
                print(f"  ✓ 高于中枢10%以内 - 中枢区间[{zs_info['zs_zd']:.2f}, {zs_info['zs_zg']:.2f}], 收盘价:{zs_info['close_price']:.2f}, 距离上沿:{zs_info['distance_from_zs']:.2f}")
                zs_out_stats['above_zs']['within_10pct']['count'] += 1
            elif position_type == 'above_zs_beyond_10pct':
                print(f"  ✓ 高于中枢10%以外 - 中枢区间[{zs_info['zs_zd']:.2f}, {zs_info['zs_zg']:.2f}], 收盘价:{zs_info['close_price']:.2f}, 距离上沿:{zs_info['distance_from_zs']:.2f}")
                zs_out_stats['above_zs']['beyond_10pct']['count'] += 1
            elif position_type == 'below_zs_within_20pct':
                print(f"  ✓ 低于中枢20%以内 - 中枢区间[{zs_info['zs_zd']:.2f}, {zs_info['zs_zg']:.2f}], 收盘价:{zs_info['close_price']:.2f}, 距离下沿:{zs_info['distance_from_zs']:.2f}")
                zs_out_stats['below_zs']['within_20pct']['count'] += 1
            elif position_type == 'below_zs_beyond_20pct':
                print(f"  ✓ 低于中枢20%以外 - 中枢区间[{zs_info['zs_zd']:.2f}, {zs_info['zs_zg']:.2f}], 收盘价:{zs_info['close_price']:.2f}, 距离下沿:{zs_info['distance_from_zs']:.2f}")
                zs_out_stats['below_zs']['beyond_20pct']['count'] += 1
            else:
                print(f"  ✗ 无有效中枢信息")
            
            buy_price = df['close'].iloc[start_index]
            max_val = -1000
            last_start_index = start_index
            last_buy_date = buy_date  # 更新上次购买日期
            
            for idx in range(start_index+1,start_index+hold_days+1):
                if idx<len(df['date']):
                    stock_close = df['close'].iloc[idx]
                    ratio = round(100*(stock_close-buy_price)/buy_price,2)
                    ratio_map[idx-start_index].append(ratio)
                    max_val = max(max_val,ratio)

            if max_val>0:
                plus_list.append(max_val)
                if position_type == 'in_zs':
                    zs_in_stats['plus_list'].append(max_val)
                elif position_type == 'above_zs_within_10pct':
                    zs_out_stats['above_zs']['within_10pct']['plus_list'].append(max_val)
                elif position_type == 'above_zs_beyond_10pct':
                    zs_out_stats['above_zs']['beyond_10pct']['plus_list'].append(max_val)
                elif position_type == 'below_zs_within_20pct':
                    zs_out_stats['below_zs']['within_20pct']['plus_list'].append(max_val)
                elif position_type == 'below_zs_beyond_20pct':
                    zs_out_stats['below_zs']['beyond_20pct']['plus_list'].append(max_val)
            else:
                minus_list.append(max_val)
                if position_type == 'in_zs':
                    zs_in_stats['minus_list'].append(max_val)
                elif position_type == 'above_zs_within_10pct':
                    zs_out_stats['above_zs']['within_10pct']['minus_list'].append(max_val)
                elif position_type == 'above_zs_beyond_10pct':
                    zs_out_stats['above_zs']['beyond_10pct']['minus_list'].append(max_val)
                elif position_type == 'below_zs_within_20pct':
                    zs_out_stats['below_zs']['within_20pct']['minus_list'].append(max_val)
                elif position_type == 'below_zs_beyond_20pct':
                    zs_out_stats['below_zs']['beyond_20pct']['minus_list'].append(max_val)

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

def print_zs_analysis():
    """打印中枢分析结果"""
    print("\n" + "="*60)
    print("中枢区间分析结果（细化版）")
    print("="*60)
    
    # 中枢内统计
    print(f"中枢内买入次数: {zs_in_stats['count']}")
    if zs_in_stats['count'] > 0:
        zs_in_plus = len(zs_in_stats['plus_list'])
        zs_in_minus = len(zs_in_stats['minus_list'])
        zs_in_total = zs_in_plus + zs_in_minus
        if zs_in_total > 0:
            print(f"中枢内正收益次数: {zs_in_plus}")
            print(f"中枢内负收益次数: {zs_in_minus}")
            print(f"中枢内正收益占比: {round(100*zs_in_plus/zs_in_total, 2)}%")
            
            if zs_in_plus > 0:
                zs_in_plus_avg = sum(zs_in_stats['plus_list']) / zs_in_plus
                print(f"中枢内平均正收益: {zs_in_plus_avg:.2f}%")
            if zs_in_minus > 0:
                zs_in_minus_avg = sum(zs_in_stats['minus_list']) / zs_in_minus
                print(f"中枢内平均负收益: {zs_in_minus_avg:.2f}%")
    
    # 高于中枢统计 - 10%以内
    print(f"\n高于中枢10%以内买入次数: {zs_out_stats['above_zs']['within_10pct']['count']}")
    if zs_out_stats['above_zs']['within_10pct']['count'] > 0:
        zs_above_within_plus = len(zs_out_stats['above_zs']['within_10pct']['plus_list'])
        zs_above_within_minus = len(zs_out_stats['above_zs']['within_10pct']['minus_list'])
        zs_above_within_total = zs_above_within_plus + zs_above_within_minus
        if zs_above_within_total > 0:
            print(f"高于中枢10%以内正收益次数: {zs_above_within_plus}")
            print(f"高于中枢10%以内负收益次数: {zs_above_within_minus}")
            print(f"高于中枢10%以内正收益占比: {round(100*zs_above_within_plus/zs_above_within_total, 2)}%")
            
            if zs_above_within_plus > 0:
                zs_above_within_plus_avg = sum(zs_out_stats['above_zs']['within_10pct']['plus_list']) / zs_above_within_plus
                print(f"高于中枢10%以内平均正收益: {zs_above_within_plus_avg:.2f}%")
            if zs_above_within_minus > 0:
                zs_above_within_minus_avg = sum(zs_out_stats['above_zs']['within_10pct']['minus_list']) / zs_above_within_minus
                print(f"高于中枢10%以内平均负收益: {zs_above_within_minus_avg:.2f}%")
    
    # 高于中枢统计 - 10%以外
    print(f"\n高于中枢10%以外买入次数: {zs_out_stats['above_zs']['beyond_10pct']['count']}")
    if zs_out_stats['above_zs']['beyond_10pct']['count'] > 0:
        zs_above_beyond_plus = len(zs_out_stats['above_zs']['beyond_10pct']['plus_list'])
        zs_above_beyond_minus = len(zs_out_stats['above_zs']['beyond_10pct']['minus_list'])
        zs_above_beyond_total = zs_above_beyond_plus + zs_above_beyond_minus
        if zs_above_beyond_total > 0:
            print(f"高于中枢10%以外正收益次数: {zs_above_beyond_plus}")
            print(f"高于中枢10%以外负收益次数: {zs_above_beyond_minus}")
            print(f"高于中枢10%以外正收益占比: {round(100*zs_above_beyond_plus/zs_above_beyond_total, 2)}%")
            
            if zs_above_beyond_plus > 0:
                zs_above_beyond_plus_avg = sum(zs_out_stats['above_zs']['beyond_10pct']['plus_list']) / zs_above_beyond_plus
                print(f"高于中枢10%以外平均正收益: {zs_above_beyond_plus_avg:.2f}%")
            if zs_above_beyond_minus > 0:
                zs_above_beyond_minus_avg = sum(zs_out_stats['above_zs']['beyond_10pct']['minus_list']) / zs_above_beyond_minus
                print(f"高于中枢10%以外平均负收益: {zs_above_beyond_minus_avg:.2f}%")
    
    # 低于中枢统计 - 20%以内
    print(f"\n低于中枢20%以内买入次数: {zs_out_stats['below_zs']['within_20pct']['count']}")
    if zs_out_stats['below_zs']['within_20pct']['count'] > 0:
        zs_below_within_plus = len(zs_out_stats['below_zs']['within_20pct']['plus_list'])
        zs_below_within_minus = len(zs_out_stats['below_zs']['within_20pct']['minus_list'])
        zs_below_within_total = zs_below_within_plus + zs_below_within_minus
        if zs_below_within_total > 0:
            print(f"低于中枢20%以内正收益次数: {zs_below_within_plus}")
            print(f"低于中枢20%以内负收益次数: {zs_below_within_minus}")
            print(f"低于中枢20%以内正收益占比: {round(100*zs_below_within_plus/zs_below_within_total, 2)}%")
            
            if zs_below_within_plus > 0:
                zs_below_within_plus_avg = sum(zs_out_stats['below_zs']['within_20pct']['plus_list']) / zs_below_within_plus
                print(f"低于中枢20%以内平均正收益: {zs_below_within_plus_avg:.2f}%")
            if zs_below_within_minus > 0:
                zs_below_within_minus_avg = sum(zs_out_stats['below_zs']['within_20pct']['minus_list']) / zs_below_within_minus
                print(f"低于中枢20%以内平均负收益: {zs_below_within_minus_avg:.2f}%")
    
    # 低于中枢统计 - 20%以外
    print(f"\n低于中枢20%以外买入次数: {zs_out_stats['below_zs']['beyond_20pct']['count']}")
    if zs_out_stats['below_zs']['beyond_20pct']['count'] > 0:
        zs_below_beyond_plus = len(zs_out_stats['below_zs']['beyond_20pct']['plus_list'])
        zs_below_beyond_minus = len(zs_out_stats['below_zs']['beyond_20pct']['minus_list'])
        zs_below_beyond_total = zs_below_beyond_plus + zs_below_beyond_minus
        if zs_below_beyond_total > 0:
            print(f"低于中枢20%以外正收益次数: {zs_below_beyond_plus}")
            print(f"低于中枢20%以外负收益次数: {zs_below_beyond_minus}")
            print(f"低于中枢20%以外正收益占比: {round(100*zs_below_beyond_plus/zs_below_beyond_total, 2)}%")
            
            if zs_below_beyond_plus > 0:
                zs_below_beyond_plus_avg = sum(zs_out_stats['below_zs']['beyond_20pct']['plus_list']) / zs_below_beyond_plus
                print(f"低于中枢20%以外平均正收益: {zs_below_beyond_plus_avg:.2f}%")
            if zs_below_beyond_minus > 0:
                zs_below_beyond_minus_avg = sum(zs_out_stats['below_zs']['beyond_20pct']['minus_list']) / zs_below_beyond_minus
                print(f"低于中枢20%以外平均负收益: {zs_below_beyond_minus_avg:.2f}%")
    
    # 总体对比
    total_in = zs_in_stats['count']
    total_above_within = zs_out_stats['above_zs']['within_10pct']['count']
    total_above_beyond = zs_out_stats['above_zs']['beyond_10pct']['count']
    total_below_within = zs_out_stats['below_zs']['within_20pct']['count']
    total_below_beyond = zs_out_stats['below_zs']['beyond_20pct']['count']
    total_all = total_in + total_above_within + total_above_beyond + total_below_within + total_below_beyond
    
    if total_all > 0:
        print(f"\n总体对比:")
        print(f"中枢内买入占比: {round(100*total_in/total_all, 2)}%")
        print(f"高于中枢10%以内买入占比: {round(100*total_above_within/total_all, 2)}%")
        print(f"高于中枢10%以外买入占比: {round(100*total_above_beyond/total_all, 2)}%")
        print(f"低于中枢20%以内买入占比: {round(100*total_below_within/total_all, 2)}%")
        print(f"低于中枢20%以外买入占比: {round(100*total_below_beyond/total_all, 2)}%")
        
        # 收益表现对比
        print(f"\n收益表现对比:")
        if total_in > 0:
            zs_in_ratio = len([x for x in zs_in_stats['plus_list'] + zs_in_stats['minus_list'] if x > 0]) / (len(zs_in_stats['plus_list']) + len(zs_in_stats['minus_list'])) * 100
            print(f"中枢内正收益占比: {round(zs_in_ratio, 2)}%")
        
        if total_above_within > 0:
            zs_above_within_ratio = len([x for x in zs_out_stats['above_zs']['within_10pct']['plus_list'] + zs_out_stats['above_zs']['within_10pct']['minus_list'] if x > 0]) / (len(zs_out_stats['above_zs']['within_10pct']['plus_list']) + len(zs_out_stats['above_zs']['within_10pct']['minus_list'])) * 100
            print(f"高于中枢10%以内正收益占比: {round(zs_above_within_ratio, 2)}%")
        
        if total_above_beyond > 0:
            zs_above_beyond_ratio = len([x for x in zs_out_stats['above_zs']['beyond_10pct']['plus_list'] + zs_out_stats['above_zs']['beyond_10pct']['minus_list'] if x > 0]) / (len(zs_out_stats['above_zs']['beyond_10pct']['plus_list']) + len(zs_out_stats['above_zs']['beyond_10pct']['minus_list'])) * 100
            print(f"高于中枢10%以外正收益占比: {round(zs_above_beyond_ratio, 2)}%")
        
        if total_below_within > 0:
            zs_below_within_ratio = len([x for x in zs_out_stats['below_zs']['within_20pct']['plus_list'] + zs_out_stats['below_zs']['within_20pct']['minus_list'] if x > 0]) / (len(zs_out_stats['below_zs']['within_20pct']['plus_list']) + len(zs_out_stats['below_zs']['within_20pct']['minus_list'])) * 100
            print(f"低于中枢20%以内正收益占比: {round(zs_below_within_ratio, 2)}%")
        
        if total_below_beyond > 0:
            zs_below_beyond_ratio = len([x for x in zs_out_stats['below_zs']['beyond_20pct']['plus_list'] + zs_out_stats['below_zs']['beyond_20pct']['minus_list'] if x > 0]) / (len(zs_out_stats['below_zs']['beyond_20pct']['plus_list']) + len(zs_out_stats['below_zs']['beyond_20pct']['minus_list'])) * 100
            print(f"低于中枢20%以外正收益占比: {round(zs_below_beyond_ratio, 2)}%")

if __name__ == '__main__':
    all_symbols  = get_daily_symbols()
    for symbol in all_symbols:
        # 打印进度
        print("进度：{} / {}".format(all_symbols.index(symbol),len(all_symbols)))
        df = get_local_stock_data(symbol,'2020-01-01')
        get_main_strong_join_buy_point(symbol,df)

        # 分阶段打印统计结果
        if all_symbols.index(symbol)==1000 or all_symbols.index(symbol)==2000 or all_symbols.index(symbol)==3000:
            print_console(plus_list,minus_list,ratio_map)
            print_zs_analysis()

    print_console(plus_list,minus_list,ratio_map)
    print_zs_analysis()

'''
正收益次数：10119
正收益占比：69.5%
总的正收益：108204.38999999997
总的负收益：-18685.739999999994
第 1 天：
     正收益次数：7214
     正收益占比：49.56%
     总的正收益：40102.05999999985
     总的负收益：-27510.260000000013
第 2 天：
     正收益次数：6560
     正收益占比：45.09%
     总的正收益：51245.41000000004
     总的负收益：-40368.79999999993
第 3 天：
     正收益次数：6370
     正收益占比：43.8%
     总的正收益：57577.33000000015
     总的负收益：-49804.40999999984
第 4 天：
     正收益次数：6164
     正收益占比：42.43%
     总的正收益：62243.2599999999
     总的负收益：-57102.79000000006
第 5 天：
     正收益次数：6005
     正收益占比：41.36%
     总的正收益：65265.48000000014
     总的负收益：-62587.810000000034

============================================================
中枢区间分析结果（细化版）
============================================================
中枢内买入次数: 628
中枢内正收益次数: 467
中枢内负收益次数: 161
中枢内正收益占比: 74.36%
中枢内平均正收益: 12.38%
中枢内平均负收益: -3.48%

高于中枢10%以内买入次数: 630
高于中枢10%以内正收益次数: 459
高于中枢10%以内负收益次数: 171
高于中枢10%以内正收益占比: 72.86%
高于中枢10%以内平均正收益: 10.54%
高于中枢10%以内平均负收益: -2.88%

高于中枢10%以外买入次数: 3579
高于中枢10%以外正收益次数: 2387
高于中枢10%以外负收益次数: 1192
高于中枢10%以外正收益占比: 66.69%
高于中枢10%以外平均正收益: 11.46%
高于中枢10%以外平均负收益: -6.21%

低于中枢20%以内买入次数: 661
低于中枢20%以内正收益次数: 495
低于中枢20%以内负收益次数: 166
低于中枢20%以内正收益占比: 74.89%
低于中枢20%以内平均正收益: 11.77%
低于中枢20%以内平均负收益: -3.47%

低于中枢20%以外买入次数: 101
低于中枢20%以外正收益次数: 78
低于中枢20%以外负收益次数: 23
低于中枢20%以外正收益占比: 77.23%
低于中枢20%以外平均正收益: 15.46%
低于中枢20%以外平均负收益: -3.49%

总体对比:
中枢内买入占比: 11.22%
高于中枢10%以内买入占比: 11.25%
高于中枢10%以外买入占比: 63.92%
低于中枢20%以内买入占比: 11.81%
低于中枢20%以外买入占比: 1.8%

收益表现对比:
中枢内正收益占比: 74.36%
高于中枢10%以内正收益占比: 72.86%
高于中枢10%以外正收益占比: 66.69%
低于中枢20%以内正收益占比: 74.89%
低于中枢20%以外正收益占比: 77.23%
'''