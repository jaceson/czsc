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
import pandas as pd

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

def output_png(code, etf_share_dict, etf_price_dict, cachedir):
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
    pngfile = cachedir+etf_share_dict['name']+'【'+code+'】'+'.png'
    plt.savefig(pngfile)  # 保存为 PNG 文件

    plt.close()

def clear_cache(cachedir):
    if os.path.isdir(cachedir):
        shutil.rmtree(cachedir)
    os.makedirs(cachedir)

def _fetch_fund_info_em(code, start_date, end_date):
    """获取ETF基金净值信息，无数据或异常时返回 None。"""
    try:
        df = ak.fund_etf_fund_info_em(code, start_date, end_date)
        if df is None or len(df) == 0:
            return None
        return df
    except (ValueError, Exception):
        return None


def is_asc_share(code,etf_share_dict,days=30,min_ratio=1.5):
    dt_list = etf_share_dict['share']['dt']
    share_list = etf_share_dict['share']['share']
    if len(share_list)<30:
        return False,None
    share_ratio_30 = share_list[-1]/share_list[-30]
    share_ratio_20 = share_list[-1]/share_list[-20]
    share_ratio_10 = share_list[-1]/share_list[-10]

    start_str = START_DATE.replace('-','')
    end_str = dt_list[-1].replace('-','')
    data_list = _fetch_fund_info_em(code, start_str, end_str)
    if data_list is None or len(data_list) < 30:
        return False, None

    close_list = data_list['单位净值'].tolist()
    close_data = {'dt': data_list['净值日期'].tolist(), 'close': close_list}

    if share_ratio_30>1 and share_ratio_20>1 and share_ratio_10>1 and share_ratio_30>min_ratio:
        print("【{}】{}  10日份额增加：{}，20日份额增加：{}，30日份额增加：{}".format(code,etf_share_dict['name'],round(share_ratio_10,2),round(share_ratio_20,2),round(share_ratio_30,2)))
        close_ratio_30 = close_list[-1]/close_list[-30]
        close_ratio_20 = close_list[-1]/close_list[-20]
        close_ratio_10 = close_list[-1]/close_list[-10]
        if close_ratio_30<share_ratio_30 and close_ratio_20<share_ratio_20 and close_ratio_10<share_ratio_10:
            print(start_str, end_str)
            return True, close_data
        return False, close_data
    return False, close_data

def output_etf_share_change_excel(output_dir=None):
    """
    输出 ETF 份额变化 Excel 文件
    按份额变化排序：从增加最多到缩减最多
    包含字段：ETF 代码、名称、当前份额、前一天份额、份额变化
    只保留前 10 条（增加最多）和后 10 条（缩减最多）数据
    """
    if output_dir is None:
        output_dir = get_data_dir() + '/etf/'
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 获取所有 ETF 份额数据
    etf_share_list = get_etf_share(dt=START_DATE)
    
    # 构建数据列表
    data_list = []
    for code, etf_share_dict in etf_share_list.items():
        share_dt = etf_share_dict['share']['dt']
        share_data = etf_share_dict['share']['share']
        
        if len(share_data) < 2:
            continue
        
        # 当前份额（最后一个数据）
        current_share = share_data[-1]
        # 前一天份额（倒数第二个数据）
        prev_share = share_data[-2]
        # 份额变化
        share_change = current_share - prev_share
        
        data_list.append({
            'ETF 代码': code,
            'ETF 名称': etf_share_dict['name'],
            '当前日期': share_dt[-1],
            '当前份额 (万份)': current_share,
            '前一天份额 (万份)': prev_share,
            '份额变化 (万份)': share_change
        })
    
    # 转换为 DataFrame
    df = pd.DataFrame(data_list)
    
    # 按份额变化降序排序（从增加最多到缩减最多）
    df = df.sort_values(by='份额变化 (万份)', ascending=False)
    
    # 只保留前 10 条和后 10 条
    if len(df) > 20:
        top_10 = df.head(10)
        bottom_10 = df.tail(10)
        df_filtered = pd.concat([top_10, bottom_10])
    else:
        df_filtered = df
    
    # 生成输出文件名
    output_file = os.path.join(output_dir, 'ETF 份额变化排名 TOP20.xlsx')
    
    # 导出到 Excel
    df_filtered.to_excel(output_file, index=False)
    
    print("=" * 80)
    print("ETF 份额变化排名 TOP20 已导出至：{}".format(output_file))
    print("=" * 80)
    print("【前 10 名】份额增加最多的 ETF：")
    print("-" * 80)
    print(df_filtered.head(10).to_string(index=False))
    print("\n" + "=" * 80)
    print("【后 10 名】份额缩减最多的 ETF：")
    print("-" * 80)
    print(df_filtered.tail(10).to_string(index=False))
    print("=" * 80)
    
    return df_filtered

def output_national_team_etf_charts():
    """
    输出国家队护盘 ETF 走势图
    分为大盘和中小盘两个文件夹
    """
    # 定义大盘 ETF 列表
    large_cap_etfs = {
        '510300': '华泰柏瑞沪深 300ETF',
        '510310': '易方达沪深 300ETF',
        '510330': '华夏沪深 300ETF',
        '159919': '嘉实沪深 300ETF',
        '510050': '华夏上证 50ETF',
    }
    
    # 定义中小盘 ETF 列表
    small_mid_cap_etfs = {
        '510500': '南方中证 500ETF',
        '512100': '南方中证 1000ETF',
        '159845': '华夏中证 1000ETF',
        '159915': '易方达创业板 ETF',
        '588000': '华夏科创 50ETF',
    }
    
    # 获取所有 ETF 份额数据
    etf_share_list = get_etf_share(dt=START_DATE)
    
    # 创建输出目录
    base_dir = get_data_dir() + '/etf/png/'
    large_cap_dir = base_dir + '核心大盘/'
    small_mid_cap_dir = base_dir + '中小盘/'
    
    if not os.path.exists(large_cap_dir):
        os.makedirs(large_cap_dir)
    if not os.path.exists(small_mid_cap_dir):
        os.makedirs(small_mid_cap_dir)
    
    print("=" * 80)
    print("开始生成国家队护盘 ETF 走势图")
    print("=" * 80)
    
    # 处理大盘 ETF
    print("\n【核心大盘 ETF】")
    print("-" * 80)
    for code, name in large_cap_etfs.items():
        if code not in etf_share_list:
            print("未找到 {}({}) 的数据".format(name, code))
            continue
        
        etf_share_dict = etf_share_list[code]
        
        # 获取净值数据
        start_str = START_DATE.replace('-', '')
        end_str = etf_share_dict['share']['dt'][-1].replace('-', '')
        data_list = _fetch_fund_info_em(code, start_str, end_str)
        
        if data_list is None or len(data_list) == 0:
            print("{}({}) 无净值数据".format(name, code))
            continue
        
        try:
            close_list = data_list['单位净值'].tolist()
            # 使用 share 数据的日期，避免 akshare 日期解析问题
            close_data = {'dt': etf_share_dict['share']['dt'], 'close': close_list}
            
            # 确保数据长度一致
            min_len = min(len(close_list), len(etf_share_dict['share']['dt']))
            if min_len == 0:
                print("{}({}) 数据长度为 0".format(name, code))
                continue
            
            close_data = {
                'dt': etf_share_dict['share']['dt'][-min_len:],
                'close': close_list[-min_len:]
            }
            
            # 输出图表到大盘目录
            output_png(code, etf_share_dict, close_data, large_cap_dir)
            print("✓ {}({}) - 已生成".format(name, code))
        except Exception as e:
            print("✗ {}({}) - 生成失败：{}".format(name, code, e))
    
    # 处理中小盘 ETF
    print("\n【中小盘 ETF】")
    print("-" * 80)
    for code, name in small_mid_cap_etfs.items():
        if code not in etf_share_list:
            print("未找到 {}({}) 的数据".format(name, code))
            continue
        
        etf_share_dict = etf_share_list[code]
        
        # 获取净值数据
        start_str = START_DATE.replace('-', '')
        end_str = etf_share_dict['share']['dt'][-1].replace('-', '')
        data_list = _fetch_fund_info_em(code, start_str, end_str)
        
        if data_list is None or len(data_list) == 0:
            print("{}({}) 无净值数据".format(name, code))
            continue
        
        try:
            close_list = data_list['单位净值'].tolist()
            # 使用 share 数据的日期，避免 akshare 日期解析问题
            close_data = {'dt': etf_share_dict['share']['dt'], 'close': close_list}
            
            # 确保数据长度一致
            min_len = min(len(close_list), len(etf_share_dict['share']['dt']))
            if min_len == 0:
                print("{}({}) 数据长度为 0".format(name, code))
                continue
            
            close_data = {
                'dt': etf_share_dict['share']['dt'][-min_len:],
                'close': close_list[-min_len:]
            }
            
            # 输出图表到中小盘目录
            output_png(code, etf_share_dict, close_data, small_mid_cap_dir)
            print("✓ {}({}) - 已生成".format(name, code))
        except Exception as e:
            print("✗ {}({}) - 生成失败：{}".format(name, code, e))
    
    print("\n" + "=" * 80)
    print("国家队护盘 ETF 走势图生成完成！")
    print("核心大盘 ETF 图表保存至：{}".format(large_cap_dir))
    print("中小盘 ETF 图表保存至：{}".format(small_mid_cap_dir))
    print("=" * 80)

def main():
    # 清除 etf 缓存
    cachedir = get_data_dir()+'/etf/png/'
    clear_cache(cachedir)
    clear_cache(cachedir+'买入观察/')
    clear_cache(cachedir+'核心大盘/')
    clear_cache(cachedir+'中小盘/')
    
    # etf 场内份额
    etf_share_list = get_etf_share(dt=START_DATE)
    for code in etf_share_list.keys():
        etf_share_dict = etf_share_list[code]
        is_valid,close_list = is_asc_share(code,etf_share_dict)
        try:
            if is_valid:
                output_png(code,etf_share_dict,close_list,cachedir+'买入观察/')
            elif close_list:
                output_png(code,etf_share_dict,close_list,cachedir)
        except Exception as e:
            print(e)
    
    # 输出 ETF 份额变化 Excel 文件
    output_etf_share_change_excel()
    
    # 输出国家队护盘 ETF 走势图
    output_national_team_etf_charts()
        
"""
    source /Users/wj/workspace/czsc/czsc_env/bin/activate
    cd /Users/wj/czsc
"""
if __name__ == '__main__':
    main()