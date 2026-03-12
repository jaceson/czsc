#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import smtplib
import configparser
import base64
import random
import string
import time

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage

def create_mail_conf_163(username, password):
    """
    创建邮件配置文件，存储 base64 编码后的密码
    username: 163邮箱用户名（不含 @163.com 部分）
    password: 163邮箱授权码（不是登录密码！）
    """
    path = os.path.expanduser("~/klavo_mail.conf")
    if not os.path.exists(path):
        with open(path, "w", encoding='utf-8') as f:
            f.write("")

    email_config = configparser.ConfigParser()
    email_config.read(path, encoding='utf-8')

    coded_password = random.choice(string.ascii_letters) + base64.b64encode(password.encode()).decode() + random.choice(string.ascii_letters)
    if not email_config.has_section(username):
        email_config.add_section(username)
    email_config.set(username, "password", coded_password)

    with open(path, "w", encoding='utf-8') as f:
        email_config.write(f)
    print(f"配置已保存到 {path}")

def get_mail_pass_163(username):
    """从配置文件获取解码后的密码"""
    path = os.path.expanduser("~/klavo_mail.conf")
    email_config = configparser.ConfigParser()

    email_config.read(path, encoding='utf-8')

    try:
        origin_password = email_config.get(username, "password")
        decoded_pass = base64.b64decode(origin_password[1:len(origin_password)-1])
        if isinstance(decoded_pass, bytes):
            decoded_pass = decoded_pass.decode("utf-8") 
        return decoded_pass
    except Exception as e:
        print("Cannot get email password, plz run create pass first.")
        raise e

def send_smtpmail_core(mail_host, port, username, sender_email, sender_password, receivers, message, use_ssl=True):
    """
    核心发送函数
    163邮箱使用 SSL 连接，端口 465 或 994
    """
    try:
        if use_ssl:
            # 163邮箱必须使用 SSL
            smtpObj = smtplib.SMTP_SSL(mail_host, port)
        else:
            smtpObj = smtplib.SMTP()
            smtpObj.connect(mail_host, port)

        smtpObj.login(username, sender_password)
        smtpObj.sendmail(sender_email, receivers, message.as_string()) 
        smtpObj.quit()
        print('send to {} success'.format(receivers))
        return True
    except smtplib.SMTPException as e:
        print('send to {} error'.format(receivers), e)
        return False

def send_html_email(username, receivers, subject, content, attachments_path=None, cc_list=None, image_list=None):
    """
    发送 HTML 邮件（支持附件和图片）

    参数:
        username: 163邮箱用户名（如 xxx，完整邮箱为 xxx@163.com）
        receivers: 收件人列表或字符串（多个用逗号分隔）
        subject: 邮件主题
        content: HTML 内容
        attachments_path: 附件路径列表（可选）
        cc_list: 抄送列表（可选）
        image_list: 内嵌图片路径列表（可选，需在 HTML 中引用）
    """
    # 处理收件人格式
    if isinstance(receivers, list):
        if len(receivers) == 1:
            receivers_str = receivers[0]
        else:
            receivers_str = ",".join(receivers)
    else:
        receivers_str = receivers
        receivers = receivers.split(",")

    # 处理抄送
    cc_str = None
    if isinstance(cc_list, list):
        if len(cc_list) == 1:
            cc_str = cc_list[0]
        else:
            cc_str = ",".join(cc_list)
        receivers.extend(cc_list)
    elif isinstance(cc_list, str):
        cc_str = cc_list
        receivers.extend(cc_list.split(","))

    # 获取密码（授权码）
    sender_password = get_mail_pass_163(username)

    # ==================== 163 邮箱配置 ====================
    mail_host = 'smtp.163.com'           # 163 SMTP 服务器
    smtp_port = 465                       # SSL 端口（也可用 994）
    sender_email = '{}@163.com'.format(username)  # 完整发件地址
    # =====================================================

    # 构建邮件
    message = MIMEMultipart("related")
    message['Subject'] = subject
    message['From'] = sender_email 
    message['To'] = receivers_str
    if cc_str:
        message['Cc'] = cc_str

    # HTML 正文
    html_body = MIMEText(content, 'html', 'utf-8')
    message.attach(html_body)

    # 添加附件
    if attachments_path is not None and len(attachments_path) > 0:
        for attachment_file_path in attachments_path:
            if os.path.exists(attachment_file_path):
                filename = os.path.basename(attachment_file_path)
                with open(attachment_file_path, 'rb') as f:
                    part = MIMEApplication(f.read())
                part.add_header('Content-Disposition', 'attachment', filename=filename)
                message.attach(part)
            else:
                print("file not exists at {}".format(attachment_file_path))

    # 添加内嵌图片（需在 HTML 中用 <img src=\"cid:filename\"> 引用）
    if image_list is not None and len(image_list) > 0:
        for file in image_list:
            if os.path.exists(file):
                with open(file, 'rb') as fp:
                    part = MIMEImage(fp.read())
                # 使用文件名作为 Content-ID
                cid = os.path.basename(file)
                part.add_header('Content-ID', '<%s>' % cid)
                message.attach(part)
            else:
                print("image not exists at {}".format(file))

    # 发送邮件（带重试机制）
    send_success = False
    send_cnt = 1
    max_retry_cnt = 5
    while send_cnt <= max_retry_cnt and not send_success:
        if send_cnt > 1:
            print("start to retry")
        print("send cnt is {}......".format(send_cnt))
        send_success = send_smtpmail_core(
            mail_host, smtp_port, username, sender_email, 
            sender_password, receivers, message, use_ssl=True
        )
        send_cnt += 1
        if not send_success and send_cnt <= max_retry_cnt:
            time.sleep(2)  # 重试前等待 2 秒

    return send_success


def receive_email_imap(username, folder="inbox", limit=10):
    """
    使用 IMAP 接收邮件（新增功能）

    参数:
        username: 163邮箱用户名
        folder: 邮箱文件夹（默认 inbox）
        limit: 获取邮件数量

    返回:
        邮件主题列表
    """
    import imaplib
    import email
    from email.header import decode_header

    password = get_mail_pass_163(username)

    # 连接到 163 IMAP 服务器
    imap_server = "imap.163.com"
    imap_port = 993

    try:
        # 使用 SSL 连接
        mail = imaplib.IMAP4_SSL(imap_server, imap_port)
        mail.login(username, password)

        # 选择邮箱文件夹
        status, messages = mail.select(folder)
        if status != "OK":
            print(f"无法选择文件夹: {folder}")
            return []

        # 获取邮件数量
        msg_count = int(messages[0])
        print(f"{folder} 文件夹共有 {msg_count} 封邮件")

        # 获取最新的 limit 封邮件
        result = []
        for i in range(max(1, msg_count - limit + 1), msg_count + 1):
            status, msg_data = mail.fetch(str(i), "(RFC822)")
            if status == "OK":
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        # 解码主题
                        subject, encoding = decode_header(msg["Subject"])[0]
                        if isinstance(subject, bytes):
                            subject = subject.decode(encoding or "utf-8")

                        # 获取发件人
                        from_addr = msg.get("From")

                        # 获取日期
                        date = msg.get("Date")

                        result.append({
                            "subject": subject,
                            "from": from_addr,
                            "date": date
                        })
                        print(f"[{i}] 主题: {subject} | 发件人: {from_addr}")

        mail.close()
        mail.logout()
        return result

    except Exception as e:
        print(f"接收邮件失败: {e}")
        return []


if __name__ == '__main__':
    # ==================== 使用示例 ====================

    # 1. 首次运行：创建配置（将 xxx 替换为你的 163 邮箱用户名，授权码替换为实际授权码）
    # 注意：password 参数是 163 邮箱的【授权码】，不是登录密码！
    # 获取方式：登录 163 邮箱网页版 → 设置 → POP3/SMTP/IMAP → 开启服务 → 获取授权码

    # create_mail_conf_163("13311566853", "EVumSbg8BMjaYHKu")

    # 2. 发送邮件示例
    html = '''
    <html>
    <head></head>
    <body>
        <h1 style="color: blue;">测试邮件</h1>
        <p>这是一封来自 <b>163 邮箱</b> 的测试邮件。</p>
        <p>点击访问：<a href="http://www.baidu.com">百度</a></p>
    </body>
    </html>
    '''
    
    # 发送给单个收件人
    send_html_email("13311566853", "13311566853@163.com", "测试邮件", html)
    # 
    # # 发送给多个收件人（带附件和抄送）
    # send_html_email(
    #     username="your_163_username",
    #     receivers=["vickywang@qiyi.com", "another@example.com"],
    #     subject="带附件的测试邮件",
    #     content=html,
    #     attachments_path=["/path/to/file.pdf"],
    #     cc_list=["cc@example.com"]
    # )

    # 3. 接收邮件示例
    # receive_email_imap("your_163_username", folder="inbox", limit=5)

    # print("请取消注释上面的示例代码并修改配置后运行")
    # print("注意：首次使用必须先运行 create_mail_conf_163() 保存授权码")
