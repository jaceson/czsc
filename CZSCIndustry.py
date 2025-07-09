# coding: utf-8
import os
import sys
import pandas as pd
import numpy as np
import baostock as bs
import akshare as ak
from lib.MyTT import *
from czsc_daily_util import *

def main():
    # 获取所有概念板块列表
    concept_df = ak.stock_board_concept_name_em()
    print(concept_df.head())

    # 获取某个概念的成分股，例如 "人工智能"
    concept_stocks_df = ak.stock_board_concept_cons_em(symbol="人工智能")
    print(concept_stocks_df.head())

    # 获取行业板块列表
    # industry_df = ak.stock_board_industry_name_em()
    # print(industry_df.head())

    # # 获取某个行业的成分股，例如 "半导体"
    # stocks_df = ak.stock_board_industry_cons_em(symbol="半导体")
    # print(stocks_df.head())

    # lg = bs.login()
    # # 获取行业分类数据
    # rs = bs.query_stock_industry()

    # # 打印结果
    # while rs.next():
    #     print(rs.get_row_data())
    # bs.logout()

if __name__ == '__main__':
    main()
