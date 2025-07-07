# coding: utf-8
import os
import sys
import joblib
import pandas as pd
import numpy as np
import streamlit as st
from lib.MyTT import *
import matplotlib.pyplot as plt
from czsc_daily_util import *
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import matplotlib
matplotlib.use('TkAgg')  # 设置为交互式后端
import matplotlib.pyplot as plt

def main():
    lg = bs.login()
    # df_v = get_stock_pd('sh.000001','2010-01-01','2025-07-04',"d")
    df = get_stock_pd('sh.601318','2010-01-01','2025-07-04',"d")
    
    # df['CLOSE_V'] = df_v['close']
    # df['CLOSE_volume'] = df_v['volume']
    df['MA5'] = MA(df['close'], 5)
    df['MA10'] = MA(df['close'], 10)
    df['MA20'] = MA(df['close'], 20)
    df['MA60'] = MA(df['close'], 60)
    df['RSI'] = RSI(df['close'], 14)
    df['MACD'],_,_ = MACD(df['close'])
    df['VAR'] = (df['close'] - LLV(df['low'], 10)) / (HHV(df['high'], 10) - LLV(df['low'], 10)) * 100
    df['K0'] = SMA(df['VAR'], 10, 1)
    df['target'] = (df['close'].shift(-1) > df['close']).astype(int)

    # 特征工程之后一定要丢掉NA，不然模型直接闹罢工
    df.dropna(inplace=True)

    features = ['MA5', 'MA10', 'MA20', 'MA60', 'RSI', 'K0', 'MACD', 'volume']
    X = df[features]
    y = df['target']
    # 90%数据训练
    X_train, X_test, y_train, y_test = train_test_split(X, y, shuffle=False, test_size=0.9)

    # 用100棵决策树,每棵树最多问3个问题,学习速度
    model = XGBClassifier(n_estimators=100, max_depth=3, learning_rate=0.1)
    model.fit(X_train, y_train)

    # 预测后10%的数据
    y_pred = model.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"准确率：{acc:.2f}")

    # 可视化特征重要性
    plt.figure(figsize=(10,4))
    plt.barh(X.columns, model.feature_importances_)
    plt.title('哪些指标最重要？')
    plt.show()

    bs.logout()

if __name__ == '__main__':
    main()
