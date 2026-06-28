# coding: utf-8
"""
超买风险策略（基于超跌反弹策略的逆向因子）

核心思路：将超跌反弹的买入因子反转，构建超买/卖出风险信号

超跌反弹买入因子 → 超买风险因子：
  1. CTD6 (超跌反弹)    → OB_Price (超买价): 股价远高于动态成本
  2. CTD3 (筹码套牢)    → OB_Chip  (超买筹): 多数筹码盈利丰厚
  3. BCD1<0 (动量向下)  → ME_Momentum (动量衰竭): BCD1从正转负
  4. XL3  (低位拐头)    → HT_Turn  (高位拐头): 短期高点均线见顶回落
  5. Y6<=-10 (深度超跌) → Y6回归/RS超买 (超买回归)
"""
import pandas as pd
import numpy as np
import baostock as bs
from lib.MyTT import (
    REF, EMA, HHV, LLV, MAX, MIN, ABS, MA,
)
from czsc_daily_util import *
from czsc_sqlite import get_local_stock_data
from CZSCStragegy_OversoldRebound import calculate_oversold_indicators, _calc_distribution_metrics


# ========== 风险因子参数 ==========
OB_PRICE_THRESHOLD = 20.0         # 超买价阈值%: (C-CTD1)/CTD1*100 > N
NEAR_HIGH_REF = 1.08             # 距10日高点距离: REF(H,10)/C < N
OB_CHIP_PROFIT_THRESHOLD = 0.15  # 获利阈值: (C-cost20)/C > N
Y3_TIGHT_THRESHOLD = 5.0         # 筹码紧密阈值: Y3 < N (极窄分布)
RS_OVERBOUGHT = 75.0             # RS超买阈值
DIVERGENCE_LOOKBACK = 20         # BCD1顶背离观察周期
VOLUME_SURGE_RATIO = 1.8         # 放量阈值
UPPER_SHADOW_RATIO = 0.5         # 上影线占比阈值

# 风险等级标签
RISK_LEVELS = ["无风险", "轻度", "中度", "高度"]
RISK_SIGNAL_KEYS = [
    "超买价", "超买筹", "动量衰竭", "高位拐头",
    "放量滞涨", "顶背离",
]


def calculate_overbought_indicators(df):
    """
    计算超买风险因子
    在超跌反弹指标基础上，增加超买风险信号列

    返回:
        ndf: 包含原始指标 + 超买风险信号的DataFrame
    """
    ndf = calculate_oversold_indicators(df)
    if ndf is None:
        return None

    O = ndf["open"].values.astype(float)
    H = ndf["high"].values.astype(float)
    L = ndf["low"].values.astype(float)
    C = ndf["close"].values.astype(float)
    V = ndf["volume"].values.astype(float)

    # 读取已有的中间变量
    CTD1 = ndf["CTD1"].values.astype(float)
    Y6 = ndf["Y6"].values.astype(float)
    Y3 = ndf["Y3"].values.astype(float)
    RS = ndf["RS"].values.astype(float)
    BCD1 = ndf["BCD1"].values.astype(float)

    # ========== 1. 超买价信号 (OB_Price) ==========
    # 价格远高于动态成本: (C-CTD1)/CTD1*100 > threshold
    with np.errstate(divide='ignore', invalid='ignore'):
        price_dev = np.where(np.abs(CTD1) > 1e-10, (C - CTD1) / CTD1 * 100, 0)
    ndf["price_dev_ctd1"] = price_dev
    OB_price_raw = price_dev > OB_PRICE_THRESHOLD

    # 距10日高点较近: REF(H,10)/C < NEAR_HIGH_REF
    H_REF10 = REF(H, 10)
    near_high = np.where(C > 1e-10, H_REF10 / C < NEAR_HIGH_REF, False)
    ndf["near_10d_high"] = near_high

    OB_price = OB_price_raw & near_high
    ndf["超买价"] = OB_price

    # ========== 2. 超买筹信号 (OB_Chip) ==========
    # 多数筹码盈利: (C-cost20)/C > OB_CHIP_PROFIT_THRESHOLD (逆CTD3)
    cost20 = ndf["cost20"].values if "cost20" in ndf.columns else None
    if cost20 is None:
        _, _, cost20_arr = _calc_distribution_metrics(C)
        cost20 = cost20_arr
    with np.errstate(divide='ignore', invalid='ignore'):
        chip_profit = np.where((C > 1e-10) & (~np.isnan(cost20)),
                               (C - cost20) / C > OB_CHIP_PROFIT_THRESHOLD, False)
    ndf["chip_profit"] = chip_profit

    # 筹码紧密: Y3 < Y3_TIGHT_THRESHOLD (极窄分布, 风险集中)
    chip_tight = Y3 < Y3_TIGHT_THRESHOLD
    ndf["chip_tight"] = chip_tight

    OB_chip = chip_profit | chip_tight
    ndf["超买筹"] = OB_chip

    # ========== 3. 动量衰竭信号 (ME_Momentum) ==========
    # BCD1死叉: BCD1从正转负
    bcd1_prev = REF(BCD1, 1)
    bcd1_death_cross = (bcd1_prev >= 0) & (BCD1 < 0)
    ndf["BCD1_死叉"] = bcd1_death_cross

    # RS超买
    rs_overbought = RS > RS_OVERBOUGHT
    ndf["RS超买"] = rs_overbought

    # BCD1顶背离: 价格创20日新高但BCD1未创新高
    C_20d_max = HHV(C, DIVERGENCE_LOOKBACK)
    C_new_high = np.abs(C - C_20d_max) < 1e-10

    BCD1_20d_max = HHV(BCD1, DIVERGENCE_LOOKBACK)
    BCD1_not_new_high = BCD1 < REF(BCD1_20d_max, 1)

    divergence = C_new_high & BCD1_not_new_high
    ndf["顶背离"] = divergence

    ME = bcd1_death_cross | rs_overbought
    ndf["动量衰竭"] = ME

    # ========== 4. 高位拐头信号 (HT_Turn) ==========
    # 逆XL3: 短期高点均线在长期阻力下方见顶
    # XH1 = MA(HIGH, 2) * 1.04 (短期阻力)
    # XH2 = MA(HIGH, 26) * 1.15 (长期阻力)
    # 条件: REF(XH1,1) > XH2 AND REF(XH1,1) > XH1 AND REF(XH1,1) > REF(XH1,2)
    XH1 = MA(H, 2) * 1.04
    XH2 = MA(H, 26) * 1.15
    XH1_REF1 = REF(XH1, 1)
    XH1_REF2 = REF(XH1, 2)
    HT = (XH1_REF1 > XH2) & (XH1_REF1 > XH1) & (XH1_REF1 > XH1_REF2)
    ndf["XH1"] = XH1
    ndf["XH2"] = XH2
    ndf["高位拐头"] = HT

    # ========== 5. 放量滞涨信号 (VS_Volume) ==========
    # 价格涨幅微小但成交量放大 + 长上影线
    vol_ma5 = MA(V, 5)
    with np.errstate(divide='ignore', invalid='ignore'):
        vol_ratio = np.where(vol_ma5 > 1e-10, V / vol_ma5, 0)
    vol_surge = vol_ratio > VOLUME_SURGE_RATIO

    # 价格涨幅 < 0.5%
    price_change = np.where(REF(C, 1) > 1e-10, C / REF(C, 1) - 1, 0)
    price_stall = price_change < 0.005

    # 长上影线: (H - MAX(C,O)) / (H-L) > threshold
    upper_shadow = np.where(H - L > 1e-10, (H - np.maximum(C, O)) / (H - L), 0)
    long_upper = upper_shadow > UPPER_SHADOW_RATIO

    VS = vol_surge & price_stall & long_upper
    ndf["vol_ratio"] = vol_ratio
    ndf["price_change"] = price_change
    ndf["upper_shadow"] = upper_shadow
    ndf["放量滞涨"] = VS

    # ========== 6. 综合风险等级 ==========
    # 轻度: 超买价 OR 动量衰竭
    risk_l1 = OB_price | ME

    # 中度: 超买价 AND (超买筹 OR 动量衰竭)
    risk_l2 = OB_price & (OB_chip | ME)

    # 高度: 超买价 AND 超买筹 AND (动量衰竭 OR 高位拐头 OR 顶背离)
    risk_l3 = OB_price & OB_chip & (ME | HT | divergence)

    risk_level = np.zeros(len(ndf), dtype=int)
    risk_level[risk_l3] = 3
    risk_level[risk_l2 & (risk_level == 0)] = 2
    risk_level[risk_l1 & (risk_level == 0)] = 1
    ndf["风险等级"] = risk_level

    # 综合风险信号: 中度和高度
    ndf["卖出风险"] = risk_l2 | risk_l3

    # 各风险因子计数
    risk_count = (OB_price.astype(int) + OB_chip.astype(int) + ME.astype(int)
                  + HT.astype(int) + VS.astype(int) + divergence.astype(int))
    ndf["风险因子数"] = risk_count

    return ndf


def get_overbought_risk_points(symbol, df, min_risk_level=2):
    """
    获取超买风险信号点
    筛选最近N日内出现超买风险信号的股票

    参数:
        symbol: 股票代码
        df: 日线DataFrame
        min_risk_level: 最低风险等级 (1=轻度, 2=中度, 3=高度)

    返回:
        signals: 风险信号列表
    """
    if df is None or len(df) < 120:
        return None

    ndf = calculate_overbought_indicators(df)
    if ndf is None:
        return None

    risk_level_arr = ndf["风险等级"].fillna(0).values

    signals = []
    for idx in range(len(ndf)):
        if risk_level_arr[idx] < min_risk_level:
            continue

        row = ndf.iloc[idx]
        sig = {
            "symbol": symbol,
            "date": row["date"],
            "风险等级": int(risk_level_arr[idx]),
            "风险因子数": int(ndf["风险因子数"].iloc[idx]),
            "price_dev_ctd1": float(ndf["price_dev_ctd1"].iloc[idx]),
            "Y6": float(ndf["Y6"].iloc[idx]),
            "BCD1": float(ndf["BCD1"].iloc[idx]),
            "RS": float(ndf["RS"].iloc[idx]),
            "close": float(row["close"]),
        }

        for k in RISK_SIGNAL_KEYS:
            val = ndf[k].iloc[idx]
            if isinstance(val, (bool, np.bool_)):
                sig[k] = bool(val)
            else:
                sig[k] = val

        signals.append(sig)

    # 只返回最近一次信号
    if signals:
        return signals[-1]
    return None


def print_risk_report(symbol, risk_signal, df):
    """打印单个股票的风险报告"""
    if risk_signal is None:
        return

    level = risk_signal["风险等级"]
    level_label = RISK_LEVELS[level] if level < len(RISK_LEVELS) else "未知"
    risk_count = risk_signal["风险因子数"]

    print(f"\n【{symbol}】{get_symbols_name(symbol)}")
    print(f"  日期: {risk_signal['date']}")
    print(f"  风险等级: {level_label}({level})  触发因子数: {risk_count}")

    active_signals = [k for k in RISK_SIGNAL_KEYS if risk_signal.get(k)]
    if active_signals:
        print(f"  触发因子: {', '.join(active_signals)}")

    print(f"  收盘价: {risk_signal['close']:.2f}")
    print(f"  价格偏离CTD1: {risk_signal['price_dev_ctd1']:.1f}%")
    print(f"  Y6(成本偏离): {risk_signal['Y6']:.1f}")
    print(f"  BCD1(动量): {risk_signal['BCD1']:.1f}")
    print(f"  RS(相对强弱): {risk_signal['RS']:.1f}")


def scan_overbought_stocks(symbols, start_date, end_date, min_risk_level=2):
    """
    扫描全市场超买风险股票

    参数:
        symbols: 股票列表
        start_date: 起始日期
        end_date: 结束日期
        min_risk_level: 最低风险等级
    """
    print(f"\n{'='*70}")
    print(f"  超买风险扫描报告 (风险等级 >= {RISK_LEVELS[min_risk_level]})")
    print(f"{'='*70}")

    risk_stats = {
        "total": 0,
        "level_1": 0,
        "level_2": 0,
        "level_3": 0,
        "by_factor": {k: 0 for k in RISK_SIGNAL_KEYS},
    }

    for i, symbol in enumerate(symbols):
        n = len(symbols)
        if (i + 1) % 100 == 0:
            print(f"[{pd.Timestamp.now().strftime('%H:%M:%S')}] 进度: {i+1}/{n}")

        try:
            df = get_local_stock_data(symbol, start_date)
            if df is None or len(df) < 120:
                continue
        except Exception:
            continue

        sig = get_overbought_risk_points(symbol, df, min_risk_level=min_risk_level)
        if sig is None:
            continue

        risk_stats["total"] += 1
        level = int(sig["风险等级"])
        level_key = f"level_{level}"
        if level_key in risk_stats:
            risk_stats[level_key] += 1

        for k in RISK_SIGNAL_KEYS:
            if sig.get(k):
                risk_stats["by_factor"][k] += 1

        print_risk_report(symbol, sig, df)

    print(f"\n{'='*70}")
    print(f"  扫描统计")
    print(f"{'='*70}")
    print(f"  总股票数: {len(symbols)}")
    print(f"  触发风险: {risk_stats['total']} ({100*risk_stats['total']/len(symbols):.1f}%)")
    print(f"    轻度风险: {risk_stats.get('level_1', 0)}")
    print(f"    中度风险: {risk_stats.get('level_2', 0)}")
    print(f"    高度风险: {risk_stats.get('level_3', 0)}")
    print(f"  因子分布:")
    for k, v in risk_stats["by_factor"].items():
        if v > 0:
            print(f"    {k}: {v}")


if __name__ == "__main__":
    start_date = "2024-01-01"
    bs.login()
    end_date = get_latest_trade_date()
    all_symbols = get_daily_symbols()

    test_data = read_json('./data/突破上涨通道.json')
    test_symbols = [s["symbol"] for s in test_data["stocks"]] if test_data and "stocks" in test_data else None

    if test_symbols:
        for symbol in all_symbols:
            if symbol not in test_symbols:
                continue
            df = get_stock_pd(symbol, start_date, end_date, 'd')
            sig = get_overbought_risk_points(symbol, df, min_risk_level=1)
            print_risk_report(symbol, sig, df)
    else:
        scan_overbought_stocks(all_symbols, start_date, end_date, min_risk_level=2)
    bs.logout()
