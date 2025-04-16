#!/bin/bash
param1="$1"
param2="$2"
echo "参数1: $param1"
echo "参数2: $param2"
# 获取当前脚本的绝对路径
SCRIPT_PATH=$(realpath "$0")
# 获取当前脚本所在的目录
SCRIPT_DIR=$(dirname "$SCRIPT_PATH")
# 激活虚拟环境
cd ${SCRIPT_DIR}
rm -rf ${SCRIPT_DIR}/data/log.json
source ${SCRIPT_DIR}/czsc_env/bin/activate
# 股票筛选
python czsc_daily_stock.py
#commit
if [[ "$param1" == "push" ]]; then
	current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
	if grep -q "Stock Finished!" ${SCRIPT_DIR}/data/log.json; then
		git add .
		git commit -m "${current_datetime} update daily stock"
		git push
	fi
fi

#commit
if [[ "$param2" == "push" ]]; then
	# etf数据更新
	python czsc_auto_etf.py
	# etf数据写入数据库
	python czsc_sqlite.py
	# etf数据筛选
	python czsc_daily_etf.py

	current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
	if grep -q "Stock Finished!" ${SCRIPT_DIR}/data/log.json; then
		git add .
		git commit -m "${current_datetime} update daily etf"
		git push
	fi
fi
