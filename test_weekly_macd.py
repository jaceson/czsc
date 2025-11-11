# coding: utf-8
"""
测试周线MACD背离+金叉策略
"""
import sys
from czsc_daily_util import get_daily_symbols
from CZSCStragegy_WeeklyMACDDivergence import check_weekly_macd_strategy
import baostock as bs
import pandas as pd
    
#### 登陆系统 ####
lg = bs.login()
# 显示登陆返回信息
print('login respond error_code:'+lg.error_code)
print('login respond  error_msg:'+lg.error_msg)
    
#### 获取沪深A股历史K线数据 ####
# 详细指标参数，参见“历史行情指标参数”章节；“分钟线”参数与“日线”参数不同。“分钟线”不包含指数。
# 分钟线指标：date,time,code,open,high,low,close,volume,amount,adjustflag
# 周月线指标：date,code,open,high,low,close,volume,amount,adjustflag,turn,pctChg
rs = bs.query_history_k_data_plus("sh.600000",
        "date,code,open,high,low,close,volume,amount,adjustflag",
        start_date='2024-07-01', end_date='2024-12-31',
        frequency="w", adjustflag="3")
print('query_history_k_data_plus respond error_code:'+rs.error_code)
print('query_history_k_data_plus respond  error_msg:'+rs.error_msg)
    
#### 打印结果集 ####
data_list = []
while (rs.error_code == '0') & rs.next():
    # 获取一条记录，将记录合并在一起
    data_list.append(rs.get_row_data())
result = pd.DataFrame(data_list, columns=rs.fields)

def test_single_stock():
    """测试单只股票"""
    # 测试股票代码
    test_symbols  = get_daily_symbols()

    print("=" * 80)
    print("测试周线MACD背离+金叉策略")
    print("=" * 80)
    
    for symbol in test_symbols:
        print("进度：{} / {}".format(test_symbols.index(symbol),len(test_symbols)))
        print(f"\n测试股票: {symbol}")
        print("-" * 80)
        
        is_match, info = check_weekly_macd_strategy(symbol)
        
        if is_match:
            print(f"✅ {symbol} 符合策略条件！")
            print(f"   日期: {info['last_date']}")
            print(f"   收盘价: {info['last_close']:.2f}")
            print(f"   DIF: {info['last_dif']:.4f}")
            print(f"   DEA: {info['last_dea']:.4f}")
            print(f"   MACD: {info['last_macd']:.4f}")
        else:
            print(f"❌ {symbol} 不符合策略条件")
    
    print("\n" + "=" * 80)

# if __name__ == '__main__':
#     test_single_stock()
