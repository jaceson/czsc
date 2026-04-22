import akshare as ak
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import requests
import json

class RealtimeDataFetcher:
    """实时行情数据获取器"""
    
    def __init__(self):
        self.cache = {}
        self.last_update = {}
        self._baostock_initialized = False
        
    def _init_baostock(self):
        """初始化baostock连接"""
        if not self._baostock_initialized:
            try:
                import baostock as bs
                bs.login()
                self._baostock_initialized = True
                self._bs = bs
                print("baostock初始化成功")
            except Exception as e:
                print(f"baostock初始化失败: {e}")
                self._baostock_initialized = False
                
    def _close_baostock(self):
        """关闭baostock连接"""
        if self._baostock_initialized:
            try:
                self._bs.logout()
                self._baostock_initialized = False
            except:
                pass
    
    def _standardize_dataframe(self, df, source='baostock'):
        """
        标准化DataFrame的列名，统一为中文格式
        返回包含以下列的DataFrame: 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 涨跌幅
        """
        if df is None or df.empty:
            return pd.DataFrame()
        
        df = df.copy()
        
        if source == 'baostock':
            # baostock使用英文列名，转换为中文
            column_mapping = {
                'date': '日期',
                'open': '开盘',
                'close': '收盘',
                'high': '最高',
                'low': '最低',
                'volume': '成交量',
                'amount': '成交额',
                'pctChg': '涨跌幅'
            }
            df.rename(columns=column_mapping, inplace=True)
            
            # 确保日期列是datetime类型，并设置为索引
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'])
                if df.index.name != '日期':
                    df.set_index('日期', inplace=True)
                    
        elif source == 'akshare':
            # AKShare已经是中文列名，但可能需要调整
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'])
                if df.index.name != '日期':
                    df.set_index('日期', inplace=True)
            
            # 确保列名统一
            rename_map = {
                '开盘价': '开盘',
                '收盘价': '收盘',
                '最高价': '最高',
                '最低价': '最低',
                '成交量': '成交量',
                '成交额': '成交额',
                '涨跌幅': '涨跌幅'
            }
            df.rename(columns=rename_map, inplace=True)
        
        # 转换数据类型
        numeric_columns = ['开盘', '收盘', '最高', '最低', '成交量', '成交额', '涨跌幅']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    def get_realtime_price_baostock(self, stock_codes):
        """
        使用baostock获取实时行情
        pip install baostock
        """
        try:
            self._init_baostock()
            if not self._baostock_initialized:
                return {}
                
            result = {}
            for code in stock_codes:
                # baostock代码格式：sh.600000 或 sz.000001
                if code.startswith('6'):
                    bs_code = f"sh.{code}"
                elif code.startswith('0') or code.startswith('3'):
                    bs_code = f"sz.{code}"
                else:
                    bs_code = f"sz.{code}"
                
                # 获取实时K线数据（当日）
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
                
                k_rs = self._bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume,amount,pctChg",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="3"  # 不复权
                )
                
                if k_rs and k_rs.error_code == '0':
                    data = k_rs.get_data()
                    if data is not None and len(data) > 0:
                        latest = data.iloc[-1]
                        # 获取前一交易日收盘价
                        prev_close = data.iloc[-2]['close'] if len(data) > 1 else latest['open']
                        
                        # 获取股票名称
                        name = self._get_stock_name_baostock(bs_code)
                        
                        # 安全转换函数
                        def safe_float(val):
                            try:
                                if val is None or val == '' or val == 'None':
                                    return 0.0
                                return float(val)
                            except:
                                return 0.0
                        
                        result[code] = {
                            'name': name,
                            'price': safe_float(latest['close']),
                            'change_pct': safe_float(latest['pctChg']),
                            'volume': safe_float(latest['volume']),
                            'turnover': 0,
                            'high': safe_float(latest['high']),
                            'low': safe_float(latest['low']),
                            'open': safe_float(latest['open']),
                            'prev_close': safe_float(prev_close),
                            'amount': safe_float(latest['amount']),
                            'time': datetime.now()
                        }
            return result
        except Exception as e:
            print(f"baostock获取数据失败: {e}")
            return {}
    
    def _get_stock_name_baostock(self, bs_code):
        """获取股票名称"""
        try:
            rs = self._bs.query_stock_basic(bs_code)
            if rs and rs.error_code == '0':
                data = rs.get_data()
                if data is not None and len(data) > 0:
                    return data.iloc[0]['code_name']
            return ""
        except Exception as e:
            print(f"获取股票名称失败: {e}")
            return ""
    
    def get_historical_data_baostock(self, stock_code, days=120, period='daily'):
        """
        使用baostock获取历史K线数据
        period: daily, week, month
        返回标准化的DataFrame（中文列名）
        """
        try:
            self._init_baostock()
            if not self._baostock_initialized:
                return pd.DataFrame()
            
            # 转换周期
            freq_map = {
                'daily': 'd',
                'week': 'w',
                'month': 'm'
            }
            frequency = freq_map.get(period, 'd')
            
            # 代码格式转换
            if stock_code.startswith('6'):
                bs_code = f"sh.{stock_code}"
            elif stock_code.startswith('0') or stock_code.startswith('3'):
                bs_code = f"sz.{stock_code}"
            else:
                bs_code = f"sz.{stock_code}"
            
            end_date = datetime.now().strftime('%Y-%m-%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            
            # 查询历史K线
            rs = self._bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,adjustflag,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag="2"  # 2:前复权, 3:不复权
            )
            
            # 检查返回结果
            if rs is None or rs.error_code != '0':
                # print(f"baostock查询失败: {rs.error_msg if rs else 'Unknown error'}")
                return pd.DataFrame()
            
            data = rs.get_data()
            if data is None or len(data) == 0:
                # print(f"baostock未获取到{stock_code}的数据")
                return pd.DataFrame()
            
            # 标准化DataFrame（转换为中文列名）
            df = self._standardize_dataframe(data, source='baostock')
            
            return df
            
        except Exception as e:
            print(f"baostock获取{stock_code}历史数据失败: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()
    
    def get_realtime_price_akshare(self, stock_codes):
        """
        使用AKShare获取实时行情
        pip install akshare
        """
        try:
            # 获取A股实时行情
            df = ak.stock_zh_a_spot_em()
            df['代码'] = df['代码'].astype(str).str.zfill(6)
            
            result = {}
            for code in stock_codes:
                stock_data = df[df['代码'] == code]
                if not stock_data.empty:
                    row = stock_data.iloc[0]
                    result[code] = {
                        'name': row['名称'],
                        'price': float(row['最新价']),
                        'change_pct': float(row['涨跌幅']),
                        'volume': float(row['成交量']),
                        'turnover': float(row['换手率']) if '换手率' in row else 0,
                        'high': float(row['最高']),
                        'low': float(row['最低']),
                        'open': float(row['开盘']),
                        'prev_close': float(row['昨收']),
                        'amount': float(row['成交额']) if '成交额' in row else 0,
                        'time': datetime.now()
                    }
            return result
        except Exception as e:
            print(f"AKShare获取数据失败: {e}")
            return {}
    
    def get_realtime_price_tushare(self, stock_codes, token):
        """
        使用Tushare获取实时行情（需要注册token）
        pip install tushare
        """
        try:
            import tushare as ts
            ts.set_token(token)
            pro = ts.pro_api()
            
            # 获取实时行情
            df = ts.get_realtime_quotes(stock_codes)
            result = {}
            for _, row in df.iterrows():
                code = row['code']
                result[code] = {
                    'name': row['name'],
                    'price': float(row['price']),
                    'change_pct': float(row['pre_close']) if row['pre_close'] != '0' else 0,
                    'volume': float(row['volume']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'open': float(row['open']),
                    'prev_close': float(row['pre_close']),
                    'time': datetime.now()
                }
            return result
        except Exception as e:
            print(f"Tushare获取数据失败: {e}")
            return {}
    
    def get_historical_data(self, stock_code, days=120, period='daily', source='baostock'):
        """
        获取历史K线数据
        source: akshare, baostock
        返回标准化的DataFrame（包含中文列名：开盘、收盘、最高、最低、成交量、成交额、涨跌幅）
        """
        if source == 'baostock':
            return self.get_historical_data_baostock(stock_code, days, period)
        else:
            return self.get_historical_data_akshare(stock_code, days, period)
    
    def get_historical_data_akshare(self, stock_code, days=120, period='daily'):
        """使用AKShare获取历史K线数据，返回标准化的DataFrame"""
        try:
            # 使用AKShare获取历史数据
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
            
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period=period,
                start_date=start_date,
                end_date=end_date,
                adjust='qfq'
            )
            
            if df is not None and not df.empty:
                # 标准化DataFrame
                df = self._standardize_dataframe(df, source='baostock')
                return df
            return pd.DataFrame()
        except Exception as e:
            print(f"获取{stock_code}历史数据失败: {e}")
            return pd.DataFrame()
    
    def get_batch_historical_data(self, stock_codes, days=60, source='baostock'):
        """批量获取历史数据"""
        results = {}
        for code in stock_codes:
            print(f"正在获取{code}的历史数据...")
            results[code] = self.get_historical_data(code, days, source=source)
            time.sleep(0.5)  # 避免请求过快
        
        # 如果是baostock，完成后关闭连接
        if source == 'baostock':
            self._close_baostock()
        return results
    
    def __del__(self):
        """析构函数，关闭baostock连接"""
        self._close_baostock()