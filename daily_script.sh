#!/bin/bash
# rm -rf ~/czsc/data/log.json
# source ~/workspace/czsc/czsc_env/bin/activate
cd ~/czsc
# python czsc_daily_stock.py

current_datetime=$(date +%Y-%m-%d_%H:%M:%S)
if cat ./data/log.json | grep -q "Stock Finished!"; then
	git add .
	git commit -m "${current_datetime} update daily stock"
	git push
fi