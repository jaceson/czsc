# coding: utf-8
import os
import sys
import json
import shutil
import numpy as np
from czsc_sqlite import *
import akshare as ak
from czsc_daily_util import *
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy.interpolate import make_interp_spline
plt.rcParams["font.sans-serif"] = ["SimHei"]
plt.rcParams["axes.unicode_minus"] = False  # 正常显示负号

def output_png(code,etf_share_dict):
    # 定义数据
    x = etf_share_dict['share']['dt']
    y = etf_share_dict['share']['share']

    # 绘制原始数据
    plt.figure(figsize=(10, 5))
    plt.plot(x, y, '*-', label='Original Data')

    plt.title("{}share number 【万元】".format(code))
    plt.xlabel("X-axis")
    plt.ylabel("Y-axis")

    # 添加图例
    plt.legend()

    plt.grid(True)

    # 保存图形为文件
    pngfile = get_data_dir()+'/etf/png/'+etf_share_dict['name']+'.png'
    print(pngfile)
    plt.savefig(pngfile)  # 保存为 PNG 文件

def clear_cache(cachedir):
    if os.path.isdir(cachedir):
        shutil.rmtree(cachedir)
    os.makedirs(cachedir)

def is_asc_share(code,etf_share_dict,days=30):
    dt_list = etf_share_dict['share']['dt']
    share_list = etf_share_dict['share']['share']
    if len(share_list)<30:
        return False
    share_ratio_30 = share_list[-1]/share_list[-30]
    share_ratio_20 = share_list[-1]/share_list[-20]
    share_ratio_10 = share_list[-1]/share_list[-10]
    if share_ratio_30>1 and share_ratio_20>1 and share_ratio_10>1:
        print("【{}】{}10日份额增加：{}，20日份额增加：{}，30日份额增加：{}".format(code,etf_share_dict['name'],round(share_ratio_10,2),round(share_ratio_20,2),round(share_ratio_30,2)))
        
        close_list = ak.fund_etf_fund_info_em('588300','20250101','20250307')
        return True
    
    return False

def main():
    # close_list = ak.fund_etf_fund_info_em('588300','20250101','20250307')
    # close_list = query_trade_data_to_pd(close_list)
    # print(close_list)
    # 清除etf缓存
    cachedir = get_data_dir()+'/etf/png/'
    clear_cache(cachedir)
    # etf场内份额
    etf_share_list = get_etf_share(dt='2025-01-01')
    for code in etf_share_list.keys():
        etf_share_dict = etf_share_list[code]
        if is_asc_share(code,etf_share_dict):
            output_png(code,etf_share_dict)
"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()