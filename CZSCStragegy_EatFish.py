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

MIN_THRESH = 50 # 最低阈值
MIN_RATIO = 0.98 # 买入条件
# 大盘指数代码（上证指数）
大盘指数代码 = "sh.000001"

# 全局变量：大盘指数数据缓存
_index_data_cache = None

# 收益统计变量
plus_list = []
minus_list = []
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

def to_series(data, index):
    """
    将数据转换为与 DataFrame 索引对齐的 pandas Series
    """
    if isinstance(data, pd.Series):
        return data.reindex(index, fill_value=np.nan)
    else:
        # numpy 数组或其他类型
        arr = np.array(data)
        if len(arr) == len(index):
            return pd.Series(arr, index=index)
        elif len(arr) > len(index):
            # 如果数组长度大于索引长度，取最后 len(index) 个元素
            return pd.Series(arr[-len(index):], index=index)
        else:
            # 如果数组长度小于索引长度，前面填充 NaN
            result = pd.Series([np.nan] * (len(index) - len(arr)) + list(arr), index=index)
            return result

def calculate_eatfish_indicators(df):
    """
    计算吃鱼行情指标
    """
    # 确保所有计算结果都与 df.index 对齐
    idx = df.index
    
    # ========== 基础指标计算 ==========
    # ABC1:=EMA(CLOSE,N1);
    ABC1 = to_series(EMA(df['close'], N1), idx)
    
    # ABC2:=(ABC1/LLV(ABC1,10)-1)*100;
    ABC2 = to_series((ABC1 / to_series(LLV(ABC1.values, 10), idx) - 1) * 100, idx)
    
    # ABC3:=(-1)*ABC2;
    ABC3 = (-1) * ABC2
    
    # ABC4:=100*(HHV(HIGH,N2)-CLOSE)/(HHV(HIGH,N2)-LLV(LOW,N2));
    HHV_high = to_series(HHV(df['high'], N2), idx)
    LLV_low = to_series(LLV(df['low'], N2), idx)
    ABC4 = to_series(100 * (HHV_high - df['close']) / (HHV_high - LLV_low + 1e-10), idx)
    
    # ABC5:=REF(CLOSE,1);
    ABC5 = to_series(REF(df['close'], 1), idx)
    
    # ABC6:=SMA(MAX(CLOSE-ABC5,0),N3,1)/SMA(ABS(CLOSE-ABC5),N3,1)*100;
    close_minus_abc5 = df['close'] - ABC5
    ABC6 = to_series(SMA(MAX(close_minus_abc5.values, 0), N3, 1), idx) / (to_series(SMA(ABS(close_minus_abc5.values), N3, 1), idx) + 1e-10) * 100
    
    # ABC7:=(CLOSE-LLV(LOW,9))/(HHV(HIGH,9)-LLV(LOW,9))*100;
    LLV_low9 = to_series(LLV(df['low'], 9), idx)
    HHV_high9 = to_series(HHV(df['high'], 9), idx)
    ABC7 = to_series((df['close'] - LLV_low9) / (HHV_high9 - LLV_low9 + 1e-10) * 100, idx)
    
    # ABC8:=SMA(ABC7,3,1);
    ABC8 = to_series(SMA(ABC7.values, 3, 1), idx)
    
    # ABC9:=SMA(ABC8,3,1);
    ABC9 = to_series(SMA(ABC8.values, 3, 1), idx)
    
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
    ABC14 = to_series(EMA(df['close'], 20), idx)
    
    # ABC15:=EMA(CLOSE,30);
    ABC15 = to_series(EMA(df['close'], 30), idx)
    
    # ABC16:=EMA(CLOSE,60);
    ABC16 = to_series(EMA(df['close'], 60), idx)
    
    # ABC17:=EMA(CLOSE,120);
    ABC17 = to_series(EMA(df['close'], 120), idx)
    
    # ABC18:=EMA(CLOSE,250);
    ABC18 = to_series(EMA(df['close'], 250), idx)
    
    # 计算均线粘合度
    # ABC27:=MAX(MAX(ABC15,ABC16),ABC17);
    ABC27 = pd.Series([max(max(ABC15.iloc[i], ABC16.iloc[i]), ABC17.iloc[i]) for i in range(len(idx))], index=idx)
    
    # ABC28:=MIN(MIN(ABC15,ABC16),ABC17);
    ABC28 = pd.Series([min(min(ABC15.iloc[i], ABC16.iloc[i]), ABC17.iloc[i]) for i in range(len(idx))], index=idx)
    
    # ABC29:=MAX(ABC27,ABC18);
    ABC29 = pd.Series([max(ABC27.iloc[i], ABC18.iloc[i]) for i in range(len(idx))], index=idx)
    
    # ABC30:=MIN(ABC28,ABC18);
    ABC30 = pd.Series([min(ABC28.iloc[i], ABC18.iloc[i]) for i in range(len(idx))], index=idx)
    
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
    ABC39 = (to_series(LLV(ABC38.values, 2), idx) > 成交额阈值1) & (ABC38 > 成交额阈值2)
    
    # ========== 趋势过滤条件 ==========
    # ABC37:=ABC35 < 1.3 AND REF(ABC36,1) < 1.05 AND CLOSE > ABC14 AND CLOSE > ABC33 AND ABC36 < 1.08;
    ABC37 = (ABC35 < 1.3) & (to_series(REF(ABC36.values, 1), idx) < 1.05) & (df['close'] > ABC14) & (df['close'] > ABC33) & (ABC36 < 1.08)
    
    # ========== 成交量确认增强 ==========
    # 量能放大1:=VOL > REF(VOL,1)*1.5;
    量能放大1 = df['volume'] > to_series(REF(df['volume'].values, 1), idx) * 1.5
    
    # 量能放大2:=VOL > MA(VOL,5)*1.2;
    量能放大2 = df['volume'] > to_series(MA(df['volume'], 5), idx) * 1.2
    
    # 量能放大3:=VOL > MA(VOL,20)*1.1;
    量能放大3 = df['volume'] > to_series(MA(df['volume'], 20), idx) * 1.1
    
    # 量能确认:=量能放大1 AND (量能放大2 OR 量能放大3);
    量能确认 = 量能放大1 & (量能放大2 | 量能放大3)
    
    # ========== 涨跌幅计算 ==========
    # ABC40:=CLOSE/REF(CLOSE,1);
    ABC40 = df['close'] / to_series(REF(df['close'].values, 1), idx)
    
    # ========== 买入信号1：均线突破 ==========
    # ABC41:=EMA(CLOSE,5);
    ABC41 = to_series(EMA(df['close'], 5), idx)
    
    # ABC42:=EMA(CLOSE,10);
    ABC42 = to_series(EMA(df['close'], 10), idx)
    
    # ABC43:=EMA(CLOSE,20);
    ABC43 = to_series(EMA(df['close'], 20), idx)
    
    # ABC44:=MAX(MAX(ABC41,ABC42),ABC43);
    ABC44 = pd.Series([max(max(ABC41.iloc[i], ABC42.iloc[i]), ABC43.iloc[i]) for i in range(len(idx))], index=idx)
    
    # ABC45:=MIN(MIN(ABC41,ABC42),ABC43);
    ABC45 = pd.Series([min(min(ABC41.iloc[i], ABC42.iloc[i]), ABC43.iloc[i]) for i in range(len(idx))], index=idx)
    
    # ABC46:=LOW < ABC45 AND CLOSE > ABC44 AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC46 = (df['low'] < ABC45) & (df['close'] > ABC44) & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    
    # ========== 买入信号2：典型价格突破 ==========
    # ABC47:=(HIGH+LOW+CLOSE)/3;
    ABC47 = (df['high'] + df['low'] + df['close']) / 3
    
    # ABC48:=(ABC47-MA(ABC47,81))*1000/(15*AVEDEV(ABC47,81));
    ABC47_ma = to_series(MA(ABC47.values, 81), idx)
    ABC47_avedev = to_series(AVEDEV(ABC47.values, 81), idx)
    ABC48 = to_series((ABC47 - ABC47_ma) * 1000 / (15 * ABC47_avedev + 1e-10), idx)
    
    # CROSS(ABC48,100) - 使用CROSS函数计算向上穿越100
    ABC48_cross = pd.Series(CROSS(ABC48.values, np.array([100] * len(ABC48))), index=idx)
    
    # ABC49:=CROSS(ABC48,100) AND 量能确认 AND ABC39 AND ABC40 > (1+涨幅阈值1/100) AND ABC37;
    ABC49 = ABC48_cross & 量能确认 & ABC39 & (ABC40 > (1 + 涨幅阈值1/100)) & ABC37
    
    # ========== 买入信号3：均线粘合突破 ==========
    # ABC50:=MA(CLOSE,30);
    ABC50 = to_series(MA(df['close'], 30), idx)
    
    # ABC51:=MA(CLOSE,60);
    ABC51 = to_series(MA(df['close'], 60), idx)
    
    # ABC52:=MA(CLOSE,90);
    ABC52 = to_series(MA(df['close'], 90), idx)
    
    # ABC53:=MA(CLOSE,240);
    ABC53 = to_series(MA(df['close'], 240), idx)
    
    # ABC54:=ABS(ABC50/ABC51-1);
    ABC54 = ABS(ABC50 / (ABC51 + 1e-10) - 1)
    
    # ABC55:=ABS(ABC51/ABC52-1);
    ABC55 = ABS(ABC51 / (ABC52 + 1e-10) - 1)
    
    # ABC56:=ABS(ABC50/ABC52-1);
    ABC56 = ABS(ABC50 / (ABC52 + 1e-10) - 1)
    
    # ABC57:=CLOSE/REF(CLOSE,1);
    ABC57 = df['close'] / to_series(REF(df['close'].values, 1), idx)
    
    # ABC58:=ABC57-1;
    ABC58 = ABC57 - 1
    
    # ABC59:=(ABC50+ABC51+ABC52)/3;
    ABC59 = (ABC50 + ABC51 + ABC52) / 3
    
    # ABC60:=IF(CLOSE > ABC59*1.04 AND CLOSE < ABC59*1.15,1,0);
    ABC60 = ((df['close'] > ABC59 * 1.04) & (df['close'] < ABC59 * 1.15)).astype(int)
    
    # ABC61:=ABC53/REF(ABC53,20);
    ABC61 = ABC53 / (to_series(REF(ABC53.values, 20), idx) + 1e-10)
    
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
    ABC66 = (ABC35 < 1.15) & (to_series(REF(ABC36.values, 1), idx) < 1.04) & (df['close'] > ABC14) & (df['close'] > ABC33) & (ABC36 < 1.08) & (ABC40 > (1 + 涨幅阈值2/100)) & 量能确认 & ABC39 & ABC37
    
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
    OUT = ABC68_优化 & (ABC71 * 6 > MIN_THRESH)
    
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
        signal_close = df['close'].iloc[idx]
        # 第二天（下一个交易日）
        if idx + 1 < len(df):
            buy_date = df['date'].iloc[idx + 1]
            # buy_price = df['open'].iloc[idx + 1]  # 第二天开盘价
            buy_price = df['close'].iloc[idx + 1]  # 第二天收盘价
            # buy_price = min(buy_price, buy_close)
            if buy_price >= signal_close*MIN_RATIO:  # 买入价格不能高于信号当天的收盘价*0.98
                continue

            buy_index = idx + 2
            # 计算持有不同天数的收益
            max_ratio = -1000
            for x in range(1, hold_days + 1):
                if buy_index + x < len(df):
                    # 使用最高价计算收益（最佳情况）
                    sell_high = df['high'].iloc[buy_index + x]
                    ratio = round(100 * (sell_high - buy_price) / buy_price, 2)
                    ratio_map[x].append(ratio)
                    max_ratio = max(max_ratio, ratio)
            if max_ratio == -1000:
                continue

            # 记录最大收益（使用最高价，最佳情况）
            if max_ratio > 0:
                plus_list.append(max_ratio)
            else:
                minus_list.append(max_ratio)
            
            buy_points.append({
                'symbol': symbol,
                'signal_date': signal_date,
                'buy_date': buy_date,
                'buy_price': buy_price,
                'signal_close': df['close'].iloc[idx],
                'buy_index': buy_index
            })
            stock_name = get_symbols_name(symbol)
            print(f"  {symbol} ({stock_name}) - 信号: {signal_date}, 买入: {buy_date}, 价格: {buy_price}")
    
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
    print(f"吃鱼阈值： {MIN_THRESH}")
    print(f"买入条件： {MIN_RATIO}")
    
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
    
    batch_size = 100  # 每处理100个股票打印一次统计
    
    for i, symbol in enumerate(all_symbols):
        print(f"[{pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}] 进度：{i+1} / {len(all_symbols)} - {symbol}")
        
        buy_points = analyze_stock(symbol, start_date)
        
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

    # 最终收益统计
    print_statistics("最终 ")
    print(f"{'='*60}\n")

'''
=== [900/4281] 收益统计结果 ===
吃鱼阈值： 40
买入条件： 0.98
正收益次数（最大收益）：201
正收益占比（最大收益）：85.17%
总的正收益：2058.67
总的负收益：-105.44

按持有天数统计：
第 1 天：
     样本数：236
     正收益次数：168
     正收益占比：71.19%
     总的正收益：977.67
     总的负收益：-184.29
第 2 天：
     样本数：236
     正收益次数：157
     正收益占比：66.53%
     总的正收益：961.49
     总的负收益：-314.23
第 3 天：
     样本数：236
     正收益次数：126
     正收益占比：53.39%
     总的正收益：1004.98
     总的负收益：-481.48
第 4 天：
     样本数：236
     正收益次数：123
     正收益占比：52.12%
     总的正收益：1130.57
     总的负收益：-641.77
第 5 天：
     样本数：236
     正收益次数：127
     正收益占比：53.81%
     总的正收益：1313.32
     总的负收益：-699.20

=== 详细统计 ===
正收益（最大收益）：
    平均值：10.24
    最大值：47.40
    最小值：0.14
    50% 的百分位数：7.31
    95% 的百分位数：27.73
负收益（最大收益）：
    平均值：-3.01
    最大值：0.00
    最小值：-11.76
    50% 的百分位数：-2.00
    95% 的百分位数：-0.15
第 1 天收益：
    平均值：3.36
    最大值：20.30
    最小值：-11.76
    50% 的百分位数：2.17
    95% 的百分位数：14.24
第 2 天收益：
    平均值：2.74
    最大值：27.92
    最小值：-18.43
    50% 的百分位数：2.00
    95% 的百分位数：14.77
第 3 天收益：
    平均值：2.22
    最大值：31.09
    最小值：-23.31
    50% 的百分位数：0.63
    95% 的百分位数：16.07
第 4 天收益：
    平均值：2.07
    最大值：38.21
    最小值：-27.24
    50% 的百分位数：0.53
    95% 的百分位数：21.69
第 5 天收益：
    平均值：2.60
    最大值：47.40
    最小值：-28.73
    50% 的百分位数：0.96
    95% 的百分位数：26.27
============================================================
============================================================
已处理 900 / 4281 个股票

=== [900/4281] 收益统计结果 ===
吃鱼阈值： 40
买入条件： 0.95
正收益次数（最大收益）：22
正收益占比（最大收益）：84.62%
总的正收益：244.91
总的负收益：-13.45

按持有天数统计：
第 1 天：
     样本数：26
     正收益次数：18
     正收益占比：69.23%
     总的正收益：95.71
     总的负收益：-32.70
第 2 天：
     样本数：26
     正收益次数：17
     正收益占比：65.38%
     总的正收益：101.24
     总的负收益：-51.73
第 3 天：
     样本数：26
     正收益次数：14
     正收益占比：53.85%
     总的正收益：120.61
     总的负收益：-61.83
第 4 天：
     样本数：26
     正收益次数：14
     正收益占比：53.85%
     总的正收益：129.16
     总的负收益：-80.82
第 5 天：
     样本数：26
     正收益次数：14
     正收益占比：53.85%
     总的正收益：160.49
     总的负收益：-87.15

=== 详细统计 ===
正收益（最大收益）：
    平均值：11.13
    最大值：38.81
    最小值：0.38
    50% 的百分位数：7.70
    95% 的百分位数：32.52
负收益（最大收益）：
    平均值：-3.36
    最大值：-0.97
    最小值：-5.29
    50% 的百分位数：-3.60
    95% 的百分位数：-1.27
第 1 天收益：
    平均值：2.42
    最大值：16.40
    最小值：-9.92
    50% 的百分位数：1.09
    95% 的百分位数：12.02
第 2 天收益：
    平均值：1.90
    最大值：16.36
    最小值：-12.22
    50% 的百分位数：2.56
    95% 的百分位数：10.63
第 3 天收益：
    平均值：2.26
    最大值：20.66
    最小值：-13.77
    50% 的百分位数：1.48
    95% 的百分位数：14.45
第 4 天收益：
    平均值：1.86
    最大值：32.79
    最小值：-17.17
    50% 的百分位数：0.49
    95% 的百分位数：24.99
第 5 天收益：
    平均值：2.82
    最大值：38.81
    最小值：-20.59
    50% 的百分位数：1.16
    95% 的百分位数：27.11
============================================================
============================================================
已处理 900 / 4281 个股票

=== [900/4281] 收益统计结果 ===
吃鱼阈值： 45
买入条件： 0.98
正收益次数（最大收益）：133
正收益占比（最大收益）：83.12%
总的正收益：1302.91
总的负收益：-76.73

按持有天数统计：
第 1 天：
     样本数：160
     正收益次数：106
     正收益占比：66.25%
     总的正收益：552.89
     总的负收益：-134.70
第 2 天：
     样本数：160
     正收益次数：99
     正收益占比：61.88%
     总的正收益：591.59
     总的负收益：-241.01
第 3 天：
     样本数：160
     正收益次数：80
     正收益占比：50.0%
     总的正收益：654.94
     总的负收益：-352.39
第 4 天：
     样本数：160
     正收益次数：80
     正收益占比：50.0%
     总的正收益：728.75
     总的负收益：-471.16
第 5 天：
     样本数：160
     正收益次数：82
     正收益占比：51.25%
     总的正收益：822.09
     总的负收益：-505.19

=== 详细统计 ===
正收益（最大收益）：
    平均值：9.80
    最大值：42.36
    最小值：0.14
    50% 的百分位数：6.67
    95% 的百分位数：27.12
负收益（最大收益）：
    平均值：-2.84
    最大值：0.00
    最小值：-11.76
    50% 的百分位数：-1.23
    95% 的百分位数：-0.11
第 1 天收益：
    平均值：2.61
    最大值：20.30
    最小值：-11.76
    50% 的百分位数：1.38
    95% 的百分位数：13.30
第 2 天收益：
    平均值：2.19
    最大值：27.92
    最小值：-18.43
    50% 的百分位数：1.31
    95% 的百分位数：14.48
第 3 天收益：
    平均值：1.89
    最大值：31.09
    最小值：-23.31
    50% 的百分位数：0.08
    95% 的百分位数：15.68
第 4 天收益：
    平均值：1.61
    最大值：38.21
    最小值：-27.24
    50% 的百分位数：0.05
    95% 的百分位数：20.60
第 5 天收益：
    平均值：1.98
    最大值：42.36
    最小值：-28.73
    50% 的百分位数：0.45
    95% 的百分位数：23.15
============================================================
============================================================
已处理 900 / 4281 个股票

=== [900/4281] 收益统计结果 ===
吃鱼阈值： 45
买入条件： 0.95
正收益次数（最大收益）：18
正收益占比（最大收益）：90.0%
总的正收益：164.60
总的负收益：-5.16

按持有天数统计：
第 1 天：
     样本数：20
     正收益次数：14
     正收益占比：70.0%
     总的正收益：64.53
     总的负收益：-21.75
第 2 天：
     样本数：20
     正收益次数：13
     正收益占比：65.0%
     总的正收益：73.51
     总的负收益：-36.51
第 3 天：
     样本数：20
     正收益次数：11
     正收益占比：55.0%
     总的正收益：80.39
     总的负收益：-41.90
第 4 天：
     样本数：20
     正收益次数：11
     正收益占比：55.0%
     总的正收益：69.34
     总的负收益：-54.20
第 5 天：
     样本数：20
     正收益次数：11
     正收益占比：55.0%
     总的正收益：88.75
     总的负收益：-55.89

=== 详细统计 ===
正收益（最大收益）：
    平均值：9.14
    最大值：27.40
    最小值：0.38
    50% 的百分位数：7.60
    95% 的百分位数：22.42
负收益（最大收益）：
    平均值：-2.58
    最大值：-0.97
    最小值：-4.19
    50% 的百分位数：-2.58
    95% 的百分位数：-1.13
第 1 天收益：
    平均值：2.14
    最大值：16.40
    最小值：-9.92
    50% 的百分位数：1.02
    95% 的百分位数：11.57
第 2 天收益：
    平均值：1.85
    最大值：16.36
    最小值：-11.78
    50% 的百分位数：2.23
    95% 的百分位数：10.74
第 3 天收益：
    平均值：1.92
    最大值：13.85
    最小值：-13.77
    50% 的百分位数：1.48
    95% 的百分位数：12.20
第 4 天收益：
    平均值：0.76
    最大值：21.54
    最小值：-17.17
    50% 的百分位数：0.90
    95% 的百分位数：16.39
第 5 天收益：
    平均值：1.64
    最大值：27.40
    最小值：-13.57
    50% 的百分位数：1.16
    95% 的百分位数：13.64
============================================================
============================================================
已处理 900 / 4281 个股票

=== [900/4281] 收益统计结果 ===
吃鱼阈值： 50
买入条件： 0.98
正收益次数（最大收益）：97
正收益占比（最大收益）：83.62%
总的正收益：1030.24
总的负收益：-54.74

按持有天数统计：
第 1 天：
     样本数：116
     正收益次数：80
     正收益占比：68.97%
     总的正收益：423.74
     总的负收益：-104.35
第 2 天：
     样本数：116
     正收益次数：74
     正收益占比：63.79%
     总的正收益：436.02
     总的负收益：-174.39
第 3 天：
     样本数：116
     正收益次数：59
     正收益占比：50.86%
     总的正收益：515.78
     总的负收益：-273.79
第 4 天：
     样本数：116
     正收益次数：59
     正收益占比：50.86%
     总的正收益：586.53
     总的负收益：-357.24
第 5 天：
     样本数：116
     正收益次数：61
     正收益占比：52.59%
     总的正收益：675.31
     总的负收益：-382.15

=== 详细统计 ===
正收益（最大收益）：
    平均值：10.62
    最大值：42.36
    最小值：0.14
    50% 的百分位数：7.12
    95% 的百分位数：29.18
负收益（最大收益）：
    平均值：-2.88
    最大值：0.00
    最小值：-11.76
    50% 的百分位数：-0.97
    95% 的百分位数：-0.07
第 1 天收益：
    平均值：2.75
    最大值：20.30
    最小值：-11.76
    50% 的百分位数：1.67
    95% 的百分位数：15.52
第 2 天收益：
    平均值：2.26
    最大值：27.92
    最小值：-18.43
    50% 的百分位数：1.47
    95% 的百分位数：14.35
第 3 天收益：
    平均值：2.09
    最大值：31.09
    最小值：-23.31
    50% 的百分位数：0.45
    95% 的百分位数：17.60
第 4 天收益：
    平均值：1.98
    最大值：38.21
    最小值：-27.24
    50% 的百分位数：0.20
    95% 的百分位数：22.26
第 5 天收益：
    平均值：2.53
    最大值：42.36
    最小值：-28.73
    50% 的百分位数：0.96
    95% 的百分位数：26.36
============================================================
============================================================
已处理 900 / 4281 个股票

=== [900/4281] 收益统计结果 ===
吃鱼阈值： 50
买入条件： 0.95
正收益次数（最大收益）：14
正收益占比（最大收益）：93.33%
总的正收益：136.19
总的负收益：-0.97

按持有天数统计：
第 1 天：
     样本数：15
     正收益次数：11
     正收益占比：73.33%
     总的正收益：51.51
     总的负收益：-16.67
第 2 天：
     样本数：15
     正收益次数：9
     正收益占比：60.0%
     总的正收益：55.07
     总的负收益：-24.73
第 3 天：
     样本数：15
     正收益次数：8
     正收益占比：53.33%
     总的正收益：64.90
     总的负收益：-26.35
第 4 天：
     样本数：15
     正收益次数：8
     正收益占比：53.33%
     总的正收益：58.02
     总的负收益：-34.36
第 5 天：
     样本数：15
     正收益次数：9
     正收益占比：60.0%
     总的正收益：85.39
     总的负收益：-35.53

=== 详细统计 ===
正收益（最大收益）：
    平均值：9.73
    最大值：27.40
    最小值：0.38
    50% 的百分位数：7.60
    95% 的百分位数：23.59
负收益（最大收益）：
    平均值：-0.97
    最大值：-0.97
    最小值：-0.97
    50% 的百分位数：-0.97
    95% 的百分位数：-0.97
第 1 天收益：
    平均值：2.32
    最大值：16.40
    最小值：-9.92
    50% 的百分位数：1.11
    95% 的百分位数：12.58
第 2 天收益：
    平均值：2.02
    最大值：16.36
    最小值：-10.13
    50% 的百分位数：1.35
    95% 的百分位数：12.22
第 3 天收益：
    平均值：2.57
    最大值：13.85
    最小值：-12.20
    50% 的百分位数：1.25
    95% 的百分位数：12.63
第 4 天收益：
    平均值：1.58
    最大值：21.54
    最小值：-13.70
    50% 的百分位数：0.10
    95% 的百分位数：17.75
第 5 天收益：
    平均值：3.32
    最大值：27.40
    最小值：-12.76
    50% 的百分位数：2.86
    95% 的百分位数：17.26
============================================================
'''
