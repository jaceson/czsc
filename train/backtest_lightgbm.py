# coding: utf-8
"""
LightGBM 模型回测脚本
训练完成后运行此脚本，加载 train/lightgbm_stock_clf.txt 与 train_meta_lightgbm.json，
在指定回测区间内按「信号日次日开盘买入、持有 TARGET_DAYS 日后收盘卖出」规则统计收益。
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_train_dir = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
if _train_dir not in sys.path:
    sys.path.insert(0, _train_dir)

from czsc_daily_util import get_daily_symbols, get_data_dir
from czsc_sqlite import get_local_stock_data

try:
    import lightgbm as lgb
except ImportError:
    print("请先安装 LightGBM: pip install lightgbm")
    sys.exit(1)

from train_xgboost import build_features, MIN_BARS

# 回测配置
TRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = "lightgbm_stock_clf.txt"
META_NAME = "train_meta_lightgbm.json"
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2024-12-31"
PROBA_THRESHOLD = 0.5
MAX_SYMBOLS_BACKTEST = None


def load_model_and_meta():
    """加载 LightGBM 模型（Booster）和训练元信息"""
    model_path = os.path.join(TRAIN_DIR, MODEL_NAME)
    meta_path = os.path.join(TRAIN_DIR, META_NAME)
    if not os.path.isfile(model_path) or not os.path.isfile(meta_path):
        raise FileNotFoundError(
            "未找到模型或元信息文件，请先运行 train_lightgbm.py 完成训练。\n"
            "需要存在: {} 与 {}".format(model_path, meta_path)
        )
    model = lgb.Booster(model_file=model_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    feature_cols = meta["feature_cols"]
    target_days = int(meta["target_days"])
    return model, feature_cols, target_days, meta


def run_backtest_for_symbol(symbol: str, model, feature_cols: list, target_days: int,
                            start_date: str, end_date: str):
    """
    单只股票回测：构建特征 -> 预测 -> 按「次日开盘买、TARGET_DAYS 日后收盘卖」计算收益。
    model 为 LightGBM Booster，predict 返回正类概率。
    """
    df_raw = get_local_stock_data(symbol, start_date=start_date, frequency="d")
    if df_raw is None or len(df_raw) < MIN_BARS:
        return []
    df_raw = df_raw.sort_values("date").reset_index(drop=True)
    df_raw["date"] = pd.to_datetime(df_raw["date"])

    df_feat = build_features(df_raw)
    if df_feat is None or len(df_feat) == 0:
        return []
    df_feat["date"] = pd.to_datetime(df_feat["date"])
    df_feat = df_feat[(df_feat["date"] >= start_date) & (df_feat["date"] <= end_date)]
    if len(df_feat) == 0:
        return []

    X = df_feat[feature_cols]
    # Booster.predict 对二分类返回正类概率
    proba = model.predict(X)
    if proba.ndim > 1:
        proba = proba[:, 1]
    pred = (proba >= PROBA_THRESHOLD).astype(int)

    raw_dates = pd.to_datetime(df_raw["date"]).dt.strftime("%Y-%m-%d").values
    date_to_idx = {d: i for i, d in enumerate(raw_dates)}
    trades = []
    for pos, (_, row) in enumerate(df_feat.iterrows()):
        if pred[pos] == 0:
            continue
        d = row["date"]
        if isinstance(d, pd.Timestamp):
            d = d.strftime("%Y-%m-%d")
        idx = date_to_idx.get(d)
        if idx is None:
            continue
        buy_idx = idx + 1
        sell_idx = idx + 1 + target_days
        if sell_idx >= len(df_raw):
            continue
        buy_price = float(df_raw.iloc[buy_idx]["open"])
        sell_price = float(df_raw.iloc[sell_idx]["close"])
        ret = (sell_price - buy_price) / (buy_price + 1e-10)
        trades.append({
            "date": d,
            "symbol": symbol,
            "ret": ret,
            "proba": float(proba[pos]),
            "buy_price": buy_price,
            "sell_price": sell_price,
        })
    return trades


def main():
    print("=" * 60)
    print("LightGBM 模型回测")
    print("=" * 60)

    model, feature_cols, target_days, meta = load_model_and_meta()
    print("已加载模型: {}".format(os.path.join(TRAIN_DIR, MODEL_NAME)))
    print("特征数: {}, 持有天数: {}".format(len(feature_cols), target_days))
    print("回测区间: {} ~ {}".format(BACKTEST_START, BACKTEST_END))
    print("信号阈值: 预测概率 >= {}".format(PROBA_THRESHOLD))
    print("规则: 信号日次日开盘买入，持有 {} 日后收盘卖出".format(target_days))
    print("=" * 60)

    symbols = get_daily_symbols()
    if MAX_SYMBOLS_BACKTEST is not None:
        symbols = symbols[:MAX_SYMBOLS_BACKTEST]
    print("回测股票数: {}".format(len(symbols)))

    all_trades = []
    for i, symbol in enumerate(symbols):
        if (i + 1) % 100 == 0:
            print("  已回测 {}/{} 只股票".format(i + 1, len(symbols)))
        try:
            trades = run_backtest_for_symbol(
                symbol, model, feature_cols, target_days,
                BACKTEST_START, BACKTEST_END,
            )
            all_trades.extend(trades)
        except Exception:
            continue

    if not all_trades:
        print("回测区间内无有效交易，请检查数据与回测区间。")
        return

    rets = np.array([t["ret"] for t in all_trades])
    n = len(rets)
    win_rate = (rets > 0).mean() * 100
    avg_ret = rets.mean() * 100
    total_ret_compound = (np.prod(1 + rets) - 1) * 100

    df_trades = pd.DataFrame(all_trades)
    df_trades["date"] = pd.to_datetime(df_trades["date"])
    df_trades = df_trades.sort_values("date").reset_index(drop=True)
    equity = (1 + df_trades["ret"]).cumprod()
    peak = equity.cummax()
    drawdown = (equity - peak) / (peak + 1e-10)
    max_dd = drawdown.min() * 100

    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print("交易次数:       {}".format(n))
    print("胜率:           {:.2f}%".format(win_rate))
    print("平均单笔收益:   {:.2f}%".format(avg_ret))
    print("累计收益(复利): {:.2f}%".format(total_ret_compound))
    print("最大回撤:       {:.2f}%".format(max_dd))
    print("=" * 60)

    out_path = os.path.join(TRAIN_DIR, "backtest_trades_lightgbm.csv")
    df_trades.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("交易明细已保存: {}".format(out_path))


if __name__ == "__main__":
    main()
