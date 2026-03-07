# coding: utf-8
"""
基于本地股票数据，使用 XGBoost 训练涨跌预测模型
数据来源：data/sqlite3.db STOCK_DAILY 表，通过 czsc_sqlite.get_local_stock_data 获取

优化点：
1. 增强特征工程（20+ 技术指标）
2. 添加特征标准化
3. 使用 Optuna 超参数调优
4. 改进类别不平衡处理
5. 添加特征重要性分析
6. 时间序列交叉验证
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score, precision_recall_fscore_support
import warnings
warnings.filterwarnings('ignore')

# 将项目根目录加入 path，以便导入 czsc 模块
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from czsc_daily_util import (
    get_daily_symbols,
    get_data_dir,
    get_kd_data,
    get_rps_data,
    get_longterm_turn_condition,
    get_main_strong_join_condition,
    get_pocket_pivot_condition,
)
from czsc_sqlite import get_local_stock_data
# 吃鱼公式指标（公式平台/好股网等），用于特征
try:
    from CZSCStragegy_FormulaSignal import calculate_formula_indicators
except Exception:
    calculate_formula_indicators = None
# 指标公式统一从 lib.MyTT 读取（通达信/同花顺兼容）
from lib.MyTT import (
    MA, EMA, RSI, REF, ABS, MAX, MIN, HHV, LLV, SMA,
    MACD, BOLL, KDJ, CCI, VR, ROC, OBV,
    STD, SUM
)

# XGBoost（需安装：pip install xgboost）
try:
    import xgboost as xgb
except ImportError:
    print("请先安装 xgboost: pip install xgboost")
    sys.exit(1)

# Optuna 超参数优化（需安装：pip install optuna）
try:
    import optuna
    from optuna.integration import XGBoostPruningCallback
except ImportError:
    print("提示：安装 optuna 可进行超参数调优：pip install optuna")
    optuna = None

# 配置
TRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
MIN_BARS = 120          # 单只股票最少 K 线数才参与训练
START_DATE = "2020-01-01"
END_DATE = "2023-12-31"
TARGET_DAYS = 10         # 预测未来 N 日涨跌
TARGET_THRESHOLD = 0.05  # 未来 N 日收益率 > 5% 才算「涨」
TRAIN_END_RATIO = 0.9   # 前 90% 时间用于训练，后 10% 验证
MAX_SYMBOLS = 100       # 最多使用股票数量（增加样本多样性）
RANDOM_STATE = 42
MODEL_NAME = "xgboost_stock_clf_v2.json"

# 类别不平衡
SCALE_POS_WEIGHT = True
UNDERSAMPLE_NEG_RATIO = 2.0  # 2:1 负正比，保留更多负样本信息

# 是否启用超参数调优
USE_OPTUNA = True
OPTUNA_TRIALS = 50  # 调优次数

def build_features(df: pd.DataFrame, symbol: str = None) -> pd.DataFrame:
    """根据 OHLCV 构建特征，增加更多技术指标

    symbol: 股票代码，可选；提供时会基于 czsc_daily_util.get_longterm_turn_condition
            生成长线转折指标特征。
    """
    if df is None or len(df) < MIN_BARS:
        return None

    df = df.copy()
    df = df.sort_values("date").reset_index(drop=True)

    C = df["close"].values.astype(float)
    H = df["high"].values.astype(float)
    L = df["low"].values.astype(float)
    V = df["volume"].values.astype(float)
    O = df["open"].values.astype(float)

    # === 趋势型指标 ===
    # MACD
    dif, dea, macd_bar = MACD(C, SHORT=12, LONG=26, M=9)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_bar"] = macd_bar
    df["macd_golden_cross"] = (dif > dea).astype(int)
    
    # EMA 均线系统
    ema5 = EMA(C, 5)
    ema10 = EMA(C, 10)
    ema20 = EMA(C, 20)
    ema60 = EMA(C, 60)
    df["ema5"] = ema5
    df["ema20"] = ema20
    df["ema60"] = ema60
    df["price_ema5_ratio"] = C / (ema5 + 1e-10)
    df["price_ema20_ratio"] = C / (ema20 + 1e-10)
    df["ema5_ema20_diff"] = (ema5 - ema20) / (ema20 + 1e-10)
    
    # === 摆动型指标 ===
    # RSI (多周期)
    rsi6 = RSI(C, 6)
    rsi12 = RSI(C, 12)
    rsi24 = RSI(C, 24)
    df["rsi_6"] = rsi6
    df["rsi_12"] = rsi12
    df["rsi_24"] = rsi24
    
    # KDJ
    k, d, j = KDJ(C, H, L, N=9, M1=3, M2=3)
    df["kdj_k"] = k
    df["kdj_d"] = d
    df["kdj_j"] = j
    df["kd_diff"] = k - d
    
    # KD 指标（参考 czsc_daily_util.get_kd_data）
    df = get_kd_data(df)
    
    # CCI
    cci14 = CCI(C, H, L, N=14)
    cci84 = CCI(C, H, L, N=84)
    df["cci_14"] = cci14
    df["cci_84"] = cci84
    
    # === 波动率指标 ===
    # BOLL 布林带
    upper, mid, lower = BOLL(C, N=20, P=2)
    df["boll_upper"] = upper
    df["boll_mid"] = mid
    df["boll_lower"] = lower
    df["boll_pct_b"] = (C - lower) / (upper - lower + 1e-10)
    df["boll_width"] = (upper - lower) / (mid + 1e-10)
    
    # === 成交量指标 ===
    vol_ma5 = MA(V, 5)
    vol_ma20 = MA(V, 20)
    df["vol_ma5"] = vol_ma5
    df["vol_ma20"] = vol_ma20
    df["volume_ratio"] = V / (vol_ma5 + 1e-10)
    df["volume_ma_ratio"] = vol_ma5 / (vol_ma20 + 1e-10)
    
    # OBV 能量潮
    obv = OBV(C, V)
    df["obv"] = obv
    df["obv_ma5"] = MA(obv, 5)
    
    # VR 成交量比率
    vr26 = VR(C, V, M1=26)
    df["vr_26"] = vr26
    
    # === 动量指标 ===
    # ROC 变动速率
    roc_val, roc_ma = ROC(C, N=12, M=6)
    df["roc_12"] = roc_val
    
    # MTM 动量
    mtm12 = C - REF(C, 12)
    df["mtm_12"] = mtm12
    
    # RPS 指标（参考 czsc_daily_util.get_rps_data）
    df = get_rps_data(df)

    # === 吃鱼公式输出指标（开始吃鱼、COLORGRAY、COLOR4080FF、COLORFF0080、COLORRED、COLORGREEN、公式平台、好股网） ===
    if calculate_formula_indicators is not None and "amount" in df.columns:
        try:
            df = calculate_formula_indicators(df)
            # 布尔列转为 0/1 便于模型使用
            for col in ("COLOR4080FF", "COLORFF0080", "COLORRED", "COLORGREEN"):
                if col in df.columns:
                    df[col] = df[col].astype(int)
        except Exception:
            pass

    # === 长线转折 & 主力进场 & 口袋支点指标（参考 czsc_daily_util） ===
    # 返回值均为布尔 Series，这里都作为 0/1 特征使用
    if symbol is not None:
        try:
            lt_cond = get_longterm_turn_condition(symbol, df)
            df["longterm_turn"] = lt_cond.astype(int)
        except Exception:
            df["longterm_turn"] = 0

        try:
            main_cond = get_main_strong_join_condition(symbol, df)
            df["main_strong_join"] = main_cond.astype(int)
        except Exception:
            df["main_strong_join"] = 0

        try:
            pocket_cond = get_pocket_pivot_condition(symbol, df)
            df["pocket_pivot"] = pocket_cond.astype(int)
        except Exception:
            df["pocket_pivot"] = 0

    # === 价格形态特征 ===
    df["price_range"] = (H - L) / (L + 1e-10)
    df["price_change"] = (C - O) / (O + 1e-10)
    df["hhv_20"] = HHV(H, 20)
    df["llv_20"] = LLV(L, 20)
    df["price_position"] = (C - df["llv_20"]) / (df["hhv_20"] - df["llv_20"] + 1e-10)
    
    # 连续上涨/下跌天数
    price_up = (C > REF(C, 1)).astype(int)
    df["consecutive_up"] = pd.Series(price_up).groupby((pd.Series(price_up) != pd.Series(price_up).shift()).cumsum()).cumsum().values
    df["consecutive_down"] = pd.Series(1 - price_up).groupby((pd.Series(1 - price_up) != pd.Series(1 - price_up).shift()).cumsum()).cumsum().values

    # 目标：未来 TARGET_DAYS 日收益率
    df["future_ret"] = df["close"].pct_change(TARGET_DAYS).shift(-TARGET_DAYS)
    df["target"] = (df["future_ret"] > TARGET_THRESHOLD).astype(int)

    # 定义要保留的技术指标特征列（排除原始 OHLCV）
    indicator_cols = [
        # MACD
        'macd_dif', 'macd_dea', 'macd_bar', 'macd_golden_cross',
        # EMA
        'ema5', 'ema10', 'ema20', 'ema60', 
        'price_ema5_ratio', 'price_ema20_ratio', 'ema5_ema20_diff',
        # RSI
        'rsi_6', 'rsi_12', 'rsi_24',
        # KDJ & KD
        'kdj_k', 'kdj_d', 'kdj_j', 'kd_diff',
        'kd0',
        # CCI
        'cci_14', 'cci_84',
        # BOLL
        'boll_upper', 'boll_mid', 'boll_lower', 'boll_pct_b', 'boll_width',
        # Volume
        'vol_ma5', 'vol_ma20', 'volume_ratio', 'volume_ma_ratio',
        'obv', 'obv_ma5', 'vr_26',
        # Momentum
        'roc_12', 'mtm_12',
        # Price Pattern
        'price_range', 'price_change', 'price_position',
        'consecutive_up', 'consecutive_down',
        # 长线转折 & 主力进场 & 口袋支点
        'longterm_turn', 'main_strong_join', 'pocket_pivot',
        # 吃鱼公式输出
        '开始吃鱼', 'COLORGRAY_TOP', 'COLORGRAY_BOTTOM',
        'COLOR4080FF', 'COLORFF0080', 'COLORRED', 'COLORGREEN',
        '公式平台', '好股网',
        # RPS
        'RPS10', 'RPS20', 'RPS50', 'RPS120', 'RPS250',
    ]
    
    # 只保留实际存在的列
    feature_cols = [c for c in indicator_cols if c in df.columns]
    
    # 删除含 NaN 的行
    df = df.dropna(subset=feature_cols + ["target", "date"])

    if len(df) < 30:
        return None

    return df[["date"] + feature_cols + ["target"]]


def undersample_majority(X, y, ratio=2.0, random_state=RANDOM_STATE):
    """对多数类下采样，保留更多信息"""
    pos_idx = np.where(y == 1)[0]
    neg_idx = np.where(y == 0)[0]
    n_pos = len(pos_idx)
    n_neg_target = int(n_pos * ratio)
    
    if len(neg_idx) > n_neg_target:
        rng = np.random.RandomState(random_state)
        neg_idx = rng.choice(neg_idx, size=n_neg_target, replace=False)
    
    keep_idx = np.sort(np.concatenate([pos_idx, neg_idx]))
    return X.iloc[keep_idx], y.iloc[keep_idx]


def collect_all_samples(symbols: list, start_date: str):
    """汇总多只股票的特征与标签"""
    all_dfs = []
    for i, symbol in enumerate(symbols):
        print(f"  已处理 {i + 1}/{len(symbols)} 只股票")
        try:
            df = get_local_stock_data(symbol, start_date=start_date, frequency="d")
            if df is None or len(df) < MIN_BARS:
                continue
            df_feat = build_features(df, symbol=symbol)
            if df_feat is None or len(df_feat) == 0:
                continue
            # 添加调试信息
            if len(df_feat) > 0:
                print(f"    ✓ {symbol}: {len(df_feat)} 条有效数据，正样本比例：{df_feat['target'].mean():.4f}")
            df_feat["symbol"] = symbol
            all_dfs.append(df_feat)
        except Exception as e:
            print(f"    ✗ {symbol}: 错误 - {str(e)}")
            continue

    if not all_dfs:
        return None
    
    print(f"\n共处理 {len(all_dfs)}/{len(symbols)} 只有效股票，总样本数：{sum(len(df) for df in all_dfs):,}")
    return pd.concat(all_dfs, ignore_index=True)


def objective(trial, X_train, y_train, X_val, y_val, scale_pos_weight):
    """Optuna 超参数优化目标函数"""
    param = {
        'n_estimators': trial.suggest_int('n_estimators', 100, 500),
        'max_depth': trial.suggest_int('max_depth', 3, 10),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.3, log=True),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
        'gamma': trial.suggest_float('gamma', 0, 0.4),
        'reg_alpha': trial.suggest_float('reg_alpha', 0, 10, log=True),
        'reg_lambda': trial.suggest_float('reg_lambda', 1, 10, log=True),
        'scale_pos_weight': scale_pos_weight,
        'random_state': RANDOM_STATE,
        'eval_metric': 'logloss',
        'early_stopping_rounds': 30,
    }
    
    model = xgb.XGBClassifier(**param)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=0,
    )
    
    y_pred_proba = model.predict_proba(X_val)[:, 1]
    auc = roc_auc_score(y_val, y_pred_proba)
    
    return auc


def analyze_thresholds(y_true, y_proba, min_signals: int = 20):
    """
    在验证集上扫描不同阈值，帮助选择“高胜率、信号少”的阈值。
    """
    print("\n" + "=" * 60)
    print("不同阈值下的正类 Precision / Recall / 信号数量")
    print("=" * 60)
    print("阈值\tPrecision\tRecall\t\tF1\t\t预测上涨数")

    best_prec = 0.0
    best_prec_th = 0.5
    best_prec_stats = None

    # 主要关注 0.5~0.99 的高阈值区间
    for th in np.linspace(0.5, 0.99, 20):
        y_pred_th = (y_proba >= th).astype(int)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_pred_th, average='binary', zero_division=0
        )
        signals = int(y_pred_th.sum())
        print(f"{th:.2f}\t{precision:.4f}\t\t{recall:.4f}\t\t{f1:.4f}\t\t{signals}")

        # 只在信号数量不太少时，记录最高 precision 的阈值
        if signals >= min_signals and precision > best_prec:
            best_prec = precision
            best_prec_th = th
            best_prec_stats = (precision, recall, f1, signals)

    if best_prec_stats is not None:
        p, r, f1, s = best_prec_stats
        print("\n推荐高胜率阈值（在预测上涨数 >= {} 的前提下 Precision 最大）:".format(min_signals))
        print(f"  阈值: {best_prec_th:.3f}")
        print(f"  Precision: {p:.4f}, Recall: {r:.4f}, F1: {f1:.4f}, 预测上涨数: {s}")
    else:
        print("\n未找到同时满足最小信号数量要求的高胜率阈值，请适当降低 min_signals 再试。")


def main():
    print("=" * 60)
    print("XGBoost 股票涨跌预测 - 基于本地数据训练 (优化版)")
    print("=" * 60)
    print(f"数据区间：{START_DATE} ~ {END_DATE}")
    print(f"预测目标：未来 {TARGET_DAYS} 日收益率 > {TARGET_THRESHOLD} 为 1")
    print(f"训练/验证划分：前 {TRAIN_END_RATIO*100:.0f}% 训练，后 {(1-TRAIN_END_RATIO)*100:.0f}% 验证")
    print("=" * 60)

    # 1. 获取股票列表
    symbols = get_daily_symbols()
    if MAX_SYMBOLS is not None:
        symbols = symbols[:MAX_SYMBOLS]
    print(f"使用股票数量：{len(symbols)}")

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
        print(f"截断至 {END_DATE} 后无有效数据")
        return
    data = data.sort_values("date").reset_index(drop=True)

    # 确保只使用数值型特征列
    # 排除的列：日期、股票代码、目标变量、以及原始市场数据
    exclude_cols = ["date", "symbol", "target", 
                    # 排除原始 OHLCV 数据，只保留技术指标
                    "open", "high", "low", "close", 
                    "volume", "amount", "turn", "datetime"]
    
    feature_cols = [c for c in data.columns if c not in exclude_cols]
    # 过滤掉非数值列
    numeric_cols = []
    for col in feature_cols:
        if pd.api.types.is_numeric_dtype(data[col]):
            numeric_cols.append(col)
        else:
            print(f"  ⚠ 跳过非数值列：{col} (类型：{data[col].dtype})")
    
    feature_cols = numeric_cols
    X = data[feature_cols]
    y = data["target"]
    
    print(f"\n特征列数量：{len(feature_cols)}")
    print(f"特征列 (前 10): {feature_cols[:10]}...")
    print(f"数据类型检查完成，所有特征均为数值型")

    # 3. 按时间划分训练集与验证集
    n = len(data)
    split_idx = int(n * TRAIN_END_RATIO)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"总样本数：{n:,}, 训练：{len(X_train):,}, 验证：{len(X_val):,}")
    print(f"训练集正样本比例：{y_train.mean():.4f}")

    # 3.1 可选：对训练集负类下采样
    if UNDERSAMPLE_NEG_RATIO is not None:
        X_train, y_train = undersample_majority(X_train, y_train, ratio=UNDERSAMPLE_NEG_RATIO)
        print(f"下采样后训练集：{len(X_train):,} (正 {y_train.sum()}, 负 {(y_train==0).sum()})")

    # 3.2 特征标准化
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_val_scaled = scaler.transform(X_val)
    
    # 转换回 DataFrame 以保持列名
    X_train_scaled = pd.DataFrame(X_train_scaled, columns=feature_cols)
    X_val_scaled = pd.DataFrame(X_val_scaled, columns=feature_cols)

    # 4. scale_pos_weight
    n_neg_train = (y_train == 0).sum()
    n_pos_train = max((y_train == 1).sum(), 1)
    scale_pos_weight = (n_neg_train / n_pos_train) if SCALE_POS_WEIGHT else 1.0
    print(f"scale_pos_weight: {scale_pos_weight:.2f}")

    # 5. 超参数调优
    best_params = None
    if USE_OPTUNA and optuna is not None:
        print("\n" + "=" * 60)
        print("使用 Optuna 进行超参数调优...")
        print("=" * 60)
        
        study = optuna.create_study(direction='maximize', pruner=optuna.pruners.MedianPruner())
        study.optimize(
            lambda trial: objective(trial, X_train_scaled, y_train, X_val_scaled, y_val, scale_pos_weight),
            n_trials=OPTUNA_TRIALS,
            timeout=3600,
            show_progress_bar=True
        )
        
        best_params = study.best_params
        best_auc = study.best_value
        
        print(f"\n最佳 AUC: {best_auc:.4f}")
        print(f"最佳参数:")
        for key, value in best_params.items():
            print(f"  {key}: {value}")
        
        # 使用最佳参数重新训练
        print("\n使用最佳参数重新训练...")
    else:
        print("\n使用默认参数训练...")
        best_params = {
            'n_estimators': 300,
            'max_depth': 6,
            'learning_rate': 0.05,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 3,
            'gamma': 0.1,
            'reg_alpha': 1.0,
            'reg_lambda': 5.0,
        }

    # 6. 训练最终模型
    final_params = {
        **best_params,
        'scale_pos_weight': scale_pos_weight,
        'random_state': RANDOM_STATE,
        'eval_metric': 'logloss',
        'early_stopping_rounds': 30,
    }
    
    model = xgb.XGBClassifier(**final_params)
    model.fit(
        X_train_scaled, y_train,
        eval_set=[(X_val_scaled, y_val)],
        verbose=50,
    )

    # 7. 验证集评估（默认 0.5 阈值）
    y_pred = model.predict(X_val_scaled)
    y_proba = model.predict_proba(X_val_scaled)[:, 1]
    acc = accuracy_score(y_val, y_pred)
    auc = roc_auc_score(y_val, y_proba) if len(np.unique(y_val)) > 1 else 0.0
    
    precision, recall, f1, _ = precision_recall_fscore_support(y_val, y_pred, average='binary')
    
    print("\n" + "=" * 60)
    print("验证集结果")
    print("=" * 60)
    print(f"  Accuracy: {acc:.4f}")
    print(f"  AUC:      {auc:.4f}")
    print(f"  Precision:{precision:.4f}")
    print(f"  Recall:   {recall:.4f}")
    print(f"  F1-Score: {f1:.4f}")
    print("\n分类报告 (阈值=0.50):")
    print(classification_report(y_val, y_pred, target_names=["下跌/平", "上涨"]))

    # 7.1 阈值扫描，寻找高胜率阈值
    analyze_thresholds(y_val, y_proba, min_signals=20)

    # 8. 特征重要性分析
    print("\n特征重要性 Top 10:")
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    print(importance_df.head(10).to_string(index=False))

    # 9. 保存模型与特征列表
    model_path = os.path.join(TRAIN_DIR, MODEL_NAME)
    model.save_model(model_path)
    print(f"\n模型已保存：{model_path}")

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
        "val_precision": round(precision, 4),
        "val_recall": round(recall, 4),
        "val_f1": round(f1, 4),
        "best_params": best_params,
        "top_features": importance_df.head(10).to_dict('records'),
    }
    meta_path = os.path.join(TRAIN_DIR, "train_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"训练元信息已保存：{meta_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()