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

        # 退出chrome
        driver.quit()

        return True
    except Exception as e:
        print(e)
        driver.quit()
    return False

def fetch_sz_day(today):
    filepath = get_data_dir()+'/etf/sz/{}.json'.format(today)
    if os.path.isfile(filepath):
        return True

    driver = webdriver.Chrome()
    url = 'https://fund.szse.cn/marketdata/fundslist/index.html'
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

        # 退出chrome
        driver.quit()

        return True
    except Exception as e:
        print(e)
        driver.quit()
    return False

def prev_date(now_date_str):
    today = datetime.strptime(now_date_str, "%Y-%m-%d")
    yesterday = today - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")

def write_json(data, json_path):
    if os.path.exists(json_path):
        os.remove(json_path)
    with open(json_path, 'w') as file:
        json.dump(data, file, indent=4)
        file.close()

def automatic_click():
    today = LAST_DAYS
    while True:
        print(today)
        fetch_sh_day(today)

        today = prev_date(today)

if __name__ == '__main__':
    lg = bs.login()
    # 登录baostock
    czsc_logger().info('login respond error_code:' + lg.error_code)
    czsc_logger().info('login respond  error_msg:' + lg.error_msg)
    LAST_DAYS = get_latest_trade_date()
    # 登出系统
    bs.logout()

    automatic_click()

                        





