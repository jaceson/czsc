#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import math
import getopt
from datetime import datetime,timedelta

def usage():
    print ("-l: 低点")
    print ("-t: 高点")
    print ("-s: 起始日期")
    print ("-e: 结束日期")
    pass

opts,args = getopt.getopt(sys.argv[1:], "ht:l:s:e:")
low_val = 0
high_val = 0
start_date = ""
end_date = ""
for op, value in opts:
    if op == "-l":
        low_val = float(value)
    elif op == "-t":
        high_val = float(value)
    elif op == "-s":
        start_date = value
    elif op == "-e":
        end_date = value
    elif op == "-h":    
        usage()
        sys.exit()

print("低点："+str(low_val))
print("高点："+str(high_val))
print("起始日期："+str(start_date))
print("结束日期："+str(end_date))
print("\n")

# 低点&高点值校验
is_num_valid = False
is_date_valid = False
if low_val > 0 and high_val > 0 and high_val > low_val:
    is_num_valid = True
# 日期值校验
if len(start_date)>0 and len(end_date)>0:
    date1 = datetime.strptime(start_date, "%Y-%m-%d")
    date2 = datetime.strptime(end_date, "%Y-%m-%d")
    if date1 < date2:
        is_date_valid = True
# 数值和日期都错误
if not is_num_valid and not is_date_valid:
	print("输入参数不合法！！！")
	sys.exit()

# 乘积平方根
def sqrt_val(a,b):
	return round(math.sqrt(a*b),3)

# 中间位
def mid_val(a,b):
    return round((a+b)/2.0,3)

# 黄金分割线
def gold_val_low(a,b):
	# 0.382、 0.618
	val = max(a,b)-min(a,b)
	return val*0.382 + min(a,b)

def gold_val_high(a,b):
	# 0.382、 0.618
	val = max(a,b)-min(a,b)
	return val*0.618 + min(a,b)

def get_date_diff(a,b):
    date1 = datetime.strptime(a, "%Y-%m-%d")
    date2 = datetime.strptime(b, "%Y-%m-%d")
    diff = date2 - date1
    return diff.days

def get_date_future(a,days):
    delta = timedelta(days)
    date = datetime.strptime(a, "%Y-%m-%d")
    date = date + delta
    return date.strftime("%Y-%m-%d")

def gold_date_val(a,b):
    days = get_date_diff(a,b)
    delta = timedelta(days)
    date = datetime.strptime(b, "%Y-%m-%d")
    date = date + delta
    return date.strftime("%Y-%m-%d")

print("关键点位：")
if is_num_valid:
    print("           1）平   方  根："+str(sqrt_val(low_val,high_val)))
    print("           2）中   间  位："+str(mid_val(low_val,high_val)))
    print("           3）黄金分割高点："+str(gold_val_high(low_val,high_val)))
    print("           4）黄金分割低点："+str(gold_val_low(low_val,high_val)))
    print('\n')
if is_date_valid:
    days = get_date_diff(start_date,end_date)
    print("           1）上涨天数："+str(days))
    print("           2）中间位："+str(get_date_future(end_date,math.ceil(days*0.5))))
    print("           3）最少黄金位："+str(get_date_future(end_date,math.ceil(days*0.382))))
    print("           4）最多黄金位："+str(get_date_future(end_date,math.ceil(days*0.618))))
    