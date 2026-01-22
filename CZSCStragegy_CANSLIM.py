# coding: utf-8
"""
欧奈尔 CANSLIM 选股策略
参考 CZSCStragegy_Goldenline.py 的结构实现

CANSLIM 原则：
C: Current quarterly earnings per share（当前季度每股收益）
A: Annual earnings growth（年度收益增长）
N: New products, new management, new highs（新产品、新管理层、新高）
S: Supply and demand（供需关系，主要是成交量）
L: Leader or laggard（领先股还是落后股）
I: Institutional sponsorship（机构投资者支持）
M: Market direction（市场方向）
"""
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd
import baostock as bs
import numpy as np
from czsc_sqlite import get_local_stock_data

# 统计变量
plus_list = []
minus_list = []
total_ratio = []
total_hold_days = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

def print_console(title, arr):
    """打印统计结果"""
    if len(arr) == 0:
        print(f"{title}：无数据")
        return
    
    # 计算平均值
    average = np.mean(arr)
    
    # 计算最大值
    max_value = np.max(arr)
    
    # 计算最小值
    min_value = np.min(arr)
    
    # 计算 50% 和 95% 的百分位数
    lower_bound = np.percentile(arr, 50)
    upper_bound = np.percentile(arr, 95)
    
    # 输出结果
    print(title)
    print(f"    平均值：{average:.2f}")
    print(f"    最大值：{max_value:.2f}")
    print(f"    最小值：{min_value:.2f}")
    print(f"    50% 的百分位数：{lower_bound:.2f}")
    print(f"    95% 的百分位数：{upper_bound:.2f}")

def get_financial_data(symbol):
    """
    使用 baostock API 获取财务数据
    参考: http://baostock.com/mainContent?file=pythonAPI.md
    
    返回: (季度收益数据, 年度收益增长数据)
    """
    profit_data = None
    growth_data = None
    
    try:
        # 获取最近4个季度的盈利能力数据（每股收益）
        # query_profit_data(code, year, quarter)
        current_date = pd.Timestamp.now()
        current_year = current_date.year
        current_quarter = (current_date.month - 1) // 3 + 1
        
        # 获取最近4个季度的数据
        profit_list = []
        for i in range(4):
            q = current_quarter - i
            y = current_year
            if q <= 0:
                q += 4
                y -= 1
            
            rs = bs.query_profit_data(code=symbol, year=y, quarter=q)
            if rs.error_code == '0':
                while rs.next():
                    data = rs.get_row_data()
                    if len(data) > 0:
                        profit_list.append({
                            'year': y,
                            'quarter': q,
                            'eps': float(data[3]) if len(data) > 3 and data[3] else 0,  # 每股收益
                        })
        
        if len(profit_list) >= 2:
            # 计算季度收益增长率
            latest_eps = profit_list[0]['eps']
            prev_eps = profit_list[1]['eps']
            if prev_eps > 0:
                eps_growth = (latest_eps - prev_eps) / abs(prev_eps) * 100
                profit_data = {
                    'latest_eps': latest_eps,
                    'prev_eps': prev_eps,
                    'eps_growth': eps_growth,
                    'eps_growth_rate': eps_growth
                }
        
        # 获取年度成长能力数据
        # query_growth_data(code, year, quarter)
        growth_list = []
        for i in range(2):
            q = current_quarter - i * 4
            y = current_year
            if q <= 0:
                q += 4
                y -= 1
            
            rs = bs.query_growth_data(code=symbol, year=y, quarter=q)
            if rs.error_code == '0':
                while rs.next():
                    data = rs.get_row_data()
                    if len(data) > 0:
                        growth_list.append({
                            'year': y,
                            'quarter': q,
                            'profit_yoy': float(data[3]) if len(data) > 3 and data[3] else 0,  # 净利润同比增长率
                        })
        
        if len(growth_list) >= 1:
            growth_data = {
                'profit_yoy': growth_list[0]['profit_yoy'] if growth_list[0]['profit_yoy'] else 0
            }
    
    except Exception as e:
        # 如果获取财务数据失败，返回None
        pass
    
    return profit_data, growth_data

def check_canslim_criteria(symbol, df):
    """
    检查股票是否符合 CANSLIM 标准
    参考 baostock API: http://baostock.com/mainContent?file=pythonAPI.md
    
    C: Current quarterly earnings per share（当前季度每股收益）
    A: Annual earnings growth（年度收益增长）
    N: New products, new management, new highs（新产品、新管理层、新高）
    S: Supply and demand（供需关系，主要是成交量）
    L: Leader or laggard（领先股还是落后股）
    I: Institutional sponsorship（机构投资者支持）
    M: Market direction（市场方向）
    
    返回: (是否符合条件, 详细信息字典)
    """
    if len(df) < 250:  # 需要至少一年的数据
        return False, {}
    
    result = {
        'C': False,  # 季度收益
        'A': False,  # 年度收益增长
        'N': False,  # 新高
        'S': False,  # 成交量
        'L': False,  # 领先股
        'I': False,  # 机构支持（用RPS代替）
        'M': True,   # 市场方向（默认符合，需要单独判断大盘）
    }
    
    financial_details = {}
    
    # 获取RPS数据
    ndf = get_rps_data(df)
    
    # C: 当前季度每股收益（使用 baostock 财务数据）
    profit_data, growth_data = get_financial_data(symbol)
    
    if profit_data:
        # 季度每股收益增长率超过25%
        eps_growth = profit_data.get('eps_growth_rate', 0)
        result['C'] = eps_growth > 25
        financial_details['eps_growth'] = eps_growth
        financial_details['latest_eps'] = profit_data.get('latest_eps', 0)
    else:
        # 如果无法获取财务数据，使用价格涨幅作为备选
        if len(df) >= 60:
            recent_return = (df['close'].iloc[-1] / df['close'].iloc[-60] - 1) * 100
            result['C'] = recent_return > 20
            financial_details['price_growth_3m'] = recent_return
    
    # A: 年度收益增长（使用 baostock 财务数据）
    if growth_data:
        profit_yoy = growth_data.get('profit_yoy', 0)
        # 年度净利润同比增长率超过25%
        result['A'] = profit_yoy > 25
        financial_details['profit_yoy'] = profit_yoy
    else:
        # 如果无法获取财务数据，使用价格涨幅作为备选
        if len(df) >= 250:
            annual_return = (df['close'].iloc[-1] / df['close'].iloc[-250] - 1) * 100
            result['A'] = annual_return > 25
            financial_details['price_growth_1y'] = annual_return
    
    # N: 新高（价格接近或创历史新高）
    if len(df) >= 250:
        current_price = df['close'].iloc[-1]
        # 计算250日最高价
        high_250 = df['high'].iloc[-250:].max()
        # 计算52周最高价（约250个交易日）
        high_52w = df['high'].iloc[-250:].max()
        # 当前价格接近52周高点的95%以上
        result['N'] = current_price >= high_52w * 0.95
    
    # S: 供需关系（成交量放大）
    if len(df) >= 20:
        # 最近5日平均成交量
        recent_vol = df['volume'].iloc[-5:].mean()
        # 20日平均成交量
        avg_vol_20 = df['volume'].iloc[-20:].mean()
        # 成交量放大超过50%
        result['S'] = recent_vol > avg_vol_20 * 1.5
    
    # L: 领先股（使用RPS指标，RPS > 80）
    if 'RPS50' in ndf.columns:
        current_rps50 = ndf['RPS50'].iloc[-1]
        result['L'] = current_rps50 >= 80
    
    # I: 机构投资者支持（使用RPS120代替）
    if 'RPS120' in ndf.columns:
        current_rps120 = ndf['RPS120'].iloc[-1]
        result['I'] = current_rps120 >= 70
    
    # 计算符合的条件数量
    criteria_count = sum([result[k] for k in ['C', 'A', 'N', 'S', 'L', 'I', 'M']])
    
    # 将财务详情添加到结果中
    result['financial_details'] = financial_details
    
    return criteria_count >= 5, result  # 至少符合5个条件

def canslim_strategy(symbol, df):
    """
    CANSLIM 策略主函数
    返回买入信号和相关信息
    """
    if len(df) < 250:
        return None
    
    # 检查CANSLIM条件
    is_match, criteria = check_canslim_criteria(symbol, df)
    
    if not is_match:
        return None
    
    # 获取当前价格和日期
    current_price = df['close'].iloc[-1]
    current_date = df['date'].iloc[-1]
    
    # 计算技术指标
    ndf = get_rps_data(df)
    
    # 计算均线
    ma20 = MA(df['close'], 20)
    ma50 = MA(df['close'], 50)
    ma120 = MA(df['close'], 120)
    
    # 检查是否在均线上方
    above_ma20 = current_price > ma20.iloc[-1] if len(ma20) > 0 else False
    above_ma50 = current_price > ma50.iloc[-1] if len(ma50) > 0 else False
    above_ma120 = current_price > ma120.iloc[-1] if len(ma120) > 0 else False
    
    # 计算成交量比率
    vol_ratio = 1.0
    if len(df) >= 20:
        recent_vol = df['volume'].iloc[-5:].mean()
        avg_vol_20 = df['volume'].iloc[-20:].mean()
        vol_ratio = recent_vol / avg_vol_20 if avg_vol_20 > 0 else 1.0
    
    # 计算涨幅
    return_3m = (df['close'].iloc[-1] / df['close'].iloc[-60] - 1) * 100 if len(df) >= 60 else 0
    return_1y = (df['close'].iloc[-1] / df['close'].iloc[-250] - 1) * 100 if len(df) >= 250 else 0
    
    # 获取RPS值
    rps50 = ndf['RPS50'].iloc[-1] if 'RPS50' in ndf.columns else 0
    rps120 = ndf['RPS120'].iloc[-1] if 'RPS120' in ndf.columns else 0
    
    return {
        'symbol': symbol,
        'date': current_date,
        'price': current_price,
        'criteria': criteria,
        'above_ma20': above_ma20,
        'above_ma50': above_ma50,
        'above_ma120': above_ma120,
        'vol_ratio': vol_ratio,
        'return_3m': return_3m,
        'return_1y': return_1y,
        'rps50': rps50,
        'rps120': rps120,
    }

def simulate_trade(symbol, df, buy_signal):
    """
    模拟交易，计算收益
    """
    if buy_signal is None:
        return None
    
    buy_date = buy_signal['date']
    buy_price = buy_signal['price']
    
    # 找到买入日期在df中的索引
    buy_idx = df[df['date'] == buy_date].index
    if len(buy_idx) == 0:
        return None
    
    buy_idx = buy_idx[0]
    
    # 计算持有hold_days天后的收益
    if buy_idx + hold_days < len(df):
        sell_price = df['close'].iloc[buy_idx + hold_days]
        sell_date = df['date'].iloc[buy_idx + hold_days]
        
        # 计算收益率
        ratio = round(100 * (sell_price - buy_price) / buy_price, 2)
        days_num = hold_days
        
        # 记录每天收益
        for x in range(1, hold_days + 1):
            if buy_idx + x < len(df):
                day_price = df['high'].iloc[buy_idx + x]
                day_ratio = round(100 * (day_price - buy_price) / buy_price, 2)
                ratio_map[x].append(day_ratio)
        
        total_ratio.append(ratio)
        total_hold_days.append(days_num)
        
        if ratio > 0:
            plus_list.append(ratio)
        else:
            minus_list.append(ratio)
        
        return {
            'buy_date': buy_date,
            'buy_price': buy_price,
            'sell_date': sell_date,
            'sell_price': sell_price,
            'ratio': ratio,
            'days': days_num
        }
    
    return None

# 打印统计数据的函数
def print_statistics(symbol_count=None):
    """打印统计数据，可以指定当前处理的symbol数量"""
    prefix = ""
    if symbol_count is not None:
        prefix = f"\n=== 已处理 {symbol_count} 个symbol的CANSLIM统计结果 ===\n"
    else:
        prefix = "\n=== CANSLIM策略最终统计结果 ===\n"
    
    print(prefix)
    
    # 遍历数组并统计
    if len(total_ratio) > 0:
        # 初始化计数器
        greater_than_zero = 0
        less_than_zero = 0
        for num in total_ratio:
            if num > 0:
                greater_than_zero += 1
            else:
                less_than_zero += 1
        print("正收益次数：" + str(greater_than_zero))
        print("正收益占比：" + str(round(100 * greater_than_zero / len(total_ratio), 2)) + "%")
    
    print("正收益次数：" + str(len(plus_list)))
    if len(plus_list) > 0:
        print("正收益占比：" + str(round(100 * len(plus_list) / (len(minus_list) + len(plus_list)), 2)) + "%")
        total = 0
        for x in range(0, len(plus_list)):
            total += plus_list[x]
        print("总的正收益：" + str(total))
    
    total = 0
    for x in range(0, len(minus_list)):
        total += minus_list[x]
    print("总的负收益：" + str(total))
    
    # 每天
    for x in range(1, hold_days + 1):
        print("第 {} 天：".format(x))
        res_list = ratio_map[x]
        plus_num = 0
        plus_val = 0
        minus_num = 0
        minus_val = 0
        for idx in range(0, len(res_list)):
            ratio = res_list[idx]
            if ratio > 0:
                plus_num += 1
                plus_val += ratio
            else:
                minus_num += 1
                minus_val += ratio
        print("     正收益次数：" + str(plus_num))
        if plus_num > 0 or minus_num > 0:
            print("     正收益占比：" + str(round(100 * plus_num / (plus_num + minus_num), 2)) + "%")
        print("     总的正收益：" + str(plus_val))
        print("     总的负收益：" + str(minus_val))
    
    # 打印总体统计
    if len(total_ratio) > 0:
        print_console('总收益：', total_ratio)
    if len(total_hold_days) > 0:
        print_console('总持有天数：', total_hold_days)
    if len(plus_list):
        print_console('正收益：', plus_list)
    if len(minus_list) > 0:
        print_console('负收益：', minus_list)
    for x in range(1, hold_days + 1):
        if len(ratio_map[x]) > 0:
            print_console("第 {} 天：".format(x), ratio_map[x])

if __name__ == '__main__':
    print('CANSLIM选股策略（使用baostock财务数据优化）')
    print('参考文档: http://baostock.com/mainContent?file=pythonAPI.md')
    
    # 登录 baostock
    lg = bs.login()
    if lg.error_code != '0':
        print('baostock登录失败: ' + lg.error_msg)
        sys.exit(1)
    print('baostock登录成功')
    
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    symbol_count = 0
    match_count = 0
    
    for symbol in all_symbols:
        symbol_count += 1
        print("[{}] 进度：{} / {}".format(
            pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"), 
            all_symbols.index(symbol), 
            len(all_symbols)
        ))
        
        try:
            df = get_local_stock_data(symbol, start_date)
            if df is None or len(df) == 0:
                continue
            
            # 执行CANSLIM策略
            buy_signal = canslim_strategy(symbol, df)
            
            if buy_signal:
                match_count += 1
                criteria = buy_signal['criteria']
                criteria_str = ', '.join([k for k, v in criteria.items() if v])
                
                print("{} {} - CANSLIM信号 - 价格: {:.2f}, 符合条件: [{}]".format(
                    symbol,
                    buy_signal['date'],
                    buy_signal['price'],
                    criteria_str
                ))
                print("    3月涨幅: {:.2f}%, 1年涨幅: {:.2f}%, RPS50: {:.2f}, RPS120: {:.2f}, 成交量比: {:.2f}".format(
                    buy_signal['return_3m'],
                    buy_signal['return_1y'],
                    buy_signal['rps50'],
                    buy_signal['rps120'],
                    buy_signal['vol_ratio']
                ))
                
                # 模拟交易
                trade_result = simulate_trade(symbol, df, buy_signal)
                if trade_result:
                    print("    买入: {} @ {:.2f}, 卖出: {} @ {:.2f}, 收益: {:.2f}%, 持有: {}天".format(
                        trade_result['buy_date'],
                        trade_result['buy_price'],
                        trade_result['sell_date'],
                        trade_result['sell_price'],
                        trade_result['ratio'],
                        trade_result['days']
                    ))
        
        except Exception as e:
            print("处理 {} 时出错: {}".format(symbol, str(e)))
            continue
        
        # 每100个symbol打印一次统计数据
        if symbol_count % 100 == 0:
            print_statistics(symbol_count)
    
    # 输出最终统计结果
    print("\n=== CANSLIM策略总结 ===")
    print("总股票数: {}".format(len(all_symbols)))
    print("符合CANSLIM条件的股票数: {}".format(match_count))
    print("匹配率: {:.2f}%".format(100 * match_count / len(all_symbols) if len(all_symbols) > 0 else 0))
    
    print_statistics()
    
    # 登出 baostock
    bs.logout()
    print('baostock已登出')