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
    MA, EMA, RSI, REF, MAX, ABS,
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
START_DATE = "2020-01-01"
END_DATE = "2023-12-31"
TARGET_DAYS = 10         # 预测未来 N 日涨跌
TARGET_THRESHOLD = 0.05  # 未来 N 日收益率 > 15% 才算「涨」，严格正类以追求 90%+ 胜率
TRAIN_END_RATIO = 0.9   # 前 80% 时间用于训练，后 20% 验证
MAX_SYMBOLS = 500       # 最多使用股票数量（可调大或设为 None 表示全部）
RANDOM_STATE = 42
MODEL_NAME = "xgboost_stock_clf.json"
# 类别不平衡
SCALE_POS_WEIGHT = True
UNDERSAMPLE_NEG_RATIO = 1.0  # 1:1 负正比，利于学准「大涨」边界

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

    # MACD：MyTT MACD(CLOSE, SHORT=10, LONG=20, M=7) -> DIF, DEA, MACD柱
    dif, dea, macd_bar = MACD(C, SHORT=10, LONG=20, M=7)
    df["macd_dif"] = dif
    df["macd_dea"] = dea
    df["macd_bar"] = macd_bar

    # KD指标
    VAR = (C - LLV(L, 10)) / (HHV(H, 10) - LLV(L, 10)) * 100
    K0 = SMA(VAR, 10, 1)
    D0 = REF(K0, 1)
    df['KD'] = K0-D0

    # 目标：未来 TARGET_DAYS 日收益率
    df["future_ret"] = df["close"].pct_change(TARGET_DAYS).shift(-TARGET_DAYS)
    df["target"] = (df["future_ret"] > TARGET_THRESHOLD).astype(int)

    # 特征列，删除含 NaN 的行
    feature_cols = [
        "macd_dif", "macd_dea", "macd_bar", "KD"
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

    # 3.1 可选：对训练集负类下采样，缓解类别不平衡
    if UNDERSAMPLE_NEG_RATIO is not None:
        pos_idx = np.where(y_train == 1)[0]
        neg_idx = np.where(y_train == 0)[0]
        n_pos = len(pos_idx)
        n_neg_max = int(n_pos * UNDERSAMPLE_NEG_RATIO)
        if len(neg_idx) > n_neg_max:
            rng = np.random.RandomState(RANDOM_STATE)
            neg_idx = rng.choice(neg_idx, size=n_neg_max, replace=False)
        keep_idx = np.sort(np.concatenate([pos_idx, neg_idx]))
        X_train = X_train.iloc[keep_idx].reset_index(drop=True)
        y_train = y_train.iloc[keep_idx].reset_index(drop=True)
        print(f"下采样后训练集: {len(X_train)} (正 {n_pos}, 负 {len(neg_idx)})")

    # 4. scale_pos_weight：按训练集负/正比例，提高正类权重
    n_neg_train = (y_train == 0).sum()
    n_pos_train = max((y_train == 1).sum(), 1)
    scale_pos_weight = (n_neg_train / n_pos_train) if SCALE_POS_WEIGHT else 1.0
    print(f"scale_pos_weight: {scale_pos_weight:.2f}")

    # 5. 训练 XGBoost
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
        scale_pos_weight=scale_pos_weight,
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )

    # 6. 验证集评估
    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)[:, 1]
    acc = accuracy_score(y_val, y_pred)
    auc = roc_auc_score(y_val, y_proba) if len(np.unique(y_val)) > 1 else 0.0
    print("\n验证集结果:")
    print(f"  Accuracy: {acc:.4f}")
    print(f"  AUC:      {auc:.4f}")
    print(classification_report(y_val, y_pred, target_names=["下跌/平", "上涨"]))

    # 7. 保存模型与特征列表
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
