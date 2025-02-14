import sys
sys.path.insert(0, '.')
sys.path.insert(0, '..')
import czsc

czsc.set_url_token(token="dae43c122a5707dec0d54bd8b6fc2dc5f840d9ca2364577fa8e99a12", url="http://api.tushare.pro")

pro = czsc.DataClient(url="http://api.tushare.pro", cache_path="~/.quant_data_cache")
df = pro.income(
    ts_code="000001.SH",
    fields="ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,basic_eps,diluted_eps",
)
