# coding: utf-8
import os
import sys
from czsc.analyze import *
from czsc_daily_util import *

def test_czsc_update(code):
    c = CZSC(bars, get_signals=None)
    kline = [x.__dict__ for x in c.bars_raw]
    bi = [{'dt': x.fx_a.dt, "bi": x.fx_a.fx} for x in c.bi_list] + \
         [{'dt': c.bi_list[-1].fx_b.dt, "bi": c.bi_list[-1].fx_b.fx}]
    chart = kline_pro(kline, bi=bi, title="{} - {}".format(c.symbol, c.freq))
    file_html = "x.html"
    chart.render(file_html)

if __name__ == '__main__':
    lg = bs.login()
    # 登录baostock
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)

    all_stock  = get_all_stock()
    # for stock in all_stock:
    test_czsc_update('sz.300972')
    # 登出系统
    bs.logout()