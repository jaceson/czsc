# coding: utf-8
"""
XGBoost 模型回测脚本
训练完成后运行此脚本，加载 train/xgboost_stock_clf.json 与 train_meta.json，
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
    import xgboost as xgb
except ImportError:
    print("请先安装 xgboost: pip install xgboost")
    sys.exit(1)

# 从训练脚本复用特征构建
from train_xgboost import build_features, MIN_BARS

# 回测配置
TRAIN_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = "xgboost_stock_clf.json"
META_NAME = "train_meta.json"
BACKTEST_START = "2024-01-01"   # 回测起始日（建议在训练结束之后）
BACKTEST_END = "2024-12-31"     # 回测结束日
PROBA_THRESHOLD = 0.55          # 预测概率 >= 此阈值才发出买入信号（在「按概率阈值」模式下无效）
USE_TOP_PCT_BY_PROBA = 2        # 只做概率最高的 N% 信号（2 更精选、追求高胜率；5 交易更多；0=按 PROBA_THRESHOLD）
WIN_RATE_TARGET = 90.0
MIN_TRADES_AT_TARGET = 10
MAX_SYMBOLS_BACKTEST = 200


def load_model_and_meta():
    """加载模型和训练元信息"""
    model_path = os.path.join(TRAIN_DIR, MODEL_NAME)
    meta_path = os.path.join(TRAIN_DIR, META_NAME)
    if not os.path.isfile(model_path) or not os.path.isfile(meta_path):
        raise FileNotFoundError(
            "未找到模型或元信息文件，请先运行 train_xgboost.py 完成训练。\n"
            "需要存在: {} 与 {}".format(model_path, meta_path)
        )
    model = xgb.XGBClassifier()
    model.load_model(model_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    feature_cols = meta["feature_cols"]
    target_days = int(meta["target_days"])
    return model, feature_cols, target_days, meta


def run_backtest_for_symbol(symbol: str, model, feature_cols: list, target_days: int,
                            start_date: str, end_date: str, proba_threshold: float = None):
    """
    单只股票回测：构建特征 -> 预测 -> 按「次日开盘买、TARGET_DAYS 日后收盘卖」计算收益。
    proba_threshold 为 None 时使用全局 PROBA_THRESHOLD；设为 0 可返回所有信号用于「按概率取前 N%」.
    返回 list of dict: [{"date", "symbol", "ret", "proba", "buy_price", "sell_price"}, ...]
    """
    if proba_threshold is None:
        proba_threshold = PROBA_THRESHOLD
    df_raw = get_local_stock_data(symbol, start_date=start_date, frequency="d")
    if df_raw is None or len(df_raw) < MIN_BARS:
        return []
    df_raw = df_raw.sort_values("date").reset_index(drop=True)
    df_raw["date"] = pd.to_datetime(df_raw["date"])

    df_feat = build_features(df_raw)
    if df_feat is None or len(df_feat) == 0:
        return []
    df_feat["date"] = pd.to_datetime(df_feat["date"])
    # 仅保留回测区间内的信号
    df_feat = df_feat[(df_feat["date"] >= start_date) & (df_feat["date"] <= end_date)]
    if len(df_feat) == 0:
        return []

    X = df_feat[feature_cols]
    proba = model.predict_proba(X)[:, 1]
    pred = (proba >= proba_threshold).astype(int)

    # 对齐 raw 的日期索引，用于取次日开盘、TARGET_DAYS 日后收盘
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
    print("XGBoost 模型回测")
    print("=" * 60)

    model, feature_cols, target_days, meta = load_model_and_meta()
    print("已加载模型: {}".format(os.path.join(TRAIN_DIR, MODEL_NAME)))
    print("特征数: {}, 持有天数: {}".format(len(feature_cols), target_days))
    print("回测区间: {} ~ {}".format(BACKTEST_START, BACKTEST_END))
    if USE_TOP_PCT_BY_PROBA and USE_TOP_PCT_BY_PROBA > 0:
        print("信号筛选: 只做概率最高的 {}% 信号（追求高胜率）".format(USE_TOP_PCT_BY_PROBA))
    else:
        print("信号阈值: 预测概率 >= {}".format(PROBA_THRESHOLD))
    print("规则: 信号日次日开盘买入，持有 {} 日后收盘卖出".format(target_days))
    print("=" * 60)

    symbols = get_daily_symbols()
    if MAX_SYMBOLS_BACKTEST is not None:
        symbols = symbols[:MAX_SYMBOLS_BACKTEST]
    print("回测股票数: {}".format(len(symbols)))

    all_trades = []
    proba_threshold_for_collect = 0.0 if (USE_TOP_PCT_BY_PROBA and USE_TOP_PCT_BY_PROBA > 0) else None
    for i, symbol in enumerate(symbols):
        if (i + 1) % 100 == 0:
            print("  已回测 {}/{} 只股票".format(i + 1, len(symbols)))
        try:
            trades = run_backtest_for_symbol(
                symbol, model, feature_cols, target_days,
                BACKTEST_START, BACKTEST_END,
                proba_threshold=proba_threshold_for_collect,
            )
            all_trades.extend(trades)
        except Exception as e:
            continue

    if USE_TOP_PCT_BY_PROBA and USE_TOP_PCT_BY_PROBA > 0 and len(all_trades) > 0:
        all_trades = sorted(all_trades, key=lambda t: t["proba"], reverse=True)
        n_keep = max(1, int(len(all_trades) * USE_TOP_PCT_BY_PROBA / 100))
        all_trades = all_trades[:n_keep]
        print("已按概率取前 {}% 信号，实际交易数: {}".format(USE_TOP_PCT_BY_PROBA, len(all_trades)))

    if not all_trades:
        print("回测区间内无有效交易，请检查：")
        print("  1）PROBA_THRESHOLD 是否过高（当前 {}）— 建议先改为 0.5 或 0.55 重跑，看「按信号阈值统计」后再调高。".format(PROBA_THRESHOLD))
        print("  2）回测区间 {} ~ {} 是否在本地数据范围内且有足够 K 线。".format(BACKTEST_START, BACKTEST_END))
        return

    # 汇总统计
    rets = np.array([t["ret"] for t in all_trades])
    n = len(rets)
    win_rate = (rets > 0).mean() * 100
    avg_ret = rets.mean() * 100

    # 复利与回撤：将单笔收益裁剪到合理区间，避免 (1+ret)<=0 或溢出导致 inf/-100% 回撤
    ret_min, ret_max = -0.99, 5.0
    rets_clip = np.clip(rets, ret_min, ret_max)
    total_ret_compound = (np.prod(1 + rets_clip) - 1) * 100
    if not np.isfinite(total_ret_compound) or total_ret_compound > 9999:
        total_ret_compound = (np.exp(np.log(1 + rets_clip).sum()) - 1) * 100
    # 笔数过多时复利会极大，仅作展示上限，实盘应以平均单笔与胜率为准
    total_ret_display = min(total_ret_compound, 9999.99) if np.isfinite(total_ret_compound) else 9999.99

    df_trades = pd.DataFrame(all_trades)
    df_trades["date"] = pd.to_datetime(df_trades["date"])
    df_trades = df_trades.sort_values("date").reset_index(drop=True)
    ret_curve = np.clip(df_trades["ret"].values, ret_min, ret_max)
    equity = np.cumprod(1 + ret_curve)
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / (peak + 1e-10)
    max_dd = drawdown.min() * 100

    # 异常收益数量（供排查）
    n_bad = np.sum((rets < ret_min) | (rets > ret_max))
    if n_bad > 0:
        print("说明: 有 {} 笔收益超出 [{:.0%}, {:.0%}]，已裁剪后参与复利与回撤计算。".format(n_bad, ret_min, ret_max))

    print("\n" + "=" * 60)
    print("回测结果")
    print("=" * 60)
    print("交易次数:       {}".format(n))
    print("胜率:           {:.2f}%".format(win_rate))
    print("平均单笔收益:   {:.2f}%".format(avg_ret))
    if total_ret_compound > 9999:
        print("累计收益(复利): >9999%（笔数过多，复利仅作参考，请以平均单笔与胜率为主）")
    else:
        print("累计收益(复利): {:.2f}%".format(float(total_ret_display)))
    print("最大回撤:       {:.2f}%".format(float(max_dd)))
    print("=" * 60)

    # 按概率阈值统计（在「概率前N%」模式下，下表多为已筛选后的子集，区分度有限）
    if USE_TOP_PCT_BY_PROBA and USE_TOP_PCT_BY_PROBA > 0:
        print("\n说明: 当前已按「概率前 {}%」筛选，下表为筛选后交易在不同阈值下的分布。".format(USE_TOP_PCT_BY_PROBA))
        print("若要看全量信号的阈值统计，请将 USE_TOP_PCT_BY_PROBA 设为 0 后重跑。")
    print("\n按信号阈值统计（当前使用阈值 {:.2f}）：".format(PROBA_THRESHOLD))
    print("-" * 60)
    print("{:>8} {:>10} {:>10} {:>12}".format("阈值", "交易数", "胜率%", "平均收益%"))
    print("-" * 60)
    th_list = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
    best_th = None
    best_wr = 0.0
    best_n = 0
    for th in th_list:
        sub = df_trades[df_trades["proba"] >= th]
        if len(sub) == 0:
            print("{:>8.2f} {:>10} {:>10} {:>12}".format(th, 0, "-", "-"))
            continue
        wr = (sub["ret"] > 0).mean() * 100
        ar = sub["ret"].mean() * 100
        print("{:>8.2f} {:>10} {:>10.2f} {:>12.2f}".format(th, len(sub), wr, ar))
        if wr >= WIN_RATE_TARGET and len(sub) >= MIN_TRADES_AT_TARGET:
            if best_th is None or th < best_th:
                best_th = th
                best_wr = wr
                best_n = len(sub)
    print("-" * 60)
    if best_th is not None:
        print("为达到胜率≥{:.0f}%，建议 PROBA_THRESHOLD = {:.2f}（该阈值下交易数 {}，胜率 {:.1f}%）".format(
            WIN_RATE_TARGET, best_th, best_n, best_wr))
    else:
        print("当前回测下未达到胜率≥{:.0f}% 且交易数≥{}。".format(WIN_RATE_TARGET, MIN_TRADES_AT_TARGET))
        if USE_TOP_PCT_BY_PROBA and USE_TOP_PCT_BY_PROBA > 0 and win_rate < 55:
            print("「概率前{}%」胜率仍不足 55%，说明模型高概率与回测区间真实收益未对齐（可能原因：回测与训练区间市场不同、特征泛化不足）。可尝试：1）USE_TOP_PCT_BY_PROBA=2 或 1 更精选；2）TARGET_THRESHOLD=0.20 重新训练；3）扩大训练数据时间范围。".format(USE_TOP_PCT_BY_PROBA))
        else:
            print("建议：1）提高 train_xgboost 中 TARGET_THRESHOLD（如 0.15~0.20）后重新训练；2）或使用上表中胜率最高的阈值。")
    print()

    # 可选：保存回测明细
    out_path = os.path.join(TRAIN_DIR, "backtest_trades.csv")
    df_trades.to_csv(out_path, index=False, encoding="utf-8-sig")
    print("交易明细已保存: {}".format(out_path))


if __name__ == "__main__":
    main()
