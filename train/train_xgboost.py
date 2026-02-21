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


def build_features(df: pd.DataFrame) -> pd.DataFrame:
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

    # 目标：未来 TARGET_DAYS 日收益率
    df["future_ret"] = df["close"].pct_change(TARGET_DAYS).shift(-TARGET_DAYS)
    df["target"] = (df["future_ret"] > TARGET_THRESHOLD).astype(int)

    # 删除含 NaN 的行（前面 rolling 产生的）
    feature_cols = [
        "ret_1", "ret_3", "ret_5", "ret_10", "ret_20",
        "close_ma5_ratio", "close_ma10_ratio", "close_ma20_ratio", "close_ma60_ratio",
        "rsi_6", "rsi_12", "rsi_14",
        "macd_dif", "macd_dea", "macd_bar",
        "boll_pct_b", "boll_close_mid_ratio", "boll_width",
        "vol_5", "vol_10", "vol_20",
        "volume_ratio_5",
        "amplitude",
    ]
    df = df.dropna(subset=feature_cols + ["target"])

    if len(df) < 30:
        return None

    return df[["date"] + feature_cols + ["target"]]


def collect_all_samples(symbols: list, start_date: str):
    """汇总多只股票的特征与标签"""
    all_dfs = []
    for i, symbol in enumerate(symbols):
        if (i + 1) % 100 == 0:
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
