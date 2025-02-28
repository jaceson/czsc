#!/bin/bash
param1="$1"
echo "参数: $param1"

rm -rf ~/czsc/data/log.json
source ~/workspace/czsc/czsc_env/bin/activate
cd ~/czsc
python czsc_daily_stock.py
#commit
if [[ "$param1" == "push" ]]; then
	current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
	if grep -q "Stock Finished!" ~/czsc/data/log.json; then
		git add .
		git commit -m "${current_datetime} update daily stock"
		git push
	fi
fi
