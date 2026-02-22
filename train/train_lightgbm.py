# coding: utf-8
"""
使用 LightGBM 训练与 train_xgboost 相同的涨跌预测模型
特征与数据流程与 train_xgboost 完全一致，仅将 XGBoost 替换为 LightGBM。
需安装: pip install lightgbm
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
_train_dir = os.path.dirname(os.path.abspath(__file__))
if _train_dir not in sys.path:
    sys.path.insert(0, _train_dir)

# 复用 XGBoost 脚本的特征构建与数据汇总
from train_xgboost import (
    build_features,
    collect_all_samples,
    MIN_BARS,
    START_DATE,
    END_DATE,
    TARGET_DAYS,
    TARGET_THRESHOLD,
    TRAIN_END_RATIO,
    RANDOM_STATE,
    TRAIN_DIR,
    MAX_SYMBOLS,
)

try:
    import lightgbm as lgb
except ImportError:
    print("请先安装 LightGBM: pip install lightgbm")
    sys.exit(1)

from sklearn.metrics import accuracy_score, classification_report, roc_auc_score

# LightGBM 专用配置
MODEL_NAME = "lightgbm_stock_clf.txt"
META_NAME = "train_meta_lightgbm.json"


def main():
    print("=" * 60)
    print("LightGBM 股票涨跌预测 - 基于本地数据训练")
    print("=" * 60)
    print(f"数据区间: {START_DATE} ~ {END_DATE}")
    print(f"预测目标: 未来 {TARGET_DAYS} 日收益率 > {TARGET_THRESHOLD} 为 1")
    print(f"训练/验证划分: 前 {TRAIN_END_RATIO*100:.0f}% 训练，后 {(1-TRAIN_END_RATIO)*100:.0f}% 验证")
    print("=" * 60)

    from czsc_daily_util import get_daily_symbols

    symbols = get_daily_symbols()
    if MAX_SYMBOLS is not None:
        symbols = symbols[:MAX_SYMBOLS]
    print(f"使用股票数量: {len(symbols)}")

    print("\n正在构建特征与标签...")
    data = collect_all_samples(symbols, START_DATE)
    if data is None or len(data) == 0:
        print("未获取到有效数据，请检查本地数据库 data/sqlite3.db 及 STOCK_DAILY 表")
        return

    data["date"] = pd.to_datetime(data["date"])
    data = data[data["date"] <= END_DATE].reset_index(drop=True)
    if len(data) == 0:
        print("截断至 {} 后无有效数据".format(END_DATE))
        return
    data = data.sort_values("date").reset_index(drop=True)

    feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]
    X = data[feature_cols]
    y = data["target"]

    n = len(data)
    split_idx = int(n * TRAIN_END_RATIO)
    X_train, X_val = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_val = y.iloc[:split_idx], y.iloc[split_idx:]

    print(f"总样本数: {n}, 训练: {len(X_train)}, 验证: {len(X_val)}")
    print(f"训练集正样本比例: {y_train.mean():.4f}")

    print("\n训练 LightGBM...")
    model = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=RANDOM_STATE,
        verbose=-1,
        n_jobs=-1,
        objective="binary",
        metric="binary_logloss",
    )
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        callbacks=[
            lgb.early_stopping(stopping_rounds=50, verbose=False),
            lgb.log_evaluation(period=50),
        ],
    )

    y_pred = model.predict(X_val)
    y_proba = model.predict_proba(X_val)[:, 1]
    acc = accuracy_score(y_val, y_pred)
    auc = roc_auc_score(y_val, y_proba) if len(np.unique(y_val)) > 1 else 0.0
    print("\n验证集结果:")
    print(f"  Accuracy: {acc:.4f}")
    print(f"  AUC:      {auc:.4f}")
    print(classification_report(y_val, y_pred, target_names=["下跌/平", "上涨"]))

    model_path = os.path.join(TRAIN_DIR, MODEL_NAME)
    model.booster_.save_model(model_path)
    print(f"\n模型已保存: {model_path}")

    meta = {
        "feature_cols": feature_cols,
        "target_days": TARGET_DAYS,
        "target_threshold": TARGET_THRESHOLD,
        "train_end_ratio": TRAIN_END_RATIO,
        "start_date": START_DATE,
        "end_date": END_DATE,
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "model_type": "lightgbm",
        "val_accuracy": round(acc, 4),
        "val_auc": round(auc, 4),
    }
    meta_path = os.path.join(TRAIN_DIR, META_NAME)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"训练元信息已保存: {meta_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
