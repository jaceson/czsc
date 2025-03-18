import baostock as bs
import pandas as pd
from datetime import datetime, timedelta

def get_stock_basic(bs,code):
    rs = bs.query_stock_basic(code=code)
    stock_df = rs.get_data()
    
if __name__ == "__main__":
    # 登录 baostock
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
    rs = bs.query_stock_basic(code="sz.159928")
    stock_df = rs.get_data()
    print(stock_df)
    open('file.txt')
    # 获取所有股票的基本信息
    rs = bs.query_all_stock(day="2025-01-24")
    # stock_df = rs.get_data()
    data_list = []
    while (rs.error_code == '0') and rs.next():
        stock_df = rs.get_row_data()

        data_list.append()
    result = pd.DataFrame(data_list, columns=rs.fields)
    print(result)
    open('file.txt')

    # 当前日期
    current_date = datetime.strptime('2025-02-01', '%Y-%m-%d')
    # 上市一年以上的日期
    one_year_ago = current_date - timedelta(days=365)

    # 筛选上市一年以上的股票
    print(stock_df)
    stock_df['ipoDate'] = pd.to_datetime(stock_df['ipoDate'])
    filtered_stocks = stock_df[stock_df['ipoDate'] < one_year_ago]

    # 加载融资融券标的股票名单
    # margin_stocks = pd.read_csv('margin_stocks.csv')

    # 筛选可融资融券的股票
    # filtered_stocks = filtered_stocks[filtered_stocks['code'].isin(margin_stocks['code'])]

    # 保存到文件
    print(filtered_stocks[['code']])
    # filtered_stocks[['code']].to_csv('filtered_stocks.csv', index=False)

    # 登出系统
    bs.logout()