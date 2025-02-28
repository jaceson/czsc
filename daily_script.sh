#!/bin/bash
rm -rf ~/czsc/data/log.json
source ~/workspace/czsc/czsc_env/bin/activate
cd ~/czsc
python czsc_daily_stock.py
if cat ./data/log.json | grep -q "logout success!"; then
	git add .
	current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
	git commit -m "${current_datetime} update daily stock"
	git push
fi