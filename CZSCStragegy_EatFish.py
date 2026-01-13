# coding: utf-8
"""
吃鱼行情策略 - 优化版
参考通达信选股公式实现
信号出现后第二天开盘价作为买入点
"""
import os
import sys
import pandas as pd
import numpy as np
from czsc_daily_util import *
from lib.MyTT import *
from czsc_sqlite import get_local_stock_data

# ========== 参数设置 ==========
N1 = 10          # EMA周期
N2 = 14          # 威廉指标周期
N3 = 9           # RSI周期
成交额阈值1 = 2000   # 成交额下限（万元）
成交额阈值2 = 8000   # 成交额上限（万元）
涨幅阈值1 = 2.9     # 涨幅阈值1（%）
涨幅阈值2 = 4.0     # 涨幅阈值2（%）
涨幅阈值3 = 5.0     # 涨幅阈值3（%）

# 大盘指数代码（上证指数）
大盘指数代码 = "sh.000001"

# 全局变量：大盘指数数据缓存
_index_data_cache = None

# 收益统计变量
plus_list = []
minus_list = []
total_ratio = []
total_hold_days = []
hold_days = 5
ratio_map = {}
for x in range(1, hold_days + 1):
    ratio_map[x] = []

def print_console(title, arr):
    """
    打印统计结果
    """
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

def get_index_data(start_date='2000-01-01'):
    """
    获取大盘指数数据（缓存）
    """
    global _index_data_cache
    if _index_data_cache is None:
        try:
            _index_data_cache = get_local_stock_data(大盘指数代码, start_date)
            if _index_data_cache is None or len(_index_data_cache) == 0:
                print(f"警告：无法获取大盘指数数据 {大盘指数代码}，市场过滤将被禁用")
                _index_data_cache = pd.DataFrame()
        except Exception as e:
            print(f"获取大盘指数数据失败：{e}")
            _index_data_cache = pd.DataFrame()
    return _index_data_cache

def calculate_market_filter(df):
    """
    计算市场过滤条件
    大盘趋势:=MA(大盘指数,20) > MA(大盘指数,60);
    市场强度:=(大盘指数-MA(大盘指数,20))/MA(大盘指数,20)*100;
    市场过滤:=大盘趋势 AND 市场强度 > -3;
    """
    index_df = get_index_data()
    if index_df is None or len(index_df) == 0:
        # 无法获取指数数据，返回全True（不进行过滤）
        return pd.Series([True] * len(df), index=df.index)
    
    # 合并股票数据和指数数据（按日期对齐）
    merged_df = pd.merge(df[['date']], index_df[['date', 'close']], on='date', how='left')
    merged_df = merged_df.sort_values('date').reset_index(drop=True)
    
    # 计算大盘指标
    大盘指数 = merged_df['close'].values
    大盘MA20 = MA(大盘指数, 20)
    大盘MA60 = MA(大盘指数, 60)
    
    # 大盘趋势
    大盘趋势 = 大盘MA20 > 大盘MA60
    
    # 市场强度
    市场强度 = (大盘指数 - 大盘MA20) / (大盘MA20 + 1e-10) * 100
    
    # 市场过滤
    市场过滤 = pd.Series([True] * len(df), index=df.index)
    for i, date in enumerate(df['date']):
        idx = merged_df[merged_df['date'] == date].index
        if len(idx) > 0:
            j = idx[0]
            if j < len(大盘趋势) and j < len(市场强度):
                市场过滤.iloc[i] = 大盘趋势[j] & (市场强度[j] > -3)
    
    return 市场过滤.fillna(True)

def calculate_eatfish_indicators(df):
    """
    计算吃鱼行情指标
    """
    # ========== 基础指标计算 ==========
    # ABC1:=EMA(CLOSE,N1);
    ABC1 = EMA(df['close'], N1)
    
    # ABC2:=(ABC1/LLV(ABC1,10)-1)*100;
    ABC2 = (ABC1 / LLV(ABC1, 10) - 1) * 100
    
    # ABC3:=(-1)*ABC2;
    ABC3 = (-1) * ABC2
    
    # ABC4:=100*(HHV(HIGH,N2)-CLOSE)/(HHV(HIGH,N2)-LLV(LOW,N2));
    ABC4 = 100 * (HHV(df['high'], N2) - df['close']) / (HHV(df['high'], N2) - LLV(df['low'], N2) + 1e-10)
    
    # ABC5:=REF(CLOSE,1);
    ABC5 = REF(df['close'], 1)
    
    # ABC6:=SMA(MAX(CLOSE-ABC5,0),N3,1)/SMA(ABS(CLOSE-ABC5),N3,1)*100;
    ABC6 = SMA(MAX(df['close'] - ABC5, 0), N3, 1) / (SMA(ABS(df['close'] - ABC5), N3, 1) + 1e-10) * 100
    
    # ABC7:=(CLOSE-LLV(LOW,9))/(HHV(HIGH,9)-LLV(LOW,9))*100;
    ABC7 = (df['close'] - LLV(df['low'], 9)) / (HHV(df['high'], 9) - LLV(df['low'], 9) + 1e-10) * 100
    
    # ABC8:=SMA(ABC7,3,1);
    ABC8 = SMA(ABC7, 3, 1)
    
    # ABC9:=SMA(ABC8,3,1);
    ABC9 = SMA(ABC8, 3, 1)
    
    # ABC10:=3*ABC8-2*ABC9;
    ABC10 = 3 * ABC8 - 2 * ABC9
    
    # ABC11:=ABC6 >=76 OR ABC10 > 95;
    ABC11 = (ABC6 >= 76) | (ABC10 > 95)
    
    # ABC12:=ABC4 < 25;
    ABC12 = ABC4 < 25
    
    # ABC13:=ABC11 OR ABC12;
    ABC13 = ABC11 | ABC12
    
    # ========== 简化均线系统 ==========
    # ABC14:=EMA(CLOSE,20);
    ABC14 = EMA(df['close'], 20)
    
    # ABC15:=EMA(CLOSE,30);
    ABC15 = EMA(df['close'], 30)
    
    # ABC16:=EMA(CLOSE,60);
    ABC16 = EMA(df['close'], 60)
    
    # ABC17:=EMA(CLOSE,120);
    ABC17 = EMA(df['close'], 120)
    
    # ABC18:=EMA(CLOSE,250);
    ABC18 = EMA(df['close'], 250)
    
    # 计算均线粘合度
    # ABC27:=MAX(MAX(ABC15,ABC16),ABC17);
    ABC27 = MAX(MAX(ABC15, ABC16), ABC17)
    
    # ABC28:=MIN(MIN(ABC15,ABC16),ABC17);
    ABC28 = MIN(MIN(ABC15, ABC16), ABC17)
    
    # ABC29:=MAX(ABC27,ABC18);
    ABC29 = MAX(ABC27, ABC18)
    
    # ABC30:=MIN(ABC28,ABC18);
    ABC30 = MIN(ABC28, ABC18)
    
    # ABC33:=ABC29;
    ABC33 = ABC29
    
    # ABC34:=ABC30;
    ABC34 = ABC30
    
    # ABC35:=ABC33/ABC34;
    ABC35 = ABC33 / (ABC34 + 1e-10)
    
    # ABC36:=LOW/ABC27;
    ABC36 = df['low'] / (ABC27 + 1e-10)
    
    # ========== 成交额动态过滤 ==========
    # ABC38:=AMOUNT/10000;
    ABC38 = df['amount'] / 10000
    
    # ABC39:=LLV(ABC38,2) > 成交额阈值1 AND ABC38 > 成交额阈值2;
    ABC39 = (LLV(ABC38, 2) > 成交额阈值1) & (ABC38 > 成交额阈值2)
    
    # ========== 趋势过滤条件 ==========
    # ABC37:=ABC35 < 1.3 AND REF(ABC36,1) < 1.05 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08;
    ABC37 = (ABC35 < 1.3) & (REF(ABC36, 1) < 1.05) & (df['close'] > ABC14) & (df['close'] > ABC33) & (ABC36 < 1.08)
    
    # ========== 成交量确认增强 ==========
    # 量能放大1:=VOL > REF(VOL,1)*1.5;
    量能放大1 = df['volume'] > REF(df['volume'], 1) * 1.5
    
    # 量能放大2:=VOL > MA(VOL,5)*1.2;
    量能放大2 = df['volume'] > MA(df['volume'], 5) * 1.2
    
    # 量能放大3:=VOL > MA(VOL,20)*1.1;
    量能放大3 = df['volume'] > MA(df['volume'], 20) * 1.1
    
    # 量能确认:=量能放大1 AND (量能放大2 OR 量能放大3);
    量能确认 = 量能放大1 & (量能放大2 | 量能放大3)
    
    # ========== 涨跌幅计算 ==========
    # ABC40:=CLOSE/REF(CLOSE,1);
    ABC40 = df['close'] / REF(df['close'], 1)
    
    # ========== 买入信号1：均线突破 ==========
    # ABC41:=EMA(CLOSE,5);
    ABC41 = EMA(df['close'], 5)
    
    # ABC42:=EMA(CLOSE,10);
    ABC42 = EMA(df['close'], 10)
    
    # ABC43:=EMA(CLOSE,20);
    ABC43 = EMA(df['close'], 20)
    
    # ABC44:=MAX(MAX(ABC41,ABC42),ABC43);
    ABC44 = MAX(MAX(ABC41, ABC42), ABC43)
    
    # ABC45:=MIN(MIN(ABC41,ABC42),ABC43);
    ABC45 = MIN(MIN(ABC41, ABC42), ABC43)
    
    # ABC46:=LOW < ABC45 AND CLOSE > ABC44 AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC46 = (df['low'] < ABC45) & (df['close'] > ABC44) & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    
    # ========== 买入信号2：典型价格突破 ==========
    # ABC47:=(HIGH+LOW+CLOSE)/3;
    ABC47 = (df['high'] + df['low'] + df['close']) / 3
    
    # ABC48:=(ABC47-MA(ABC47,81))*1000/(15*AVEDEV(ABC47,81));
    ABC48 = (ABC47 - MA(ABC47, 81)) * 1000 / (15 * AVEDEV(ABC47, 81) + 1e-10)
    
    # CROSS(ABC48,100) - 使用CROSS函数计算向上穿越100
    ABC48_series = pd.Series(ABC48, index=df.index)
    ABC48_cross = pd.Series(CROSS(ABC48_series, pd.Series([100] * len(ABC48_series), index=ABC48_series.index)), 
                            index=df.index)
    
    # ABC49:=CROSS(ABC48,100) AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC49 = ABC48_cross & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    
    # ========== 买入信号3：均线粘合突破 ==========
    # ABC50:=MA(CLOSE,30);
    ABC50 = MA(df['close'], 30)
    
    # ABC51:=MA(CLOSE,60);
    ABC51 = MA(df['close'], 60)
    
    # ABC52:=MA(CLOSE,90);
    ABC52 = MA(df['close'], 90)
    
    # ABC53:=MA(CLOSE,240);
    ABC53 = MA(df['close'], 240)
    
    # ABC54:=ABS(ABC50/ABC51-1);
    ABC54 = ABS(ABC50 / (ABC51 + 1e-10) - 1)
    
    # ABC55:=ABS(ABC51/ABC52-1);
    ABC55 = ABS(ABC51 / (ABC52 + 1e-10) - 1)
    
    # ABC56:=ABS(ABC50/ABC52-1);
    ABC56 = ABS(ABC50 / (ABC52 + 1e-10) - 1)
    
    # ABC57:=CLOSE/REF(CLOSE,1);
    ABC57 = df['close'] / REF(df['close'], 1)
    
    # ABC58:=ABC57-1;
    ABC58 = ABC57 - 1
    
    # ABC59:=(ABC50+ABC51+ABC52)/3;
    ABC59 = (ABC50 + ABC51 + ABC52) / 3
    
    # ABC60:=IF(CLOSE > ABC59*1.04 AND CLOSE < ABC59*1.15,1,0);
    ABC60 = ((df['close'] > ABC59 * 1.04) & (df['close'] < ABC59 * 1.15)).astype(int)
    
    # ABC61:=ABC53/REF(ABC53,20);
    ABC61 = ABC53 / (REF(ABC53, 20) + 1e-10)
    
    # ABC62:=ABS(ABC61-1);
    ABC62 = ABS(ABC61 - 1)
    
    # ABC63:=IF(ABC62 < 0.04,1,0);
    ABC63 = (ABC62 < 0.04).astype(int)
    
    # ABC64:=IF(ABC54 < 0.04 AND ABC55 < 0.04 AND ABC56 < 0.04 AND ABC58 > 0.04 AND ABC60=1 AND ABC63=1 AND ABC59 > ABC53,1,0);
    ABC64 = ((ABC54 < 0.04) & (ABC55 < 0.04) & (ABC56 < 0.04) & (ABC58 > 0.04) & (ABC60 == 1) & (ABC63 == 1) & (ABC59 > ABC53)).astype(int)
    
    # ABC65:=ABC64 AND 量能确认 AND ABC39 AND ABC37;
    ABC65 = (ABC64 == 1) & 量能确认 & ABC39 & ABC37
    
    # ========== 买入信号4：强势突破 ==========
    # ABC66:=ABC35 < 1.15 AND REF(ABC36,1) < 1.04 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08 AND ABC40 > (1+涨幅阈值2/100) AND 量能确认 AND ABC39 AND ABC37;
    ABC66 = (ABC35 < 1.15) & (REF(ABC36, 1) < 1.04) & (df['close'] > ABC14) & (df['close'] > ABC33) & (ABC36 < 1.08) & (ABC40 > (1 + 涨幅阈值2/100)) & 量能确认 & ABC39 & ABC37
    
    # ========== 买入信号5：低位反弹 ==========
    # ABC67:=LOW < ABC34 AND CLOSE > ABC33 AND ABC40 > (1+涨幅阈值3/100) AND 量能确认;
    ABC67 = (df['low'] < ABC34) & (df['close'] > ABC33) & (ABC40 > (1 + 涨幅阈值3/100)) & 量能确认
    
    # ========== 综合买入信号 ==========
    # ABC68:=ABC46 OR ABC49 OR ABC65 OR ABC66 OR ABC67;
    ABC68 = ABC46 | ABC49 | ABC65 | ABC66 | ABC67
    
    # 应用市场环境过滤
    市场过滤 = calculate_market_filter(df)
    ABC68_优化 = ABC68 & 市场过滤
    
    # ========== 输出计算 ==========
    # ABC71:=IF(ABC68_优化,ABC2,0);
    ABC71 = pd.Series([0.0] * len(df), index=df.index, dtype=float)
    ABC71.loc[ABC68_优化] = ABC2.loc[ABC68_优化]
    
    # ========== 选股输出 ==========
    # OUT:ABC68_优化 AND (ABC71*6>40);
    OUT = ABC68_优化 & (ABC71 * 6 > 40)
    
    return OUT, ABC68_优化, ABC71

def find_buy_points(symbol, df, OUT):
    """
    找到买入点：信号出现后第二天开盘价作为买入点
    并计算持有不同天数的收益
    """
    buy_points = []
    
    # 找到所有信号点
    signal_indices = df[OUT].index.tolist()
    
    for idx in signal_indices:
        # 信号出现当天
        signal_date = df['date'].iloc[idx]
        
        # 第二天（下一个交易日）
        if idx + 1 < len(df):
            buy_date = df['date'].iloc[idx + 1]
            buy_price = df['open'].iloc[idx + 1]  # 第二天开盘价
            buy_index = idx + 1
            
            # 计算持有不同天数的收益
            max_ratio = -1000
            for x in range(1, hold_days + 1):
                if buy_index + x < len(df):
                    # 使用最高价计算收益（最佳情况）
                    sell_high = df['high'].iloc[buy_index + x]
                    ratio = round(100 * (sell_high - buy_price) / buy_price, 2)
                    ratio_map[x].append(ratio)
                    max_ratio = max(max_ratio, ratio)
            
            # 记录最大收益（使用最高价，最佳情况）
            if max_ratio > 0:
                plus_list.append(max_ratio)
            else:
                minus_list.append(max_ratio)
            
            # 同时计算持有到第hold_days天的收盘价收益（更实际）
            if buy_index + hold_days < len(df):
                sell_close = df['close'].iloc[buy_index + hold_days]
                close_ratio = round(100 * (sell_close - buy_price) / buy_price, 2)
                total_ratio.append(close_ratio)
                total_hold_days.append(hold_days)
            
            buy_points.append({
                'symbol': symbol,
                'signal_date': signal_date,
                'buy_date': buy_date,
                'buy_price': buy_price,
                'signal_close': df['close'].iloc[idx],
                'buy_index': buy_index
            })
    
    return buy_points

def analyze_stock(symbol, start_date='2020-01-01'):
    """
    分析单只股票
    """
    try:
        df = get_local_stock_data(symbol, start_date)
        if df is None or len(df) < 250:  # 需要足够的历史数据
            return []
        
        # 计算指标
        OUT, ABC68_优化, ABC71 = calculate_eatfish_indicators(df)
        
        # 找到买入点
        buy_points = find_buy_points(symbol, df, OUT)
        
        return buy_points
    except Exception as e:
        print(f"分析股票 {symbol} 时出错：{e}")
        return []

def print_statistics(title_prefix=""):
    """
    打印收益统计结果
    """
    title = f"{title_prefix}收益统计结果" if title_prefix else "收益统计结果"
    print(f"\n=== {title} ===")
    
    # 统计正收益次数和占比
    if len(total_ratio) > 0:
        greater_than_zero = sum(1 for r in total_ratio if r > 0)
        less_than_zero = sum(1 for r in total_ratio if r <= 0)
        print(f"买入点总数：{len(total_ratio)}")
        print(f"正收益次数：{greater_than_zero}")
        print(f"正收益占比：{round(100 * greater_than_zero / len(total_ratio), 2)}%")
    
    # 统计最大收益
    total_count = len(plus_list) + len(minus_list)
    if total_count > 0:
        print(f"正收益次数（最大收益）：{len(plus_list)}")
        print(f"正收益占比（最大收益）：{round(100 * len(plus_list) / total_count, 2)}%")
        if len(plus_list) > 0:
            total_plus = sum(plus_list)
            print(f"总的正收益：{total_plus:.2f}")
        if len(minus_list) > 0:
            total_minus = sum(minus_list)
            print(f"总的负收益：{total_minus:.2f}")
    
    # 按持有天数统计
    print(f"\n按持有天数统计：")
    for x in range(1, hold_days + 1):
        res_list = ratio_map[x]
        if len(res_list) == 0:
            continue
        
        plus_num = sum(1 for r in res_list if r > 0)
        plus_val = sum(r for r in res_list if r > 0)
        minus_num = sum(1 for r in res_list if r <= 0)
        minus_val = sum(r for r in res_list if r <= 0)
        
        print(f"第 {x} 天：")
        print(f"     样本数：{len(res_list)}")
        print(f"     正收益次数：{plus_num}")
        if plus_num > 0 or minus_num > 0:
            print(f"     正收益占比：{round(100 * plus_num / (plus_num + minus_num), 2)}%")
        print(f"     总的正收益：{plus_val:.2f}")
        print(f"     总的负收益：{minus_val:.2f}")
    
    # 打印详细统计
    print(f"\n=== 详细统计 ===")
    if len(total_ratio) > 0:
        print_console('总收益（持有5天收盘价）：', total_ratio)
    if len(plus_list) > 0:
        print_console('正收益（最大收益）：', plus_list)
    if len(minus_list) > 0:
        print_console('负收益（最大收益）：', minus_list)
    for x in range(1, hold_days + 1):
        if len(ratio_map[x]) > 0:
            print_console(f"第 {x} 天收益：", ratio_map[x])

if __name__ == '__main__':
    start_date = "2020-01-01"
    all_symbols = get_daily_symbols()
    
    all_buy_points = []
    batch_size = 100  # 每处理100个股票打印一次统计
    
    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{i+1} / {len(all_symbols)} - {symbol}")
        
        buy_points = analyze_stock(symbol, start_date)
        all_buy_points.extend(buy_points)
        
        # 打印最近的买入点
        if buy_points:
            for bp in buy_points[-3:]:  # 只打印最近3个
                print(f"  {symbol} - 信号日期: {bp['signal_date']}, 买入日期: {bp['buy_date']}, 买入价格: {bp['buy_price']:.2f}")
        
        # 每处理batch_size个股票，打印一次统计结果
        if (i + 1) % batch_size == 0:
            print(f"\n{'='*60}")
            print(f"已处理 {i+1} / {len(all_symbols)} 个股票")
            print_statistics(f"[{i+1}/{len(all_symbols)}] ")
            print(f"{'='*60}\n")
    
    # 最终统计结果
    print(f"\n{'='*60}")
    print(f"=== 最终统计结果 ===")
    print(f"总共处理 {len(all_symbols)} 个股票")
    print(f"总共找到 {len(all_buy_points)} 个买入点")
    
    if all_buy_points:
        # 按日期排序
        all_buy_points.sort(key=lambda x: x['buy_date'])
        
        # 打印最近的买入点
        print(f"\n最近的10个买入点：")
        for bp in all_buy_points[-10:]:
            stock_name = get_symbols_name(bp['symbol'])
            print(f"  {bp['symbol']} ({stock_name}) - 信号: {bp['signal_date']}, 买入: {bp['buy_date']}, 价格: {bp['buy_price']:.2f}")
    
    # 最终收益统计
    print_statistics("最终 ")
    print(f"{'='*60}\n")
