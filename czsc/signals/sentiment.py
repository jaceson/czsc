# -*- coding: utf-8 -*-
"""
author: zengbin93
email: zeng_bin8888@163.com
create_dt: 2023/06/15
describe: A股情绪类指标信号函数
"""
from loguru import logger

try:
    import talib as ta
except:
    logger.warning("ta-lib 没有正确安装，相关信号函数无法正常执行。"
                   "请参考安装教程 https://blog.csdn.net/qaz2134560/article/details/98484091")
import numpy as np
from collections import OrderedDict
from czsc.analyze import CZSC
from czsc.utils.sig import get_sub_elements, create_single_signal


def psy_up_dw_line_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """PSY心理线，衡量投资者对市场的心理预期

    参数模板："{freq}_D{di}N{n}M{m}_PSY心理线V240625"

    **信号逻辑：**

    PSY = N天中收盘价上涨的天数 / N * 100
    当 PSY > M（通常为75），市场情绪过热，看空；
    当 PSY < (100-M)（通常为25），市场情绪低迷，看多。

    **信号列表：**

    - Signal('日线_D1N12M75_PSY心理线V240625_看多_任意_任意_0')
    - Signal('日线_D1N12M75_PSY心理线V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: PSY计算周期，默认为12
        - :param m: 情绪阈值（0-100），默认为75，当PSY>m看空，PSY<100-m看多
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 12))
    m = int(kwargs.get("m", 75))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}M{m}_PSY心理线V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    up_count = sum(1 for i in range(1, len(bars)) if bars[i].close > bars[i - 1].close)
    psy = up_count / n * 100

    if psy > m:
        v1 = "看空"
    elif psy < 100 - m:
        v1 = "看多"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def psy_ma_cross_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """PSY均线交叉，心理线与其均线的交叉信号

    参数模板："{freq}_D{di}N{n}M{m}_PSY均线V240625"

    **信号逻辑：**

    计算PSY的M日均线，当PSY上穿其均线时看多，下穿时看空。

    **信号列表：**

    - Signal('日线_D1N12M6_PSY均线V240625_看多_任意_任意_0')
    - Signal('日线_D1N12M6_PSY均线V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: PSY计算周期，默认为12
        - :param m: PSY均线周期，默认为6
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 12))
    m = int(kwargs.get("m", 6))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}M{m}_PSY均线V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + m + 20:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n + m + 5)
    psy_list = []
    for i in range(len(bars)):
        if i < n:
            continue
        up_count = sum(1 for j in range(i - n + 1, i + 1) if bars[j].close > bars[j - 1].close)
        psy_list.append(up_count / n * 100)

    if len(psy_list) < m + 2:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    psy_arr = np.array(psy_list, dtype=float)
    psy_ma = np.mean(psy_arr[-m - 1:-1])
    if psy_arr[-1] > psy_ma and psy_arr[-2] <= psy_ma:
        v1 = "看多"
    elif psy_arr[-1] < psy_ma and psy_arr[-2] >= psy_ma:
        v1 = "看空"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def vr_up_dw_line_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """VR成交量变异率，通过成交量分析市场情绪

    参数模板："{freq}_D{di}N{n}TH{th}_VR情绪V240625"

    **信号逻辑：**

    VR = (上涨日成交量之和 + 成交量之和/2) / (下跌日成交量之和 + 成交量之和/2) * 100
    VR > TH（默认200），市场过热，看空；
    VR < (100 - TH/2)（默认60），市场低迷，看多。

    **信号列表：**

    - Signal('日线_D1N26TH200_VR情绪V240625_看多_任意_任意_0')
    - Signal('日线_D1N26TH200_VR情绪V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: VR计算周期，默认为26
        - :param th: VR阈值，默认为200
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 26))
    th = int(kwargs.get("th", 200))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}TH{th}_VR情绪V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    vol_total = sum(bar.vol for bar in bars)
    vol_up = sum(bar.vol for bar in bars if bar.close > bar.open)
    vol_down = sum(bar.vol for bar in bars if bar.close < bar.open)

    if vol_down == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    vr = (vol_up + vol_total / 2) / (vol_down + vol_total / 2) * 100
    if vr > th:
        v1 = "看空"
    elif vr < 100 - th / 2:
        v1 = "看多"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def vr_ma_cross_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """VR均线交叉，成交量变异率与其均线的交叉信号

    参数模板："{freq}_D{di}N{n}M{m}_VR均线V240625"

    **信号逻辑：**

    计算VR的M日均线，当VR上穿其均线时看多，下穿时看空。

    **信号列表：**

    - Signal('日线_D1N26M6_VR均线V240625_看多_任意_任意_0')
    - Signal('日线_D1N26M6_VR均线V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: VR计算周期，默认为26
        - :param m: VR均线周期，默认为6
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 26))
    m = int(kwargs.get("m", 6))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}M{m}_VR均线V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + m + 20:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n + m + 5)
    vr_list = []
    for i in range(len(bars)):
        if i < n:
            continue
        sub = bars[i - n + 1:i + 1]
        vol_total = sum(b.vol for b in sub)
        vol_up = sum(b.vol for b in sub if b.close > b.open)
        vol_down = sum(b.vol for b in sub if b.close < b.open)
        if vol_down == 0:
            vr_list.append(200)
        else:
            vr_list.append((vol_up + vol_total / 2) / (vol_down + vol_total / 2) * 100)

    if len(vr_list) < m + 2:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    vr_arr = np.array(vr_list, dtype=float)
    vr_ma = np.mean(vr_arr[-m - 1:-1])
    if vr_arr[-1] > vr_ma and vr_arr[-2] <= vr_ma:
        v1 = "看多"
    elif vr_arr[-1] < vr_ma and vr_arr[-2] >= vr_ma:
        v1 = "看空"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def brar_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """BRAR情绪指标（ARBR），通过价格波动反映市场情绪

    参数模板："{freq}_D{di}N{n}_BRAR情绪V240625"

    **信号逻辑：**

    AR = (N天中最高价-开盘价)之和 / (N天中开盘价-最低价)之和 * 100
    BR = (N天中最高价-前收盘价)正向之和 / (N天中前收盘价-最低价)正向之和 * 100

    AR > 150，市场情绪过热，看空；
    AR < 70，市场情绪低迷，看多。
    BR > 300，市场情绪过热，看空；
    BR < 50，市场情绪低迷，看多。

    **信号列表：**

    - Signal('日线_D1N26_BRAR情绪V240625_看多_任意_任意_0')
    - Signal('日线_D1N26_BRAR情绪V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: BRAR计算周期，默认为26
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 26))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}_BRAR情绪V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    sum_h_o = sum(bar.high - bar.open for bar in bars)
    sum_o_l = sum(bar.open - bar.low for bar in bars)
    if sum_o_l == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    ar = sum_h_o / sum_o_l * 100

    sum_h_pre_c = sum(max(0, bar.high - bars[i - 1].close) for i, bar in enumerate(bars) if i > 0)
    sum_pre_c_l = sum(max(0, bars[i - 1].close - bar.low) for i, bar in enumerate(bars) if i > 0)
    if sum_pre_c_l == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    br = sum_h_pre_c / sum_pre_c_l * 100

    if ar > 150 or br > 300:
        v1 = "看空"
    elif ar < 70 or br < 50:
        v1 = "看多"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def brar_ar_br_cross_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """AR与BR交叉信号

    参数模板："{freq}_D{di}N{n}_ARBR交叉V240625"

    **信号逻辑：**

    AR上穿BR时看多，AR下穿BR时看空。

    **信号列表：**

    - Signal('日线_D1N26_ARBR交叉V240625_看多_任意_任意_0')
    - Signal('日线_D1N26_ARBR交叉V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: BRAR计算周期，默认为26
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 26))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}_ARBR交叉V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    sum_h_o = sum(bar.high - bar.open for bar in bars)
    sum_o_l = sum(bar.open - bar.low for bar in bars)
    if sum_o_l == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
    ar = sum_h_o / sum_o_l * 100

    sum_h_pre_c = sum(max(0, bar.high - bars[i - 1].close) for i, bar in enumerate(bars) if i > 0)
    sum_pre_c_l = sum(max(0, bars[i - 1].close - bar.low) for i, bar in enumerate(bars) if i > 0)
    if sum_pre_c_l == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
    br = sum_h_pre_c / sum_pre_c_l * 100

    if ar > br:
        v1 = "看多"
    elif ar < br:
        v1 = "看空"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def cr_up_dw_line_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """CR能量指标，通过中间价分析市场情绪

    参数模板："{freq}_D{di}N{n}TH{th}_CR能量V240625"

    **信号逻辑：**

    CR = (N天中最高价-前一日中间价)正向之和 / (N天中前一日中间价-最低价)正向之和 * 100
    其中中间价 = (最高价+最低价+收盘价)/3
    CR > TH（默认150），市场过热，看空；
    CR < (100 - TH/2)（默认25），市场低迷，看多。

    **信号列表：**

    - Signal('日线_D1N26TH150_CR能量V240625_看多_任意_任意_0')
    - Signal('日线_D1N26TH150_CR能量V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: CR计算周期，默认为26
        - :param th: CR阈值，默认为150
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 26))
    th = int(kwargs.get("th", 150))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}TH{th}_CR能量V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)

    mid_prev = [(bar.high + bar.low + bar.close) / 3 for bar in bars]
    sum_h_mid = sum(max(0, bar.high - mid_prev[i - 1]) for i, bar in enumerate(bars) if i > 0)
    sum_mid_l = sum(max(0, mid_prev[i - 1] - bar.low) for i, bar in enumerate(bars) if i > 0)

    if sum_mid_l == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    cr = sum_h_mid / sum_mid_l * 100

    if cr > th:
        v1 = "看空"
    elif cr < 100 - th / 2:
        v1 = "看多"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)


def mfi_up_dw_line_V240625(c: CZSC, **kwargs) -> OrderedDict:
    """MFI资金流向指标，利用成交量和价格判断买卖力量

    参数模板："{freq}_D{di}N{n}TH{th}_MFI情绪V240625"

    **信号逻辑：**

    MFI > TH（默认80），超买，看空；
    MFI < 100-TH（默认20），超卖，看多。

    **信号列表：**

    - Signal('日线_D1N14TH80_MFI情绪V240625_看多_任意_任意_0')
    - Signal('日线_D1N14TH80_MFI情绪V240625_看空_任意_任意_0')

    :param c: CZSC对象
    :param kwargs: 参数字典
        - :param di: 信号计算截止倒数第i根K线
        - :param n: MFI计算周期，默认为14
        - :param th: MFI阈值（0-100），默认为80，当MFI>th看空，MFI<100-th看多
    :return: 信号识别结果
    """
    di = int(kwargs.get("di", 1))
    n = int(kwargs.get("n", 14))
    th = int(kwargs.get("th", 80))
    freq = c.freq.value
    k1, k2, k3 = f"{freq}_D{di}N{n}TH{th}_MFI情绪V240625".split('_')
    v1 = "其他"
    if len(c.bars_raw) < di + n + 10:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    bars = get_sub_elements(c.bars_raw, di=di, n=n)
    typical_prices = [(bar.high + bar.low + bar.close) / 3 for bar in bars]

    pos_mf = 0
    neg_mf = 0
    for i in range(1, len(bars)):
        rmf = typical_prices[i] * bars[i].vol
        if typical_prices[i] > typical_prices[i - 1]:
            pos_mf += rmf
        elif typical_prices[i] < typical_prices[i - 1]:
            neg_mf += rmf

    if neg_mf == 0:
        return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)

    mfr = pos_mf / neg_mf
    mfi = 100 - (100 / (1 + mfr))

    if mfi > th:
        v1 = "看空"
    elif mfi < 100 - th:
        v1 = "看多"
    return create_single_signal(k1=k1, k2=k2, k3=k3, v1=v1)
