# coding: utf-8
import os
import sys
import json
import getopt
sys.path.insert(0, '.')
sys.path.insert(0, '..')
sys.path.insert(0, '../..')
import zipfile
import baostock as bs
from tqdm import tqdm
import pandas as pd
from czsc.analyze import CZSC, RawBar, NewBar, remove_include, FX, check_fx, Direction, kline_pro
from czsc.enum import Freq
from collections import OrderedDict

def usage():
    print ("-s: 股票代码")
    pass

opts,args = getopt.getopt(sys.argv[1:], "hs:")
stock_symbol = ""
for op, value in opts:
    if op == "-s":
        stock_symbol = value
    elif op == "-h":    
        usage()
        sys.exit()

cur_path = os.path.split(os.path.realpath(__file__))[0]


def read_1min():
    with zipfile.ZipFile(os.path.join(cur_path, 'data/000001.XSHG_1min.zip'), 'r') as z:
        f = z.open('000001.XSHG_1min.csv')
        data = pd.read_csv(f, encoding='utf-8')

    data['dt'] = pd.to_datetime(data['dt'])
    data['amount'] = data['close'] * data['vol']
    records = data.to_dict('records')

    bars = []
    for row in tqdm(records, desc='read_1min'):
        bar = RawBar(**row)
        bar.freq = Freq.F1
        bars.append(bar)
    return bars


def read_daily():
    file_kline = os.path.join(cur_path, "data/000001.SH_D.csv")
    kline = pd.read_csv(file_kline, encoding="utf-8")
    kline['amount'] = kline['close'] * kline['vol']
    kline.loc[:, "dt"] = pd.to_datetime(kline.dt)
    bars = [RawBar(symbol=row['symbol'], id=i, freq=Freq.D, open=row['open'], dt=row['dt'],
                   close=row['close'], high=row['high'], low=row['low'], vol=row['vol'], amount=row['amount'])
            for i, row in kline.iterrows()]
    return bars

# baostock查询结果转换成数组
def querydata_to_list(rs):
    data_list = []
    while (rs.error_code == '0') & rs.next():
        data_list.append(rs.get_row_data())
    result = pd.DataFrame(data_list, columns=rs.fields)
    return result

def read_online(symbol):
    rs = bs.query_history_k_data_plus(
            code=symbol,
            fields="date,open,high,low,close,volume,amount,turn",
            start_date="2024-05-01",
            end_date="2025-02-07",
            frequency="d",
            adjustflag="2",
        )
    # print('query_history_k_data_plus respond error_code:' + rs.error_code)
    # print('query_history_k_data_plus respond  error_msg:' + rs.error_msg)
    result = querydata_to_list(rs)
    df = pd.DataFrame(result)
    try:
        df['low'] = df['low'].astype(float)
        df['high'] = df['high'].astype(float)
        df['open'] = df['open'].astype(float)
        df['close'] = df['close'].astype(float)
        df['close'] = df['close'].astype(float)
        df['close'] = df['close'].astype(float)
        # df['volume'] = df['volume'].replace('', np.nan)
        # df['volume'] = df['volume'].fillna(0)
        df['volume'] = df['volume'].astype(float)
        # df['amount'] = df['amount'].replace('', np.nan)
        # df['amount'] = df['amount'].fillna(0)
        df['amount'] = df['amount'].astype(float)
        # df.set_index('date', inplace=True)
        # dt['dt'] = pd.to_datetime(df['date'])
        df.loc[:, "dt"] = pd.to_datetime(df['date'])
        bars = [RawBar(symbol=symbol, id=i, freq=Freq.D, open=row['open'], dt=row['dt'],
                    close=row['close'], high=row['high'], low=row['low'], vol=row['volume'], amount=row['amount'])
                for i, row in df.iterrows()]
        return bars
    except Exception as e:
        # print(symbol)
        # print(result)
        return []

def test_find_bi():
    bars = read_daily()
    # 去除包含关系
    bars1 = []
    for bar in bars:
        if len(bars1) < 2:
            bars1.append(NewBar(symbol=bar.symbol, id=bar.id, freq=bar.freq,
                                dt=bar.dt, open=bar.open,
                                close=bar.close, high=bar.high, low=bar.low,
                                vol=bar.vol, amount=bar.amount, elements=[bar]))
        else:
            k1, k2 = bars1[-2:]
            has_include, k3 = remove_include(k1, k2, bar)
            if has_include:
                bars1[-1] = k3
            else:
                bars1.append(k3)

    fxs = []
    for i in range(1, len(bars1) - 1):
        fx = check_fx(bars1[i - 1], bars1[i], bars1[i + 1])
        if isinstance(fx, FX):
            fxs.append(fx)


def test_czsc_update(code):
    # bars = read_daily()
    bars = read_online(code)
    if len(bars) <= 0:
        return
    # 不计算任何信号
    # c = CZSC(bars)
    # print(c.signals)
    # assert not c.signals

    # 测试 ubi 属性
    # ubi = c.ubi
    # assert ubi['direction'] == Direction.Down
    # assert ubi['high_bar'].dt < ubi['low_bar'].dt
    # 测试自定义信号
    c = CZSC(bars, get_signals=None)
    bi_list = c.bi_list
    # if len(bi_list) > 1:
    #     last_bi = bi_list[-1]
    #     sec_bi = bi_list[-2]
    #     if last_bi.fx_a.fx*1.5 < last_bi.fx_b.fx or last_bi.fx_a.fx*1.5 < last_bi.fx_b.fx:
    #         print(code)
        # print("fx_a={}".format(last_bi.fx_a.fx))
        # print("fx_b={}".format(last_bi.fx_b.fx))
        # print("fx_a={}".format(sec_bi.fx_a.fx))
        # print("fx_b={}".format(sec_bi.fx_b.fx))
        # print(str(sec_bi.fx_b.has_zs))
    # # 查看每一笔的加速度
    # for bi in c.bi_list:
    #     print(bi.fx_a.dt, bi.fx_b.dt)
    #     print(bi.slope)

    kline = [x.__dict__ for x in c.bars_raw]
    bi = [{'dt': x.fx_a.dt, "bi": x.fx_a.fx} for x in c.bi_list] + \
         [{'dt': c.bi_list[-1].fx_b.dt, "bi": c.bi_list[-1].fx_b.fx}]
    chart = kline_pro(kline, bi=bi, title="{} - {}".format(c.symbol, c.freq))
    file_html = "html/{}.html".format(code)
    chart.render(file_html)
    # os.remove(file_html)

def read_json(path):
    with open(path, 'r') as file:
        data = json.load(file)
        return data

def get_all_stock():
    stock_cache_path = '/Users/wj/chan.py/Script/all_stock.json'
    if os.path.exists(stock_cache_path):
        return read_json(stock_cache_path)

if __name__ == '__main__':
    lg = bs.login()
    # 登录baostock
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)

    if len(stock_symbol)>0:
        test_czsc_update(stock_symbol)
    else:
        # all_stock  = get_all_stock()
        all_stock = ["sh.601869","sh.603068","sh.603211","sh.603291","sh.603308","sh.603928","sh.605488","sz.000856","sz.000882","sz.001282","sz.002187","sz.300170","sz.300287","sz.300548","sz.300570","sz.300608","sz.300634","sz.300654","sz.300697","sz.300840","sz.300980","sz.300996","sz.301061","sz.301187","sz.301210","sz.301220","sz.301248","sz.301299","sz.301498"]
        for stock in all_stock:
            test_czsc_update(stock)
    # 登出系统
    bs.logout()