# coding: utf-8
"""
基于本地股票数据，使用 XGBoost 训练涨跌预测模型
数据来源：data/sqlite3.db STOCK_DAILY 表，通过 czsc_sqlite.get_local_stock_data 获取
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 将项目根目录加入 path，以便导入 czsc 模块
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from czsc_daily_util import get_daily_symbols, get_data_dir
from czsc_sqlite import get_local_stock_data
# 指标公式统一从 lib.MyTT 读取（通达信/同花顺兼容）
from lib.MyTT import (
    MA, EMA, RSI, REF, STD, DIFF, MAX, ABS,
    MACD, BOLL,
)

# XGBoost（需安装: pip install xgboost）
try:
    import xgboost as xgb
except ImportError:
    print("请先安装 xgboost: pip install xgboost")
    sys.exit(1)

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score

# 配置
TRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
MIN_BARS = 120          # 单只股票最少 K 线数才参与训练
START_DATE = "2001-01-01"
END_DATE = "2023-12-31"
TARGET_DAYS = 5         # 预测未来 N 日涨跌
TARGET_THRESHOLD = 0.0   # 未来 N 日收益率 > threshold 为 1，否则为 0
TRAIN_END_RATIO = 0.8   # 前 80% 时间用于训练，后 20% 验证
MAX_SYMBOLS = None       # 最多使用股票数量（可调大或设为 None 表示全部）
RANDOM_STATE = 42
MODEL_NAME = "xgboost_stock_clf.json"

def process_kline_inclusion(df):
    """
    缠论K线包含处理：合并包含关系的K线
    向上处理：取高高、低低；向下处理：取低低、高高
    """
    # 使用 date 列作为日期（若存在），否则用 index
    use_date_col = "date" in df.columns
    processed = []
    direction = None  # 向上/向下

    for i in range(len(df)):
        date_val = df["date"].iloc[i] if use_date_col else df.index[i]
        if i == 0:
            processed.append({
                "date": date_val,
                "high": df["high"].iloc[i],
                "low": df["low"].iloc[i],
                "open": df["open"].iloc[i],
                "close": df["close"].iloc[i],
                "volume": df["volume"].iloc[i],
            })
            continue

        curr_high, curr_low = df["high"].iloc[i], df["low"].iloc[i]
        last = processed[-1]

        # 判断包含关系
        if curr_high <= last["high"] and curr_low >= last["low"]:
            if direction == "up":
                last["high"] = max(last["high"], curr_high)
                last["low"] = max(last["low"], curr_low)
            else:
                last["high"] = min(last["high"], curr_high)
                last["low"] = min(last["low"], curr_low)
            last["close"] = df["close"].iloc[i]
        elif curr_high > last["high"] and curr_low > last["low"]:
            direction = "up"
            processed.append({
                "date": date_val,
                "high": curr_high, "low": curr_low,
                "open": df["open"].iloc[i],
                "close": df["close"].iloc[i],
                "volume": df["volume"].iloc[i],
            })
        elif curr_high < last["high"] and curr_low < last["low"]:
            direction = "down"
            processed.append({
                "date": date_val,
                "high": curr_high, "low": curr_low,
                "open": df["open"].iloc[i],
                "close": df["close"].iloc[i],
                "volume": df["volume"].iloc[i],
            })
        else:
            processed.append({
                "date": date_val,
                "high": curr_high, "low": curr_low,
                "open": df["open"].iloc[i],
                "close": df["close"].iloc[i],
                "volume": df["volume"].iloc[i],
            })

    return pd.DataFrame(processed).set_index("date")

def find_fractals(df):
    """
    识别顶底分型
    顶分型：中间K线高点最高，低点也最高
    底分型：中间K线低点最低，高点也最低
    """
    fractals = []
    highs = df['high'].values
    lows = df['low'].values
    
    for i in range(2, len(df) - 2):
        # 顶分型判断
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and 
            highs[i] > highs[i+1] and highs[i] > highs[i+2] and
            lows[i] > lows[i-1] and lows[i] > lows[i-2] and  # 低点也高于左侧
            lows[i] > lows[i+1] and lows[i] > lows[i+2]):    # 低点也高于右侧
            fractals.append({
                'index': i,
                'date': df.index[i],
                'type': 'top',
                'price': highs[i],
                'strength': highs[i] - max(lows[i-2:i+3])  # 强度：高点与周围低点的差
            })
        
        # 底分型判断
        elif (lows[i] < lows[i-1] and lows[i] < lows[i-2] and 
              lows[i] < lows[i+1] and lows[i] < lows[i+2] and
              highs[i] < highs[i-1] and highs[i] < highs[i-2] and
              highs[i] < highs[i+1] and highs[i] < highs[i+2]):
            fractals.append({
                'index': i,
                'date': df.index[i],
                'type': 'bottom',
                'price': lows[i],
                'strength': min(highs[i-2:i+3]) - lows[i]  # 强度：周围高点与低点的差
            })
    
    return pd.DataFrame(fractals)

def identify_strokes(fractals_df, min_klines=5):
    """
    根据顶底分型识别笔（连接相邻的顶底分型）
    新笔定义：顶底之间至少有5根独立K线（不含分型本身）
    """
    if len(fractals_df) < 2:
        return []
    
    strokes = []
    fractals = fractals_df.sort_values('index').to_dict('records')
    
    i = 0
    while i < len(fractals) - 1:
        curr = fractals[i]
        next_frac = fractals[i + 1]
        
        # 必须是顶接底或底接顶
        if curr['type'] == next_frac['type']:
            i += 1
            continue
        
        # 检查K线数量间隔
        kline_gap = next_frac['index'] - curr['index']
        if kline_gap >= min_klines:
            strokes.append({
                'start_date': curr['date'],
                'end_date': next_frac['date'],
                'start_idx': curr['index'],
                'end_idx': next_frac['index'],
                'start_price': curr['price'],
                'end_price': next_frac['price'],
                'direction': 'up' if next_frac['type'] == 'top' else 'down',
                'kline_count': kline_gap,
                'strength': abs(next_frac['price'] - curr['price'])
            })
            i += 1
        else:
            # 距离不够，跳过当前分型
            i += 1
    
    return pd.DataFrame(strokes)

def identify_segments(strokes_df, min_strokes=3):
    """
    识别线段：至少3笔构成，且有重叠区间形成中枢
    简化版：连续同向笔形成线段
    """
    if len(strokes_df) < min_strokes:
        return []
    
    segments = []
    i = 0
    while i < len(strokes_df) - 2:
        s1, s2, s3 = strokes_df.iloc[i], strokes_df.iloc[i+1], strokes_df.iloc[i+2]
        
        # 检查是否形成线段（3笔有重叠）
        if s1['direction'] != s2['direction'] and s2['direction'] != s3['direction']:
            # 计算中枢区间（3笔的重叠部分）
            high1, low1 = max(s1['start_price'], s1['end_price']), min(s1['start_price'], s1['end_price'])
            high2, low2 = max(s2['start_price'], s2['end_price']), min(s2['start_price'], s2['end_price'])
            high3, low3 = max(s3['start_price'], s3['end_price']), min(s3['start_price'], s3['end_price'])
            
            # 中枢高点取min，低点取max
            zg = min(high1, high2, high3)  # 中枢高点
            zd = max(low1, low2, low3)     # 中枢低点
            
            if zg > zd:  # 有有效中枢
                segments.append({
                    'start_date': s1['start_date'],
                    'end_date': s3['end_date'],
                    'direction': s1['direction'],
                    'zg': zg,  # 中枢高点
                    'zd': zd,  # 中枢低点
                    'stroke_count': 3,
                    'high': max(s1['start_price'], s3['end_price']),
                    'low': min(s1['start_price'], s3['end_price'])
                })
                i += 3
            else:
                i += 1
        else:
            i += 1
    
    return pd.DataFrame(segments)

def calculate_zhongshu_features(segments_df, current_price):
    """
    计算中枢相关特征
    """
    if len(segments_df) == 0:
        return {}
    
    last_seg = segments_df.iloc[-1]
    
    return {
        'zs_zg': last_seg['zg'],           # 中枢高点
        'zs_zd': last_seg['zd'],           # 中枢低点
        'zs_center': (last_seg['zg'] + last_seg['zd']) / 2,  # 中枢中心
        'zs_width': last_seg['zg'] - last_seg['zd'],          # 中枢宽度
        'price_to_zg': current_price / last_seg['zg'] - 1,  # 距中枢高点比例
        'price_to_zd': current_price / last_seg['zd'] - 1,    # 距中枢低点比例
        'in_zs': 1 if last_seg['zd'] <= current_price <= last_seg['zg'] else 0,  # 是否在中枢内
        'above_zs': 1 if current_price > last_seg['zg'] else 0,  # 中枢上方
        'below_zs': 1 if current_price < last_seg['zd'] else 0   # 中枢下方
    }

def identify_trading_points(df, fractals_df, strokes_df, segments_df):
    """
    识别缠论三类买卖点
    """
    trading_points = []
    current_price = df['close'].iloc[-1]
    
    if len(segments_df) < 2 or len(strokes_df) < 4:
        return trading_points
    
    # 获取最新信息
    last_seg = segments_df.iloc[-1]
    last_stroke = strokes_df.iloc[-1]
    last_fractal = fractals_df.iloc[-1] if len(fractals_df) > 0 else None
    
    # 一类买点：趋势背驰后的底分型
    if last_seg['direction'] == 'down' and last_fractal and last_fractal['type'] == 'bottom':
        # 检查是否背驰（简化版：MACD面积或价格跌幅比较）
        if len(strokes_df) >= 2:
            prev_stroke = strokes_df.iloc[-2]
            if last_stroke['strength'] < prev_stroke['strength'] * 0.8:  # 力度减弱
                trading_points.append({
                    'type': '1st_buy',
                    'price': last_fractal['price'],
                    'confidence': 0.8,
                    'condition': 'trend_divergence'
                })
    
    # 二类买点：一类买点后的回调不破前低
    # （需要历史记录，简化处理）
    
    # 三类买点：突破中枢后回调不破中枢高点
    if last_seg['direction'] == 'up' and current_price > last_seg['zg']:
        # 检查是否有回调到中枢ZG附近
        recent_low = df['low'].iloc[-5:].min()
        if abs(recent_low - last_seg['zg']) / last_seg['zg'] < 0.02:  # 2%范围内
            trading_points.append({
                'type': '3rd_buy',
                'price': recent_low,
                'confidence': 0.7,
                'condition': 'breakout_pullback'
            })
    
    # 卖点（镜像逻辑）
    if last_seg['direction'] == 'up' and last_fractal and last_fractal['type'] == 'top':
        if len(strokes_df) >= 2:
            prev_stroke = strokes_df.iloc[-2]
            if last_stroke['strength'] < prev_stroke['strength'] * 0.8:
                trading_points.append({
                    'type': '1st_sell',
                    'price': last_fractal['price'],
                    'confidence': 0.8,
                    'condition': 'trend_divergence_top'
                })
    
    return trading_points

def build_features(df: pd.DataFrame, lookback=20) -> pd.DataFrame:
    """根据 OHLCV 构建特征，指标公式均来自 lib.MyTT（通达信/同花顺兼容）"""
    if df is None or len(df) < MIN_BARS:
        return None

    df = df.copy()
    df = df.sort_values("date").reset_index(drop=True)

    C = df["close"].values.astype(float)
    H = df["high"].values.astype(float)
    L = df["low"].values.astype(float)
    V = df["volume"].values.astype(float)
    ref1 = REF(C, 1) + 1e-10

    # 收益率： (C - REF(C,N)) / REF(C,N)，等价于 pct_change
    df["ret_1"] = DIFF(C, 1) / ref1
    df["ret_3"] = (C - REF(C, 3)) / (REF(C, 3) + 1e-10)
    df["ret_5"] = (C - REF(C, 5)) / (REF(C, 5) + 1e-10)
    df["ret_10"] = (C - REF(C, 10)) / (REF(C, 10) + 1e-10)
    df["ret_20"] = (C - REF(C, 20)) / (REF(C, 20) + 1e-10)

    # 均线：MyTT MA(C, N)，close_ma_ratio = C / MA(C, N)
    for w in [5, 10, 20, 60]:
        ma_w = MA(C, w)
        df[f"ma{w}"] = ma_w
        df[f"close_ma{w}_ratio"] = C / (ma_w + 1e-10)

    # RSI 相对强弱指标：MyTT RSI(CLOSE, N)，默认 N=24，此处用 6/12/14
    df["rsi_6"] = RSI(C, 6)
    df["rsi_12"] = RSI(C, 12)
    df["rsi_14"] = RSI(C, 14)

    # 波动率：过去 N 日收益标准差，MyTT STD(S, N)
    ret_1 = df["ret_1"].values
    df["vol_5"] = STD(ret_1, 5)
    df["vol_10"] = STD(ret_1, 10)
    df["vol_20"] = STD(ret_1, 20)

    # 成交量变化：VOL / MA(VOL, 5)
    vol_ma5 = MA(V, 5)
    df["volume_ratio_5"] = V / (vol_ma5 + 1e-10)

    # 振幅：(HIGH - LOW) / REF(CLOSE, 1)
    df["amplitude"] = (H - L) / (REF(C, 1) + 1e-10)

    # MACD：MyTT MACD(CLOSE, SHORT=10, LONG=20, M=7) -> DIF, DEA, MACD柱
    dif, dea, macd_bar = MACD(C, SHORT=10, LONG=20, M=7)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_bar"] = macd_bar

    # BOLL 布林带：MyTT BOLL(CLOSE, N=20, P=2) -> UPPER, MID, LOWER
    boll_upper, boll_mid, boll_lower = BOLL(C, N=20, P=2)
    df["boll_upper"] = boll_upper
    df["boll_mid"] = boll_mid
    df["boll_lower"] = boll_lower
    # 常用衍生：%B = (C - LOWER) / (UPPER - LOWER)，收盘与中轨比，带宽
    boll_range = boll_upper - boll_lower + 1e-10
    df["boll_pct_b"] = (C - boll_lower) / boll_range
    df["boll_close_mid_ratio"] = C / (boll_mid + 1e-10)
    df["boll_width"] = boll_range / (boll_mid + 1e-10)

    # 缠论特征列：先初始化为 0，前 lookback 行及异常时保持为 0
    chan_cols = [
        "last_fractal_type", "last_fractal_strength", "fractal_count",
        "last_stroke_direction", "last_stroke_strength", "stroke_count", "avg_stroke_length",
        "zs_zg_ratio", "zs_zd_ratio", "zs_width_ratio",
        "in_zhongshu", "above_zhongshu", "below_zhongshu",
        "has_buy_signal", "has_sell_signal", "buy_confidence",
    ]
    for col in chan_cols:
        df[col] = 0.0

    # 缠论K线处理（对 lookback 窗口内的数据逐行计算）
    for i in range(lookback, len(df)):
        window_df = df.iloc[i-lookback:i]
        
        try:
            # K线包含处理
            chan_df = process_kline_inclusion(window_df)
            
            # 分型识别
            fractals = find_fractals(chan_df)
            
            # 识别笔
            strokes = identify_strokes(fractals, min_klines=5)
            
            # 识别线段和中枢
            segments = identify_segments(strokes, min_strokes=3)
            
            # 当前价格
            current_price = df['close'].iloc[i]
            
            # 3. 分型特征
            if len(fractals) > 0:
                last_fractal = fractals.iloc[-1]
                df.loc[df.index[i], 'last_fractal_type'] = 1 if last_fractal['type'] == 'top' else -1
                df.loc[df.index[i], 'last_fractal_strength'] = last_fractal['strength'] / current_price
                df.loc[df.index[i], 'fractal_count'] = len(fractals)
            else:
                df.loc[df.index[i], 'last_fractal_type'] = 0
                df.loc[df.index[i], 'last_fractal_strength'] = 0
                df.loc[df.index[i], 'fractal_count'] = 0
            
            # 4. 笔特征
            if len(strokes) > 0:
                last_stroke = strokes.iloc[-1]
                df.loc[df.index[i], 'last_stroke_direction'] = 1 if last_stroke['direction'] == 'up' else -1
                df.loc[df.index[i], 'last_stroke_strength'] = last_stroke['strength'] / current_price
                df.loc[df.index[i], 'stroke_count'] = len(strokes)
                df.loc[df.index[i], 'avg_stroke_length'] = strokes['kline_count'].mean()
            else:
                df.loc[df.index[i], 'last_stroke_direction'] = 0
                df.loc[df.index[i], 'last_stroke_strength'] = 0
                df.loc[df.index[i], 'stroke_count'] = 0
                df.loc[df.index[i], 'avg_stroke_length'] = 0
            
            # 5. 中枢特征
            if len(segments) > 0:
                zs_feats = calculate_zhongshu_features(segments, current_price)
                df.loc[df.index[i], 'zs_zg_ratio'] = zs_feats['price_to_zg']
                df.loc[df.index[i], 'zs_zd_ratio'] = zs_feats['price_to_zd']
                df.loc[df.index[i], 'zs_width_ratio'] = zs_feats['zs_width'] / current_price
                df.loc[df.index[i], 'in_zhongshu'] = zs_feats['in_zs']
                df.loc[df.index[i], 'above_zhongshu'] = zs_feats['above_zs']
                df.loc[df.index[i], 'below_zhongshu'] = zs_feats['below_zs']
            else:
                df.loc[df.index[i], ['zs_zg_ratio', 'zs_zd_ratio', 'zs_width_ratio', 
                                          'in_zhongshu', 'above_zhongshu', 'below_zhongshu']] = 0
            
            # 6. 买卖点特征
            trading_points = identify_trading_points(df.iloc[:i+1], fractals, strokes, segments)
            df.loc[df.index[i], 'has_buy_signal'] = 1 if any(p['type'].endswith('buy') for p in trading_points) else 0
            df.loc[df.index[i], 'has_sell_signal'] = 1 if any(p['type'].endswith('sell') for p in trading_points) else 0
            df.loc[df.index[i], 'buy_confidence'] = max([p['confidence'] for p in trading_points if p['type'].endswith('buy')], default=0)
            
        except Exception:
            # 该时间窗口无法计算缠论特征时，保持初始值 0
            df.loc[df.index[i], chan_cols] = 0

    # 缠论趋势特征（滚动计算）
    df["chan_trend"] = df["last_stroke_direction"].rolling(3, min_periods=1).sum()
    df["fractal_density"] = df["fractal_count"].rolling(5, min_periods=1).mean()

    # 目标：未来 TARGET_DAYS 日收益率
    df["future_ret"] = df["close"].pct_change(TARGET_DAYS).shift(-TARGET_DAYS)
    df["target"] = (df["future_ret"] > TARGET_THRESHOLD).astype(int)

    # 特征列（含缠论），删除含 NaN 的行
    feature_cols = [
        "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
        "close_ma5_ratio", "close_ma10_ratio", "close_ma20_ratio", "close_ma60_ratio",
        "rsi_6", "rsi_12", "rsi_14",
        "macd_dif", "macd_dea", "macd_bar",
        "boll_pct_b", "boll_close_mid_ratio", "boll_width",
        "vol_5", "vol_10", "vol_20",
        "volume_ratio_5",
        "amplitude",
        # 缠论特征
        "last_fractal_type", "last_fractal_strength", "fractal_count",
        "last_stroke_direction", "last_stroke_strength", "stroke_count", "avg_stroke_length",
        "zs_zg_ratio", "zs_zd_ratio", "zs_width_ratio",
        "in_zhongshu", "above_zhongshu", "below_zhongshu",
        "has_buy_signal", "has_sell_signal", "buy_confidence",
        "chan_trend", "fractal_density",
    ]
    df = df.dropna(subset=feature_cols + ["target"])

    if len(df) < 30:
        return None

    return df[["date"] + feature_cols + ["target"]]


def collect_all_samples(symbols: list, start_date: str):
    """汇总多只股票的特征与标签"""
    all_dfs = []
    for i, symbol in enumerate(symbols):
        print(f"  已处理 {i + 1}/{len(symbols)} 只股票")
        try:
            df = get_local_stock_data(symbol, start_date=start_date, frequency="d")
            if df is None or len(df) < MIN_BARS:
                continue
            df_feat = build_features(df)
            if df_feat is None or len(df_feat) == 0:
                continue
            df_feat["symbol"] = symbol
            all_dfs.append(df_feat)
        except Exception as e:
            continue

    if not all_dfs:
        return None
    return pd.concat(all_dfs, ignore_index=True)


def main():
    print("=" * 60)
    print("XGBoost 股票涨跌预测 - 基于本地数据训练")
    print("=" * 60)
    print(f"数据区间: {START_DATE} ~ {END_DATE}")
    print(f"预测目标: 未来 {TARGET_DAYS} 日收益率 > {TARGET_THRESHOLD} 为 1")
    print(f"训练/验证划分: 前 {TRAIN_END_RATIO*100:.0f}% 训练，后 {(1-TRAIN_END_RATIO)*100:.0f}% 验证")
    print("=" * 60)

    # 1. 获取股票列表
    symbols = get_daily_symbols()
    if MAX_SYMBOLS is not None:
        symbols = symbols[:MAX_SYMBOLS]
    print(f"使用股票数量: {len(symbols)}")

    # 2. 构建特征与标签
    print("\n正在构建特征与标签...")
    data = collect_all_samples(symbols, START_DATE)
    if data is None or len(data) == 0:
        print("未获取到有效数据，请检查本地数据库 data/sqlite3.db 及 STOCK_DAILY 表")
        return

    # 按结束日期截断并按时序排序
    data["date"] = pd.to_datetime(data["date"])
    data = data[data["date"] <= END_DATE].reset_index(drop=True)
    if len(data) == 0:
        print("截断至 {} 后无有效数据".format(END_DATE))
        return
    data = data.sort_values("date").reset_index(drop=True)

    feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]
    X = data[feature_cols]
    y = data["target"]

    # 3. 按时间划分训练集与验证集
    n = len(data)
    split_idx = int(n * TRAIN_END_RATIO)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"总样本数: {n}, 训练: {len(X_train)}, 验证: {len(X_val)}")
    print(f"训练集正样本比例: {y_train.mean():.4f}")

    # 4. 训练 XGBoost
    print("\n训练 XGBoost...")
    model = xgb.XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_STATE,
        use_label_encoder=False,
        eval_metric="logloss",
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )

    # 5. 验证集评估
    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)[:, 1]
    acc = accuracy_score(y_val, y_pred)
    auc = roc_auc_score(y_val, y_proba) if len(np.unique(y_val)) > 1 else 0.0
    print("\n验证集结果:")
    print(f"  Accuracy: {acc:.4f}")
    print(f"  AUC:      {auc:.4f}")
    print(classification_report(y_val, y_pred, target_names=["下跌/平", "上涨"]))

    # 6. 保存模型与特征列表
    model_path = os.path.join(TRAIN_DIR, MODEL_NAME)
    model.save_model(model_path)
    print(f"\n模型已保存: {model_path}")

    meta = {
        "feature_cols": feature_cols,
        "target_days": TARGET_DAYS,
        "target_threshold": TARGET_THRESHOLD,
        "train_end_ratio": TRAIN_END_RATIO,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "val_accuracy": round(acc, 4),
        "val_auc": round(auc, 4),
    }
    meta_path = os.path.join(TRAIN_DIR, "train_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"训练元信息已保存: {meta_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
'''
总样本数: 11282251, 训练: 9025800, 验证: 2256451
训练集正样本比例: 0.5006

训练 XGBoost...
/Users/wj/workspace/czsc/czsc_env/lib/python3.11/site-packages/xgboost/training.py:183: UserWarning: [10:26:34] WARNING: /Users/runner/work/xgboost/xgboost/src/learner.cc:738: 
Parameters: { "use_label_encoder" } are not used.

  bst.update(dtrain, iteration=i, fobj=obj)
[0] validation_0-logloss:0.69300
[50]    validation_0-logloss:0.68963
[100]   validation_0-logloss:0.68896
[150]   validation_0-logloss:0.68866
[199]   validation_0-logloss:0.68857

验证集结果:
  Accuracy: 0.5377
  AUC:      0.5463
              precision    recall  f1-score   support

        下跌/平       0.56      0.64      0.59   1194270
          上涨       0.51      0.42      0.46   1062181

    accuracy                           0.54   2256451
   macro avg       0.53      0.53      0.53   2256451
weighted avg       0.53      0.54      0.53   2256451
'''
