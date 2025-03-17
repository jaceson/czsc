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

START_DATE = "2024-06-01"
def plot_data(ax, x, y, title, xlabel, ylabel, label, rotation=45):
    """
    绘制数据并设置图表属性。
    """
    ax.plot(x, y, '*-', label=label)
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    # 确保最后一个数据点始终显示
    if len(x) > 10:
        ticks = x[::10]  # 每10个日期显示一个标签
        ticks = np.append(ticks, x[-1])  # 添加最后一个数据点
    else:
        ticks = x  # 如果数据点少于10个，显示所有标签
    ax.set_xticks(ticks)  # 设置刻度位置
    ax.set_xticklabels(ticks, rotation=rotation, ha='right')  # 旋转 x 轴标签，避免重叠
    ax.legend()

def output_png(code, etf_share_dict, etf_price_dict):
    # 定义数据
    share_x = etf_share_dict['share']['dt']
    share_y = etf_share_dict['share']['share']
    price_x = etf_price_dict['dt']
    price_y = etf_price_dict['close']

    # 创建图形和子图
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(15, 10))

    # 绘制场内份额数据
    plot_data(ax1, share_x, share_y, '【{}】场内份额【单位：万份】'.format(code), '日期', '场内份额', '份额')

    # 绘制单位净值数据
    plot_data(ax2, price_x, price_y, '【{}】单位净值'.format(code), '日期', '单位净值', '净值')

    # 调整布局
    plt.tight_layout()
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
        return False,None
    share_ratio_30 = share_list[-1]/share_list[-30]
    share_ratio_20 = share_list[-1]/share_list[-20]
    share_ratio_10 = share_list[-1]/share_list[-10]
    if share_ratio_30>1 and share_ratio_20>1 and share_ratio_10>1 and share_ratio_30>min_ratio:
        print("【{}】{}  10日份额增加：{}，20日份额增加：{}，30日份额增加：{}".format(code,etf_share_dict['name'],round(share_ratio_10,2),round(share_ratio_20,2),round(share_ratio_30,2)))
        data_list = ak.fund_etf_fund_info_em(code,START_DATE.replace('-',''),dt_list[-1].replace('-',''))
        if len(data_list)<30:
            return False,None
        close_list = data_list['单位净值'].tolist()
        close_ratio_30 = close_list[-1]/close_list[-30]
        close_ratio_20 = close_list[-1]/close_list[-20]
        close_ratio_10 = close_list[-1]/close_list[-10]
        if close_ratio_30<share_ratio_30 and close_ratio_20<share_ratio_20 and close_ratio_10<share_ratio_10:
            print(START_DATE.replace('-',''),dt_list[-1].replace('-',''))
            return True,{'dt':data_list['净值日期'].tolist(),'close':close_list}
    return False,None

def main():
    # 清除etf缓存
    cachedir = get_data_dir()+'/etf/png/'
    clear_cache(cachedir)
    # etf场内份额
    etf_share_list = get_etf_share(dt=START_DATE)
    for code in etf_share_list.keys():
        etf_share_dict = etf_share_list[code]
        is_valid,close_list = is_asc_share(code,etf_share_dict)
        if is_valid:
            output_png(code,etf_share_dict,close_list)
"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()