#coding:utf-8
import time
import os
import sys
import json
from urllib import parse
import baostock as bs
from czsc_daily_util import *
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains

LAST_DAYS = '2025-03-07'
def is_element_exist(webdriver, xpath):
    try:
        elem = webdriver.find_elements_by_xpath(xpath)
        if elem:
            return True
    except Exception as e:
        pass
    return False

def fetch_sh_tbody(tbody):
    data_list = []
    tr_list = tbody.find_elements(By.TAG_NAME,"tr")
    for tr in tr_list:
        td_list = tr.find_elements(By.TAG_NAME,"td")
        if len(td_list) == 4:
            dt_elm = td_list[0]
            code_elm = td_list[1]
            name_elm = td_list[2]
            num_elm = td_list[3]
            data_list.append({'dt':dt_elm.text,'code':code_elm.text,'name':name_elm.text,'share':num_elm.text})
    print(data_list)
    return data_list

def fetch_sh_page(driver):
    data_list = []

    last_data_list = None
    while True:
        xpath = '//div/table/tbody'
        tbody = driver.find_element(By.XPATH,xpath)
        res_list = fetch_sh_tbody(tbody)
        # blank page
        if len(res_list) <= 0:
            return data_list
        # dumplicate page
        if last_data_list and len(last_data_list)>0:
            cur_item0 = res_list[0]
            last_item0 = last_data_list[0]
            if cur_item0["code"] == last_item0["code"]:
                return data_list
        last_data_list = res_list
        data_list.extend(res_list)

        # next page
        next_page = driver.find_element(By.CLASS_NAME,"next")
        if next_page.is_displayed() and next_page.is_enabled():
            next_page.click()
            time.sleep(10)

    return data_list

def fetch_sh_day(today):
    filepath = get_data_dir()+'/etf/sh/{}.json'.format(today)
    if os.path.isfile(filepath):
        return True

    driver = webdriver.Chrome()
    url = 'https://www.sse.com.cn/market/funddata/volumn/etfvolumn/'
    print(url)
    driver.get(url)
    time.sleep(10)
    
    try:
        # 定位到指定的那天
        if today != LAST_DAYS:
            div_elm = driver.find_element(By.CLASS_NAME,"sse_searchInput")
            pre_page = div_elm.find_element(By.TAG_NAME,"input")
            js = "arguments[0].value = '{}';".format(today)
            driver.execute_script(js, pre_page)
            pre_page.click()
            time.sleep(3)
        
            confirm_elm = driver.find_element(By.CLASS_NAME,"laydate-btns-confirm")
            confirm_elm.click()
            time.sleep(5)

        # 获取改天数据
        res_list = fetch_sh_page(driver)
        write_json(res_list,filepath)
    except Exception as e:
        print(e)
        return False
    finally:
        driver.quit()
    return False

def fetch_sz_page(code,driver):
    data_list = []

    xpath = '//div/table/tbody'
    tbody_list = driver.find_elements(By.XPATH,xpath)
    tbody = tbody_list[2]
    tr_list = tbody.find_elements(By.TAG_NAME,"tr")
    for tr in tr_list:
        td_list = tr.find_elements(By.TAG_NAME,"td")
        if len(td_list) == 4:
            dt_elm = td_list[0]
            code_elm = td_list[1]
            name_elm = td_list[2]
            num_elm = td_list[3]
            data_list.append({'dt':dt_elm.text,'code':code_elm.text,'name':name_elm.text,'share':num_elm.text})
    print(data_list)
    return data_list

def create_sz_share_webdriver(retry_num=1):
    driver = webdriver.Chrome()
    url = 'https://fund.szse.cn/marketdata/fundslist/index.html'
    print(url)
    driver.get(url)
    time.sleep(MIN(20, 5*retry_num))
    
    # 点击进入份额历史数据
    div_elm = driver.find_element(By.CLASS_NAME,"report-table")
    xpath = '//div/table/tbody'
    tbody_list = div_elm.find_elements(By.XPATH,xpath)
    tbody = tbody_list[1]
    tr_list = tbody.find_elements(By.TAG_NAME,"tr")
    for tr in tr_list:
        td_list = tr.find_elements(By.TAG_NAME,"td")
        if len(td_list) > 5:
            link_elm = td_list[5]
            link_elm = link_elm.find_element(By.TAG_NAME,"a")
            link_elm.click()
            time.sleep(MIN(20, 5*retry_num))
            break
    return driver

def fetch_sz_etf(out_driver,code,today,retry_num=1):
    etf_data_dict = {}
    filepath = get_data_dir()+'/etf/sz/{}.json'.format(code)
    if os.path.isfile(filepath):
        etf_data_list = read_json(filepath)
        for item in etf_data_list:
            etf_data_dict[item['dt']] = item['share']
        if today in etf_data_dict.keys():
            return True

    is_failed = False
    if out_driver:
        driver = out_driver
    else:
        driver = create_sz_share_webdriver(retry_num)

    data_list = []
    try:
        last_data_list = None
        while True:
            print(today)
            # 输入框
            code_elm = driver.find_element(By.ID,"fund_jjgm_tab1_txtDm")
            code_elm.clear()
            code_elm.send_keys(code)
        
            # 起始日期
            start_elm = driver.find_element(By.ID,"fund_jjgm_tab1_txtStart")
            js = "arguments[0].value = '{}';".format(prev_date(today,20))
            driver.execute_script(js, start_elm)
            start_elm.click()

            # 结束日期
            end_elm = driver.find_element(By.ID,"fund_jjgm_tab1_txtEnd")
            js = "arguments[0].value = '{}';".format(today)
            driver.execute_script(js, end_elm)
            end_elm.click()

            # 点击查询按钮
            confirm_elm_list = driver.find_elements(By.TAG_NAME,"button")
            for confirm_elm in confirm_elm_list:
                if confirm_elm.text == "查询":
                    confirm_elm.click()
                    time.sleep(MIN(10,3*retry_num))
                    break

            # 获取份额数据
            res_list = fetch_sz_page(code,driver)
            # blank page
            if len(res_list) <= 0:
                break
            # dumplicate page
            if last_data_list and len(last_data_list)>0:
                cur_item0 = res_list[0]
                last_item0 = last_data_list[0]
                if cur_item0["dt"] == last_item0["dt"]:
                    break
            last_data_list = res_list
            data_list.extend(res_list)

            # 日期循环
            today = prev_date(today,21)
            if '2023-10' in today or today in etf_data_dict.keys():
                break
    except Exception as e:
        print(e)
        is_failed = True
    finally:
        if not out_driver:
            driver.quit()

    # 更新本地缓存
    etf_data_list = read_json(filepath)
    if not etf_data_list:
        etf_data_list = []
    for item in data_list:
        if not item['dt'] in etf_data_dict.keys():
            etf_data_list.append(item)
    write_json(etf_data_list,filepath)
    return not is_failed

def fetch_sz_tbody(tbody):
    data_list = []
    tr_list = tbody.find_elements(By.TAG_NAME,"tr")
    for tr in tr_list:
        td_list = tr.find_elements(By.TAG_NAME,"td")
        if len(td_list) > 3:
            code_elm = td_list[0]
            code_elm = code_elm.find_element(By.TAG_NAME,"u")
            name_elm = td_list[1]
            name_elm = name_elm.find_element(By.TAG_NAME,"u")
            type_elm = td_list[3]
            # if type_elm.text == "股票基金":
            data_list.append({'code':code_elm.text,'name':name_elm.text})
    return data_list

def fetch_sz_day(today):
    filepath = get_data_dir()+'/etf/sz/eft.json'
    if os.path.isfile(filepath):
        etf_data_dict = read_json(filepath)
        if etf_data_dict and etf_data_dict['today'] == today:
            return etf_data_dict['list']

    driver = webdriver.Chrome()
    url = 'https://fund.szse.cn/marketdata/fundslist/index.html'
    print(url)
    driver.get(url)
    time.sleep(5)
    
    data_list = []
    try:
        last_data_list = None
        while True:
            div_elm = driver.find_element(By.CLASS_NAME,"report-table")
            xpath = '//div/table/tbody'
            tbody_list = div_elm.find_elements(By.XPATH,xpath)
            tbody = tbody_list[1]
            res_list = fetch_sz_tbody(tbody)
            # blank page
            if len(res_list) <= 0:
                break
            # dumplicate page
            if last_data_list and len(last_data_list)>0:
                cur_item0 = res_list[0]
                last_item0 = last_data_list[0]
                if cur_item0["code"] == last_item0["code"]:
                    break
            last_data_list = res_list
            data_list.extend(res_list)

            # next page
            next_page_list = driver.find_elements(By.CLASS_NAME,"next")
            next_page = next_page_list[0]
            next_page = next_page.find_element(By.TAG_NAME,"a")
            if next_page.is_displayed() and next_page.is_enabled():
                next_page.click()
                time.sleep(5)
            else:
                break
    except Exception as e:
        print(e)
        sys.exit(-1)
    finally:
        driver.quit()

    # 缓存
    etf_data_dict = {'today':today,'list':data_list}
    write_json(etf_data_dict,filepath)

    return data_list

def prev_date(now_date_str,days_val=1):
    today = datetime.strptime(now_date_str, "%Y-%m-%d")
    yesterday = today - timedelta(days=days_val)
    return yesterday.strftime("%Y-%m-%d")

def automatic_click():
    today = LAST_DAYS
    # 深圳etf数据
    etf_code_list = fetch_sz_day(today)
    out_driver = create_sz_share_webdriver()
    for item in etf_code_list:
        print("{}进度：{} / {}".format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'),etf_code_list.index(item),len(etf_code_list)))

        retry_num = 1
        while True:
            if fetch_sz_etf(out_driver,item['code'],today,retry_num):
                break
            retry_num = retry_num + 1
            out_driver.quit()
            out_driver = create_sz_share_webdriver()
            print(item['code'])
            print("重试第【{}】次".format(retry_num))    
    out_driver.quit()

    # 上海etf数据
    while True:
        print(today)
        if fetch_sh_day(today):
            break
        today = prev_date(today)

if __name__ == '__main__':
    # 获取当前日期
    today = datetime.today()
    # 获取当前日期是星期几（0 表示星期一，6 表示星期日）
    weekday = today.weekday()
    # etf晚上10点再更新
    now = datetime.now()
    while (now.hour < 22 or now.minute < 30) and weekday<=5:
        print("当前时间：", now.strftime("%Y-%m-%d %H:%M:%S"))
        time.sleep(60*5)
        now = datetime.now()

    # baostock登录
    lg = bs.login()
    # 登录baostock
    czsc_logger().info('login respond error_code:' + lg.error_code)
    czsc_logger().info('login respond  error_msg:' + lg.error_msg)
    LAST_DAYS = get_latest_trade_date()
    # 登出系统
    bs.logout()
    # 自动抓取上证eft数据和深证etf数据
    automatic_click()

                        





