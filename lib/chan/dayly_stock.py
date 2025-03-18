import os
import sys
import shutil
parentdir = os.path.dirname(os.path.abspath(__file__))

def stock_full_code(code):
    if code.startswith('60'):
        return "sh."+code
    else:
        return "sz."+code

if __name__ == "__main__":
    # 清空历史数据
    result_path = parentdir+"/Daily"
    shutil.rmtree(result_path)
    os.mkdir(result_path)

    # 当天需要观察的股票
    dayly_stock = ["600255","600410","600580","600601","600673","600694","600708","601689","601869","601933","603119","603236","603306","603308","603662","603667","603699","603893","000681","002031","002117","002127","002131","002195","600126","600398","600633","600933","600988","601100","603171","603191","603379","603758","603915","605020","000837","001282","002126","002334","002664","002729","002913","002929","002965","300124","300251","301192","301210","301261","301310","301328","301368","301413","301512","301568"]
    dayly_stock_final = []
    for stock in dayly_stock:
        # 过滤重复股票
        if stock in dayly_stock_final:
            continue
        dayly_stock_final.append(stock)
        # 补全前缀
        stock = stock_full_code(stock)
        # 日K线
        os.system(f"python main.py {stock}")
        # 30分钟K线
        # os.system(f"python main.py {stock} 1")
        
