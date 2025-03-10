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
    plt.figure(figsize=(15, 5))
    plt.plot(x, y, '*-', label='场内份额【单位：万份】')

    # plt.xticks(np.arange(min(x), max(x) + 1, 1))  # 每 1 个单位取一个刻度
    plt.xticks(rotation=45)  # 旋转 x 轴标签，避免重叠

    plt.title("{}".format(code))
    plt.xlabel("日期")
    plt.ylabel("场内份额")

    # 添加图例
    plt.legend()

    plt.grid(True)

    # 保存图形为文件
    pngfile = get_data_dir()+'/etf/png/'+etf_share_dict['name']+'.png'
    plt.savefig(pngfile)  # 保存为 PNG 文件

    plt.close()

def clear_cache(cachedir):
    if os.path.isdir(cachedir):
        shutil.rmtree(cachedir)
    os.makedirs(cachedir)

def is_asc_share(code,etf_share_dict,days=30,min_ratio=1.5):
    dt_list = etf_share_dict['share']['dt']
    share_list = etf_share_dict['share']['share']
    if len(share_list)<30:
        return False
    share_ratio_30 = share_list[-1]/share_list[-30]
    share_ratio_20 = share_list[-1]/share_list[-20]
    share_ratio_10 = share_list[-1]/share_list[-10]
    if share_ratio_30>1 and share_ratio_20>1 and share_ratio_10>1 and share_ratio_30>min_ratio:
        print("【{}】{}  10日份额增加：{}，20日份额增加：{}，30日份额增加：{}".format(code,etf_share_dict['name'],round(share_ratio_10,2),round(share_ratio_20,2),round(share_ratio_30,2)))
        data_list = ak.fund_etf_fund_info_em(code,dt_list[-30].replace('-',''),dt_list[-1].replace('-',''))
        if len(data_list)<30:
            return True
        close_list = data_list['单位净值'].tolist()
        close_ratio_30 = close_list[-1]/close_list[-30]
        close_ratio_20 = close_list[-1]/close_list[-20]
        close_ratio_10 = close_list[-1]/close_list[-10]
        if close_ratio_30<share_ratio_30 and close_ratio_20<share_ratio_20 and close_ratio_10<share_ratio_10:
            return True
    return False

def main():
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