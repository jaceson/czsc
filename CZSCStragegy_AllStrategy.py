# coding: utf-8
import os
import sys
from czsc_daily_util import *
from lib.MyTT import *
import pandas as pd

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