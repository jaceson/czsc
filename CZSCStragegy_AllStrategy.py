# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd

'''
    长线转折指标逻辑
'''
def get_longterm_turn_condition(symbol,df):
    ndf = get_rps_data(df)

    YIHAOC3 = (ndf['RPS50']>=87)
    YIHAOC6 = (ndf['RPS120']>=90)
    YIHAOC7 = ((ndf['RPS50']>=90) | (ndf['RPS120']>=90))
    YIHAOC8 = (ndf['close']>=HHV(ndf['close'],70))
    YIHAOC9 = (YIHAOC7 & YIHAOC8)
    YIHAOC10 = (YIHAOC3 | YIHAOC6)
    YIHAOC11 = ((LLV(ndf['low'],50)>LLV(ndf['low'],200)) & YIHAOC9)
    YIHAOC12 = ((LLV(ndf['low'],30)>LLV(ndf['low'],120)) & YIHAOC9)
    YIHAOC13 = (LLV(ndf['low'],20)>LLV(ndf['low'],50))
    YIHAOC14 = (YIHAOC11 | YIHAOC12 | YIHAOC13)
    YIHAOC16 = (COUNT(IF(ndf['high']<HHV(ndf['high'],80),0,1),10))
    YIHAOC17 = (((ndf['close']>=HHV(ndf['close'],50)) | (ndf['high']>=HHV(ndf['high'],50))) & YIHAOC7)
    YIHAOC18 = (YIHAOC16 | YIHAOC17)
    YIHAOC19 = ((ndf['close']>MA(ndf['close'],20)) & (ndf['close']>MA(ndf['close'],200)) & (MA(ndf['close'],120)/MA(ndf['close'],200)>0.9))
    YIHAOC21 = (COUNT(IF(ndf['close']>MA(ndf['close'],200),1,0),45))
    YIHAOC23 = (COUNT(IF(ndf['close']>MA(ndf['close'],250),1,0),45))
    YIHAOC24 = ((YIHAOC21>=2) & (YIHAOC21<45))
    YIHAOC26 = (COUNT(IF(ndf['low']<MA(ndf['close'],200),1,0),45))
    YIHAOC27 = ((YIHAOC26>0) & (YIHAOC21>2))
    YIHAOC29 = (COUNT(IF(ndf['low']<MA(ndf['close'],250),1,0),45))
    YIHAOC30 = ((YIHAOC29>0) & (YIHAOC23>2))
    YIHAOC31 = (YIHAOC24 | YIHAOC27 | YIHAOC30)
    YIHAOC32 = ((MA(ndf['close'],120)>=REF(MA(ndf['close'],120),10)) | (MA(ndf['close'],200)>=REF(MA(ndf['close'],200),10)))
    YIHAOC33 = ((MA(ndf['close'],120)>=REF(MA(ndf['close'],120),15)) | (MA(ndf['close'],200)>=REF(MA(ndf['close'],200),15)))
    YIHAOC34 = (YIHAOC32 | YIHAOC33)
    YIHAOC35 = ((MA(ndf['close'],120)>=REF(MA(ndf['close'],120),10)) | (MA(ndf['close'],200)>=REF(MA(ndf['close'],200),10)))
    YIHAOC36 = ((MA(ndf['close'],120)>=REF(MA(ndf['close'],120),15)) & (MA(ndf['close'],200)>=REF(MA(ndf['close'],200),15)))
    YIHAOC37 = (YIHAOC35 | YIHAOC36)
    YIHAOC38 = ((MA(ndf['close'],120)>MA(ndf['close'],200)) & YIHAOC34)
    YIHAOC39 = ((HHV(ndf['high'],30)/LLV(ndf['low'],120)<1.50) & YIHAOC34)
    YIHAOC40 = ((HHV(ndf['high'],30)/LLV(ndf['low'],120)<1.55) & YIHAOC37)
    YIHAOC41 = ((HHV(ndf['high'],30)/LLV(ndf['low'],120)<1.65) & YIHAOC38 & YIHAOC9)
    YIHAOC42 = (YIHAOC39 | YIHAOC40 | YIHAOC41)
    YIHAOC43 = (HHV(ndf['high'],5)/HHV(ndf['high'],120)>0.85)
    YIHAOC44 = ((HHV(ndf['high'],5)/HHV(ndf['high'],120)>0.8) & YIHAOC9)
    YIHAOC45 = (ndf['close']/HHV(ndf['high'],10)>0.9)
    YIHAOC46 = ((YIHAOC43 | YIHAOC44) & YIHAOC45)

    return (YIHAOC10 & YIHAOC14 & YIHAOC18 & YIHAOC19 & YIHAOC31 & YIHAOC42 & YIHAOC46)

'''
    主力进场指标
'''
def get_main_strong_join_condition(symbol,df):
    ndf = get_rps_data(df)

    YHCSXPXGTJ1 = (MA(ndf['close'], 5))
    YHCSXPXGTJ2 = (MA(ndf['close'], 10))
    YHCSXPXGTJ3 = (MA(ndf['close'], 20))
    YHCSXPXGTJ4 = (MA(ndf['close'], 60))

    YHCSXPXGTJ5 = (SLOPE(YHCSXPXGTJ1, 5))
    YHCSXPXGTJ6 = (SLOPE(YHCSXPXGTJ2, 5))
    YHCSXPXGTJ7 = (SLOPE(YHCSXPXGTJ3, 5))
    YHCSXPXGTJ8 = (SLOPE(YHCSXPXGTJ4, 5))
    YHCSXPXGTJ9 = ((YHCSXPXGTJ5 > 0) & (YHCSXPXGTJ6 > 0) & (YHCSXPXGTJ7 > 0) & (YHCSXPXGTJ8 > 0))

    YHCSXPXGTJ10 = (EMA(ndf['close'], 12) - EMA(ndf['close'], 26))
    YHCSXPXGTJ11 = (EMA(YHCSXPXGTJ10, 9))
    YHCSXPXGTJ12 = ((YHCSXPXGTJ10 - YHCSXPXGTJ11) * 2)
    YHCSXPXGTJ13 = ((YHCSXPXGTJ10 > YHCSXPXGTJ11) & (YHCSXPXGTJ12 > REF(YHCSXPXGTJ12, 1)))

    YHCSXPXGTJ14 = ((ndf['close'] - REF(ndf['close'], 1)) / REF(ndf['close'], 1) * 100 > 8)
    YHCSXPXGTJ15 = ((ndf['open'] - REF(ndf['close'], 1)) / REF(ndf['close'], 1) * 100 < 3)

    YHCSXPXGTJ16 = (ndf['close'] > ndf['open'])
    YHCSXPXGTJ17 = (REF(ndf['close'], 1) / REF(ndf['close'], 2) <= 1.05)

    YHCSXPXGTJ18 = (REF(ndf['close'], 1))
    YHCSXPXGTJ19 = (SMA(MAX(ndf['close'] - YHCSXPXGTJ18, 0), 14, 1) / SMA(ABS(ndf['close'] - YHCSXPXGTJ18), 14, 1) * 90)

    YHCSXPXGTJ20 = (YHCSXPXGTJ19 < 80)
    YHCSXPXGTJ21 = (ndf['volume'] > MA(ndf['volume'], 5))

    return (YHCSXPXGTJ9 & YHCSXPXGTJ13 & YHCSXPXGTJ14 & YHCSXPXGTJ15  & YHCSXPXGTJ16  & YHCSXPXGTJ17  & YHCSXPXGTJ20  & YHCSXPXGTJ21)

'''
    波段之王指标
'''
def get_swing_king_condition(symbol,df):
    ndf = get_rps_data(df)

    YIHA01 = ((ndf['close']-LLV(ndf['low'],25))/(HHV(ndf['high'],25)-LLV(ndf['low'],25))*100)
    YIHA02 = (SMA(YIHA01,3,1))
    YIHA03 = (SMA(YIHA02,3,1))
    YIHA04 = (3*YIHA02-2*YIHA03)
    YIHA05 = ((2*ndf['close']+ndf['high']+ndf['low'])/4)

    YIHA06 = (EMA(EMA(EMA(YIHA05,4),4),4))
    YIHA07 = ((YIHA06-REF(YIHA06,1))/REF(YIHA06,1)*100)
    YIHA08 = (MA(YIHA07,3)+0.03)
    YIHA09 = (MA(YIHA07,1))
    YIHA2 = ((ndf['close']-LLV(ndf['low'],9))/(HHV(ndf['high'],9)-LLV(ndf['low'],9))*100)

    YIHA3 = (SMA(YIHA2,3,1))
    YIHA4 = (SMA(YIHA3,3,1))
    YIHA5 = (3*YIHA3-2*YIHA4)

    YIHA6 = (100*((EMA((ndf['high']+ndf['low'])/2,3)-LLV(EMA((ndf['high']+ndf['low'])/2,5),30)-(EMA(ndf['high'],20)-EMA(ndf['low'],20)))/(LLV(EMA((ndf['high']+ndf['low'])/2,5),30)-(EMA(ndf['high'],20)-EMA(ndf['low'],20)))))
    YIHA1 = (EMA(SLOPE(ndf['close'],3)*20+ndf['close'],34))
    YIHA7 = (IF((EMA(ndf['close'],2)>YIHA1) & (YIHA6>0),EMA(ndf['close'],3),LLV(EMA((ndf['high']+ndf['low'])/2,5),30)))
    YIHA8 = (IF((EMA(ndf['close'],2)>YIHA1) & (YIHA6>0),LLV(EMA((ndf['high']+ndf['low'])/2,5),30),EMA(ndf['close'],5)))

    YIHA9 = (SMA(ndf['close'],6,1))
    YIHA10 = (SMA(ndf['close'],13,1))
    YIHA11 = (SMA(ndf['close'],3,1))
    YIHA12 = (SMA(ndf['close'],8,1))
    YIHA13 = (SMA(ndf['close'],3,1))

    YIHA14 = ((MA(ndf['close'],3)+MA(ndf['close'],6)+MA(ndf['close'],12)+MA(ndf['close'],25))/4)
    YIHA15 = (YIHA14+3*STD(YIHA14,13))
    YIHA16 = (YIHA14-3*STD(YIHA14,13))

    YIHA17 = (MA(ndf['close'],55))
    YIHA18 = (REF(ndf['close'],1))
    YIHA19 = (SMA(MAX(ndf['close']-YIHA18,0),6,1)/SMA(ABS(ndf['close']-YIHA18),6,1)*100)


    YIHA20 = ((2*ndf['close']+ndf['high']+ndf['low'])/4)
    YIHA21 = (MA(YIHA20,5))
    YIHA22 = (YIHA21*1.02)
    YIHA23 = (YIHA21*0.98)

    YIHA24 = (LLV(YIHA20,21))
    YIHA25 = (HHV(YIHA20,30))
    YIHA26 = (YIHA21>=REF(YIHA21,1))

    YIHA27 = (MAX(MAX(YIHA9,YIHA12),YIHA10))
    YIHA28 = (MIN(MIN(YIHA9,YIHA12),YIHA10))

# DRAWTEXT(CROSS(YIHA12,YIHA11),H*1.08,'压力'),COLORGREEN;

# DRAWTEXT(CROSS(82,YIHA19) AND CLOSE<YIHA11, HIGH*1.04,'高位'),COLORLICYAN;

# DRAWTEXT(CROSS(YIHA11,YIHA21) AND YIHA11<YIHA10 AND YIHA11<YIHA12 AND YIHA11<YIHA9 AND CLOSE>YIHA24, LOW*0.98,'见底'),COLORYELLOW;

# DRAWTEXT(CROSS(YIHA11,YIHA9) AND YIHA11>YIHA21, LOW*0.92,'买进'),COLORYELLOW;

# DRAWTEXT(CROSS(YIHA11,YIHA12)  AND YIHA11>YIHA21, LOW*0.98,'加仓'),  COLORYELLOW;

    # 见底
    buy_con_1 = (CROSS(YIHA11,YIHA21) & (YIHA11<YIHA10) & (YIHA11<YIHA12) & (YIHA11<YIHA9) & (ndf['close']>YIHA24))
    # 买进
    buy_con_2 = (CROSS(YIHA11,YIHA9) & (YIHA11>YIHA21))
    # 加仓
    buy_con_3 = (CROSS(YIHA11,YIHA12) & (YIHA11>YIHA21))

    return buy_con_1,buy_con_2,buy_con_3
'''
    月线反转指标逻辑
'''
def get_month_turn_condition(symbol,df):
    ndf = get_rps_data(df)
    return (
        (ndf['RPS50']>85) &
        (ndf['close']>MA(ndf['close'],250)) &
        (COUNT(IF(ndf['high']>=HHV(ndf['high'],50),1,0), 30)>0) &
        (COUNT(IF(ndf['close']>MA(ndf['close'],250),1,0), 30)>2) &
        (COUNT(IF(ndf['close']>MA(ndf['close'],250),1,0), 30)<30) &
        (ndf['high']/HHV(ndf['high'],120)>0.9)
    )

'''
    小黄人三线红
'''
def get_third_redline_conditin(symbol,df):
    ndf = get_rps_data(df)
    return (
        (ndf['RPS50'] > 90) &
        (ndf['RPS120'] > 90) &
        (ndf['RPS250'] > 90)
    )

'''
    口袋支点指标
''' 
def get_pocket_pivot_condition(symbol,df):
    ndf = get_rps_data(df)

    YIHAOCA36 = 20
    YIHAOCA37 = (MA(ndf['close'],YIHAOCA36))
    YIHAOCA38 = (STD(ndf['close'],YIHAOCA36))
    YIHAOCA39 = (YIHAOCA37+2*YIHAOCA38)
    YIHAOCA40 = (YIHAOCA37-2*YIHAOCA38)
    YIHAOCA41 = (LLV(ndf['low'],250))
    YIHAOCA42 = (HHV(ndf['high'],250))
    YIHAOCA43 = ((ndf['close']-YIHAOCA41)/YIHAOCA41*100)
    YIHAOCA44 = ((YIHAOCA42-ndf['close'])/(YIHAOCA42-YIHAOCA41)*100)
    YIHAOCA45 = (YIHAOCA43>85)
    YIHAOCA46 = (YIHAOCA44<=60)

    # 假设 cross_today 是布尔 Series，索引为连续整数 0..n-1
    cond1 = (YIHAOCA45 & YIHAOCA46).astype(int)
    cross_today = (cond1.diff() == 1) & (cond1 == 1)   # 当前发生金叉

    cond = cross_today.values          # 转成 bool ndarray
    idx  = np.arange(len(cond))

    # 计算 BARSLAST（每行往前找最近一次 True 的间隔）
    bars = np.empty(len(cond))
    bars[:] = -1
    true_pos = np.where(cond)[0]
    for i in range(len(cond)):
        if len(true_pos[true_pos <= i]):
            bars[i] = i - true_pos[true_pos <= i][-1]

    # 构造 ref_cross：把 bars 作为 shift 步数，逐行取值
    # 当 bars[i] = k 时，取 cond[i-k]，若 k 越界则置 False
    ref_cross = np.full(len(cond), False, dtype=bool)
    mask = bars >= 0
    ref_cross[mask] = cond[idx[mask] - bars[mask].astype(int)]

    # 转成 Series 方便后续使用
    ref_cross = pd.Series(ref_cross, index=cross_today.index)

    # 最终信号
    YIHAOCA47 = (bars < 60) & ref_cross
    YIHAOCA48 = (MA(ndf['close'],10))
    YIHAOCA49 = (MA(ndf['close'],30))
    YIHAOCA50 = (MA(ndf['close'],60))
    YIHAOCA51 = (MA(ndf['close'],120))
    YIHAOCA52 = (SLOPE(YIHAOCA48,5))
    YIHAOCA53 = (SLOPE(YIHAOCA49,5))
    YIHAOCA54 = (SLOPE(YIHAOCA50,5))
    YIHAOCA55 = (SLOPE(YIHAOCA51,5))
    YIHAOCA56 = ((YIHAOCA52>0) & (YIHAOCA53>0) & (YIHAOCA54>0) & (YIHAOCA55>0))

    return (YIHAOCA45 & YIHAOCA46 & YIHAOCA47 & YIHAOCA56)

'''
    KD指标抄底逻辑
'''
def get_kd_condition(symbol,df,MIN_K=20,MIN_KD=-0.5,MIN_KR=-0.03):
    ndf = get_kd_data(df)
    return (
        (df['K0'] < MIN_K) & (df['K0'] < REF(df['K0'],1)) &
        (((df['K0']-REF(df['K0'],1))>=MIN_KD) | ((df['K0']-REF(df['K0'],1))/REF(df['K0'],1) >= MIN_KR)) & 
        (REF(df['K0'],1)<REF(df['K0'],2)) & 
        (REF(df['K0'],2)<REF(df['K0'],3)) & 
        (REF(df['K0'],3)<REF(df['K0'],4)) & 
        (REF(df['K0'],4)<REF(df['K0'],5)) & 
        (REF(df['K0'],5)<REF(df['K0'],6)) & 
        (REF(df['K0'],6)<REF(df['K0'],7)) & 
        (REF(df['K0'],7)<REF(df['K0'],8)) &
        (df['low'] <= REF(df['low'], 1)) &
        (df['high'] <= REF(df['high'], 1)) &
        (REF(df['low'], 1) <= REF(df['low'], 2)) &
        (REF(df['high'], 1) <= REF(df['high'], 2)) 
    )