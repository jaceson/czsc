#!/bin/bash

source /Users/wj/workspace/czsc/czsc_env/bin/activate
cd /Users/wj/czsc
python czsc_daily_stock.py | tee -a ./data/log.json