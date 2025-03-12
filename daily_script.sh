#!/bin/bash
param1="$1"
echo "参数: $param1"
# 激活虚拟环境
rm -rf ~/czsc/data/log.json
source ~/workspace/czsc/czsc_env/bin/activate
# 股票筛选
cd ~/czsc
python czsc_daily_stock.py
# etf数据更新
python czsc_auto_etf.py
# etf数据写入数据库
python czsc_sqlite.py
# etf数据筛选
python czsc_daily_etf.py
#commit
if [[ "$param1" == "push" ]]; then
	current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
	if grep -q "Stock Finished!" ~/czsc/data/log.json; then
		git add .
		git commit -m "${current_datetime} update daily stock"
		git push
	fi
fi
