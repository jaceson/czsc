#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时监控股票价格，当价格低于 golden_log.json 中的 sqr_val 和 gold_val 时发送邮件通知
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
import akshare as ak
import tushare as ts
import requests
from akshare_one import get_realtime_data

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from czsc_daily_util import (
    get_data_dir, 
    read_json, 
    write_json, 
    get_symbols_name,
    czsc_logger
)
from lib.email_sender import send_html_email, create_mail_conf

# 配置日志
logger = czsc_logger()

# 通知记录文件
NOTIFICATION_LOG_FILE = os.path.join(get_data_dir(), 'golden_notification_log.json')
# golden_log.json 文件路径
GOLDEN_LOG_FILE = os.path.join(get_data_dir(), 'golden_log.json')
# 监控间隔（秒）
MONITOR_INTERVAL = 300  # 每5分钟检查一次


def get_current_stock_price(symbol,pro):
    """
    获取股票当前价格
    优先使用实时行情，如果失败则使用最新收盘价
    """
    try:
        # 方法1: 使用 akshare 获取实时行情
        # 转换股票代码格式：sh.600501 -> 600501
        code = symbol.split('.')[-1]

        # 获取实时行情
        try:
            df = get_realtime_data(symbol=code)
            if df is not None and not df.empty:
                # 查找对应的股票
                low_price = float(df['low'].iloc[0])
                logger.debug(f"【{symbol}】实时价格: {low_price}")
                return low_price
        except Exception as e:
            logger.debug(f"获取 {symbol} 实时价格失败，尝试使用历史数据: {e}")
        # df = pro.index_basic(ts_code='600519.SH')
        df = pro.daily_basic(ts_code='600519.SH', fields='ts_code,trade_date,close')
        print(df)
        return None
        
    except Exception as e:
        logger.error(f"获取 {symbol} 价格时出错: {e}")
        return None


def load_notification_log():
    """加载通知记录"""
    if os.path.exists(NOTIFICATION_LOG_FILE):
        return read_json(NOTIFICATION_LOG_FILE)
    return {}


def save_notification_log(log_data):
    """保存通知记录"""
    write_json(log_data, NOTIFICATION_LOG_FILE)


def should_notify_today(symbol, log_data):
    """检查今天是否已经通知过"""
    today = datetime.now().strftime('%Y-%m-%d')
    if symbol in log_data:
        last_notify_date = log_data[symbol].get('last_notify_date', '')
        if last_notify_date == today:
            return False
    return True


def record_notification(symbol, price, sqr_val, gold_val, log_data):
    """记录通知"""
    today = datetime.now().strftime('%Y-%m-%d')
    log_data[symbol] = {
        'last_notify_date': today,
        'last_notify_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_price': price,
        'sqr_val': sqr_val,
        'gold_val': gold_val
    }
    save_notification_log(log_data)


def send_notification_email(stocks_to_notify):
    """发送通知邮件"""
    try:
        # 获取邮件密码
        response = requests.get('http://itpwd.qiyi.domain/api/GetPassword?domainuser=autobuild4ios&token=gbp84d012wsc973y')
        if response.status_code == 200:
            result = json.loads(response.content)
            password = result["password"]
            create_mail_conf("autobuild4ios", password)
        else:
            logger.error("无法获取邮件密码")
            return False
        
        # 构建邮件内容
        html_content = f"""
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: Arial, sans-serif; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <h2>股票价格监控通知</h2>
            <p>以下股票价格已低于设定的阈值：</p>
            <table>
                <tr>
                    <th>股票代码</th>
                    <th>股票名称</th>
                    <th>当前价格</th>
                    <th>平方根值(sqr_val)</th>
                    <th>黄金分割值(gold_val)</th>
                    <th>状态</th>
                </tr>
        """
        
        for stock_info in stocks_to_notify:
            symbol = stock_info['symbol']
            stock_name = get_symbols_name(symbol)
            current_price = stock_info['price']
            sqr_val = stock_info['sqr_val']
            gold_val = stock_info['gold_val']
            
            # 判断状态
            below_sqr = stock_info.get('below_sqr', current_price < sqr_val)
            below_gold = stock_info.get('below_gold', current_price < gold_val)
            
            if below_sqr and below_gold:
                status = "低于两个阈值"
            elif below_sqr:
                status = "低于平方根值"
            elif below_gold:
                status = "低于黄金分割值"
            else:
                status = "未知"
            
            html_content += f"""
                <tr>
                    <td>{symbol}</td>
                    <td>{stock_name}</td>
                    <td>{current_price:.2f}</td>
                    <td>{sqr_val:.2f}</td>
                    <td>{gold_val:.2f}</td>
                    <td>{status}</td>
                </tr>
            """
        
        html_content += """
            </table>
            <p>监控时间: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + """</p>
        </body>
        </html>
        """
        
        # 发送邮件
        subject = f"股票价格监控通知 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        send_html_email("autobuild4ios", "vickywang@qiyi.com", subject, html_content)
        logger.info(f"已发送通知邮件，包含 {len(stocks_to_notify)} 只股票")
        return True
        
    except Exception as e:
        logger.error(f"发送邮件失败: {e}")
        return False


def monitor_stocks(pro):
    """监控股票价格"""
    # 读取 golden_log.json
    if not os.path.exists(GOLDEN_LOG_FILE):
        logger.error(f"文件不存在: {GOLDEN_LOG_FILE}")
        return
    
    golden_data = read_json(GOLDEN_LOG_FILE)
    if not golden_data:
        logger.warning("golden_log.json 文件为空")
        return
    
    # 加载通知记录
    notification_log = load_notification_log()
    
    # 需要通知的股票列表
    stocks_to_notify = []
    
    logger.info(f"开始监控 {len(golden_data)} 只股票...")
    
    for symbol, stock_info in golden_data.items():
        time.sleep(5)
        try:
            sqr_val = stock_info.get('sqr_val')
            gold_val = stock_info.get('gold_val')
            
            if sqr_val is None or gold_val is None:
                logger.warning(f"【{symbol}】缺少 sqr_val 或 gold_val")
                continue
            
            # 获取当前价格
            current_price = get_current_stock_price(symbol,pro)
            if current_price is None:
                logger.warning(f"【{symbol}】无法获取价格")
                continue
            
            # 检查价格是否低于阈值（低于 sqr_val 或 gold_val 任一值即通知）
            price_below_sqr = current_price < sqr_val
            price_below_gold = current_price < gold_val
            
            if price_below_sqr or price_below_gold:
                # 检查今天是否已经通知过
                if should_notify_today(symbol, notification_log):
                    stock_name = get_symbols_name(symbol)
                    status_desc = []
                    if price_below_sqr:
                        status_desc.append(f"低于平方根值({sqr_val:.2f})")
                    if price_below_gold:
                        status_desc.append(f"低于黄金分割值({gold_val:.2f})")
                    
                    logger.info(f"【{symbol}】{stock_name} 价格 {current_price:.2f} {' 且 '.join(status_desc)}")
                    
                    stocks_to_notify.append({
                        'symbol': symbol,
                        'price': current_price,
                        'sqr_val': sqr_val,
                        'gold_val': gold_val,
                        'below_sqr': price_below_sqr,
                        'below_gold': price_below_gold
                    })
                    
                    # 记录通知（即使邮件发送失败也要记录，避免重复通知）
                    record_notification(symbol, current_price, sqr_val, gold_val, notification_log)
                else:
                    logger.debug(f"【{symbol}】今天已通知过，跳过")
            else:
                logger.debug(f"【{symbol}】价格 {current_price:.2f} 正常")
                
            # 避免请求过快
            time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"处理 {symbol} 时出错: {e}")
            continue
    
    # 如果有需要通知的股票，发送邮件
    if stocks_to_notify:
        send_notification_email(stocks_to_notify)
    else:
        logger.info("没有需要通知的股票")


def main():
    """主函数"""
    logger.info("=" * 50)
    logger.info("股票价格监控程序启动")
    logger.info(f"监控文件: {GOLDEN_LOG_FILE}")
    logger.info(f"监控间隔: {MONITOR_INTERVAL} 秒")
    logger.info("=" * 50)

    # 初始化 baostock
    try:
        ts.set_token('dae43c122a5707dec0d54bd8b6fc2dc5f840d9ca2364577fa8e99a12')
        pro = ts.pro_api()
    except Exception as e:
        logger.error(f"tushare 初始化失败: {e}")
        return
    
    try:
        while True:
            try:
                monitor_stocks(pro)
            except Exception as e:
                logger.error(f"监控过程出错: {e}")
                import traceback
                logger.error(traceback.format_exc())
            
            # 等待下次检查
            logger.info(f"等待 {MONITOR_INTERVAL} 秒后进行下次检查...")
            time.sleep(MONITOR_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，程序退出")
    finally:
        logger.info("程序已退出")


if __name__ == '__main__':
    main()
