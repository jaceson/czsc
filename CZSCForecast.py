# coding: utf-8
import os
import sys
import pandas as pd
import numpy as np
from czsc_daily_util import *
import matplotlib.pyplot as plt
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.graphics.tsaplots import plot_acf,plot_pacf

def main():
    lg = bs.login()
    df = get_stcok_pd('sh.000001','2010-01-01','2025-02-26',"d")
    close = np.diff(np.log(df['close']))

    # 绘制自相关图
    plot_acf(close)
    plt.show()

    # 绘制偏自相关图
    plot_pacf(close)
    plt.show()

    # 使用arima函数来拟合模型
    # p,d,q分别代表ar、差分和MA模型的阶数
    # model = ARIMA(df['close'], order=(p,d,q))
    model = ARIMA(close, order=(5,1,0))
    model_fit = model.fit()

    forecast = model_fit.forecast(steps=5)
    print(forecast)

    plt.plot(close,label='实际价格')
    plt.plot(np.arange(len(close),len(close)+5), forecast, label='预测走势')
    plt.legend()
    plt.xlabel('日期')
    plt.ylabel('收盘价')
    plt.show()

    bs.logout()

if __name__ == '__main__':
    main()
