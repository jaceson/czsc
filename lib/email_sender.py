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

def create_mail_conf(username, password):
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

def get_mail_pass(username):
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

def send_smtpmail_core(mail_host, username, sender_email, sender_pasword, receivers, message):
    try:
        smtpObj = smtplib.SMTP()
        smtpObj.connect(mail_host, 465)
        smtpObj.login(username, sender_pasword)
        smtpObj.sendmail(sender_email, receivers, message.as_string()) 
        smtpObj.quit()
        print('send to {} success'.format(receivers))
        return True
    except smtplib.SMTPException as e:
        print('send to {} error'.format(receivers), e)
        return False

def send_html_email(username, receivers, subject, content, attachments_path=None, cc_list=None, image_list=None):
    #fix receivers
    if isinstance(receivers, list):
        if len(receivers) == 1:
            receivers_str = receivers[0]
        else:
            receivers_str = ",".join(receivers)
    else:
        receivers_str = receivers
        receivers = receivers.split(",")

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

    #password first
    sender_pasword = get_mail_pass(username)

    mail_host = 'mail.iqiyi.com'
    sender_email = '{}@qiyi.com'.format(username)

    #html message
    message = MIMEMultipart("related")
    message['Subject'] = subject
    message['From'] = sender_email 
    message['To'] = receivers_str
    message['Cc'] = cc_str

    html_body = MIMEText(content, 'html', 'utf-8')
    message.attach(html_body)

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

    if image_list is not None and len(image_list) > 0:
        for file in image_list:
            with open(file, 'rb') as fp:
                part = MIMEImage(fp.read())
            part.add_header('Content-ID', '<%s>' % file)
            message.attach(part)

    send_success = False
    send_cnt = 1
    max_retry_cnt = 5 #retry
    while send_cnt <= max_retry_cnt and not send_success:
        if send_cnt > 1:
            print("start to retry")
        print("send cnt is {}......".format(send_cnt))
        send_success = send_smtpmail_core(mail_host, username, sender_email, sender_pasword, receivers, message)
        send_cnt += 1

if __name__ == '__main__':
    create_mail_conf("autobuild4ios", "2E2DCa*8y@d3")
    html = '<head>BUILD FAILED</head><body><a href="http://www.baidu.com">http://www.baidu.com</a></body>'
    send_html_email("autobuild4ios", "vickywang@qiyi.com", "Hi, This is a Test", html, None, None)
