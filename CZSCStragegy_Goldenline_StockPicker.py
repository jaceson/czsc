# coding: utf-8
"""
黄金分割线策略 - 选股版本
基于 CZSCStragegy_Goldenline_BacktraderV2.py 改造

功能：
1. 分析所有股票的缠论笔划分
2. 识别黄金分割买入点
3. 输出第二天可建仓、可补仓、可卖出的股票清单
4. 保存为JSON文件
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import baostock as bs
from czsc_daily_util import *


class GoldenLineStockPicker:
    """
    黄金分割线选股策略
    """
    
    def __init__(self, threshold=1.7, klines=10, min_angle=12, stake=40000):
        """
        初始化选股策略
        
        参数:
            threshold: 涨幅阈值，默认 1.7（上涨需超过 70%）
            klines: 最小上涨K线数，默认 10
            min_angle: 最小角度，默认 12
            stake: 每次买入金额，默认 40000
        """
        self.threshold = threshold
        self.klines = klines
        self.min_angle = min_angle
        self.stake = stake
        
        # 股票数据缓存
        self.stock_data_cache = {}
        
        # 分析结果
        self.buy_signals = []      # 建仓信号
        self.add_signals = []      # 补仓信号
        self.sell_signals = []     # 卖出信号
        
        # 持仓记录（用于补仓和卖出判断）
        self.positions = {}  # {symbol: {'buy_price': xxx, 'buy_date': xxx, 'add_count': xxx}}
    
    def load_stock_data(self, symbol, start_date='2020-01-01'):
        """
        加载单只股票的历史数据
        """
        try:
            end_date = get_latest_trade_date()
            df = get_stock_pd(symbol, start_date, end_date, 'd')
            if df is None or len(df) < 70:
                return None
            
            # 获取最新数据
            df['date'] = pd.to_datetime(df['date'])
            df.sort_values('date', inplace=True)
            
            return df
        except Exception as e:
            print(f"加载 {symbol} 数据失败: {e}")
            return None
    
    def analyze_stock(self, symbol, df):
        """
        分析单只股票，识别买卖信号
        
        返回:
            {
                'symbol': 股票代码,
                'buy_signal': 是否可建仓,
                'add_signal': 是否可补仓,
                'sell_signal': 是否可卖出,
                'golden_val': 黄金分割位,
                'current_price': 当前价格,
                'position_info': 持仓信息（如有）
            }
        """
        result = {
            'symbol': symbol,
            'buy_signal': False,
            'add_signal': False,
            'sell_signal': False,
            'golden_val': None,
            'current_price': df['close'].iloc[-1],
            'current_date': df['date'].iloc[-1].strftime('%Y-%m-%d'),
            'position_info': None,
            'bi_info': None,
            'reason': ''
        }
        
        # 获取持仓信息
        position_info = self.positions.get(symbol, None)
        if position_info:
            result['position_info'] = position_info
        
        # 构建RawBar列表
        bars = []
        for i, row in df.iterrows():
            bar = RawBar(
                symbol=symbol,
                id=i,
                freq=Freq.D,
                open=row['open'],
                dt=row['date'],
                close=row['close'],
                high=row['high'],
                low=row['low'],
                vol=row['volume'],
                amount=1
            )
            bars.append(bar)
        
        # 创建CZSC对象
        try:
            c = CZSC(bars, get_signals=None)
            if not c or not c.bi_list:
                result['reason'] = '无法识别笔'
                return result
        except Exception as e:
            result['reason'] = f'缠论分析失败: {e}'
            return result
        
        bi_list = c.bi_list
        zs_list = get_zs_seq(bi_list)
        ubi_fxs = c.ubi_fxs
        
        result['bi_info'] = {
            'bi_count': len(bi_list),
            'last_bi': self._get_last_bi_info(bi_list)
        }
        
        # 1. 检查买入信号（建仓）
        buy_signal = self._check_buy_signal(symbol, bi_list, zs_list, df)
        if buy_signal:
            result['buy_signal'] = True
            result['golden_val'] = buy_signal.get('golden_min_val')
            result['reason'] = f"黄金分割位: {result['golden_val']:.2f}"
        
        # 2. 检查补仓信号（已有持仓且价格在黄金分割位以下出现底分型）
        if position_info and not buy_signal:
            add_signal = self._check_add_signal(symbol, bi_list, zs_list, ubi_fxs, df, position_info)
            if add_signal:
                result['add_signal'] = True
                result['golden_val'] = add_signal.get('golden_min_val')
                result['reason'] = f"补仓信号, 黄金分割位: {result['golden_val']:.2f}"
        
        # 3. 检查卖出信号（有持仓且满足卖出条件）
        if position_info:
            sell_signal = self._check_sell_signal(symbol, bi_list, df, position_info)
            if sell_signal:
                result['sell_signal'] = True
                result['reason'] = sell_signal.get('reason', '卖出信号')
        
        return result
    
    def _get_last_bi_info(self, bi_list):
        """获取最后一笔的信息"""
        if len(bi_list) < 3:
            return None
        
        last_bi = bi_list[-1]
        if last_bi.fx_a.fx > last_bi.fx_b.fx:
            last_bi = bi_list[-2]
        
        return {
            'start_price': last_bi.fx_a.fx,
            'end_price': last_bi.fx_b.fx,
            'is_up': last_bi.fx_a.fx < last_bi.fx_b.fx,
            'start_date': last_bi.fx_a.dt.strftime('%Y-%m-%d'),
            'end_date': last_bi.fx_b.dt.strftime('%Y-%m-%d')
        }
    
    def _check_buy_signal(self, symbol, bi_list, zs_list, df):
        """
        检查黄金分割买入信号（建仓）
        """
        if len(bi_list) < 3:
            return None
        
        # 获取最后一笔上涨笔
        last_up_bi = self._get_last_up_bi(bi_list)
        if not last_up_bi:
            return None
        
        up_start_fx = last_up_bi.fx_a
        up_end_fx = last_up_bi.fx_b
        
        # 查找上涨线段的起始笔
        pre_bi = None
        last_up_idx = bi_list.index(last_up_bi)
        
        for i in range(last_up_idx - 1, -1, -1):
            current_bi = bi_list[i]
            if current_bi.fx_a.fx > current_bi.fx_b.fx:
                if current_bi.fx_a.fx > up_end_fx.fx:
                    return None
                continue
            
            if current_bi.fx_b.fx > up_end_fx.fx:
                return None
            
            if pre_bi and current_bi.fx_a.fx > pre_bi.fx_a.fx:
                break
            
            pre_bi = current_bi
        
        if pre_bi is None:
            pre_bi = last_up_bi
            pre_down_bi = None
        else:
            try:
                pre_idx = bi_list.index(pre_bi)
                pre_down_bi = bi_list[pre_idx - 1] if pre_idx > 0 else None
            except ValueError:
                pre_down_bi = None
        
        # 判断是否在中枢内，使用中枢最低点
        start_fx_for_golden = up_start_fx
        if len(zs_list) > 0:
            last_zs = zs_list[-1]
            if last_zs.is_valid:
                in_zs = (last_zs.sdt <= pre_bi.fx_a.dt <= last_zs.edt) or \
                        (pre_down_bi and last_zs.sdt <= pre_down_bi.fx_a.dt <= last_zs.edt)
                
                if in_zs:
                    for z_bi in last_zs.bis:
                        for fx in [z_bi.fx_a, z_bi.fx_b]:
                            if fx.fx < start_fx_for_golden.fx and fx.dt < start_fx_for_golden.dt:
                                start_fx_for_golden = fx
        
        return self._check_golden_setup(start_fx_for_golden, up_end_fx, df)
    
    def _get_last_up_bi(self, bi_list):
        """获取最后一笔上涨笔"""
        if len(bi_list) < 3:
            return None
        last_bi = bi_list[-1]
        if last_bi.fx_a.fx > last_bi.fx_b.fx:
            last_bi = bi_list[-2]
        return last_bi
    
    def  _check_golden_setup(self, fx_a, fx_b, df):
        """
        检查黄金分割买入条件
        """
        if fx_a.fx * self.threshold > fx_b.fx:
            return None
        
        fx_a_date = fx_a.dt.strftime("%Y-%m-%d")
        fx_b_date = fx_b.dt.strftime("%Y-%m-%d")
        
        up_kline_num = days_trade_delta(df, fx_a_date, fx_b_date)
        if up_kline_num < self.klines:
            return None
        
        angle = bi_angle(df, fx_a, fx_b)
        if angle < self.min_angle:
            return None
        
        sqrt_value = sqrt_val(fx_a.fx, fx_b.fx)
        golden_low_value = gold_val_low(fx_a.fx, fx_b.fx)
        golden_min_val = min(sqrt_value, golden_low_value)
        
        close_price = df['close'].iloc[-1]
        if close_price <= golden_min_val:
            return {
                'golden_min_val': golden_min_val,
                'sqrt_val': sqrt_value,
                'golden_low_val': golden_low_value,
                'start_price': fx_a.fx,
                'end_price': fx_b.fx
            }
        
        return None
    
    def _check_add_signal(self, symbol, bi_list, zs_list, ubi_fxs, df, position_info):
        """
        检查补仓信号：价格在黄金分割位以下 + 出现底分型
        """
        # 获取黄金分割位
        golden_setup = self._check_buy_signal(symbol, bi_list, zs_list, df)
        if not golden_setup:
            return None
        
        golden_min_val = golden_setup.get('golden_min_val')
        current_price = df['close'].iloc[-1]
        
        # 条件1：价格在黄金分割位以下
        if current_price > golden_min_val:
            return None
        
        # 条件2：检测底分型
        if self._check_bottom_fractal(ubi_fxs, df):
            return {
                'golden_min_val': golden_min_val,
                'current_price': current_price,
                'buy_price': position_info.get('buy_price')
            }
        
        return None
    
    def _check_bottom_fractal(self, ubi_fxs, df):
        """
        检测底分型
        """
        if len(ubi_fxs) <= 0:
            return False
        
        last_fx = ubi_fxs[-1]
        if last_fx.mark == Mark.G:
            return False
        
        if last_fx is not None and len(df) >= 2:
            fx_dt = last_fx.dt
            if hasattr(fx_dt, 'date'):
                fx_dt = fx_dt.date()
            
            current_date = df['date'].iloc[-2].date()
            if hasattr(current_date, 'date'):
                current_date = current_date.date()
            
            if fx_dt == current_date:
                return True
        
        return False
    
    def _check_sell_signal(self, symbol, bi_list, df, position_info):
        """
        检查卖出信号：
        1. 形成新的上涨一笔
        2. 超过最大持有天数（60天）
        """
        if len(bi_list) < 3:
            return None
        
        bought_bi_count = position_info.get('bought_bi_count', 0)
        buy_date = position_info.get('buy_date')
        
        # 条件1：形成新的上涨一笔
        if len(bi_list) > bought_bi_count:
            for i in range(bought_bi_count, len(bi_list)):
                bi = bi_list[i]
                if bi.fx_a.fx < bi.fx_b.fx:
                    return {'reason': '上涨一笔形成'}
        
        # 条件2：超过最大持有天数（60天）
        if buy_date:
            hold_days = (df['date'].iloc[-1] - buy_date).days
            if hold_days >= 60:
                return {'reason': f'达到最大持有天数60天'}
        
        return None
    
    def update_positions(self, analysis_results):
        """
        根据分析结果更新持仓记录
        """
        new_positions = {}
        
        for result in analysis_results:
            symbol = result['symbol']
            
            # 如果有卖出信号，清除持仓
            if result.get('sell_signal'):
                continue
            
            # 如果有建仓信号或已有持仓，更新持仓
            if result.get('buy_signal') or result.get('add_signal') or symbol in self.positions:
                old_pos = self.positions.get(symbol, {})
                
                new_pos = {
                    'buy_price': old_pos.get('buy_price', result.get('current_price', 0)),
                    'buy_date': old_pos.get('buy_date', datetime.now().date()),
                    'add_count': old_pos.get('add_count', 0) + (1 if result.get('add_signal') else 0),
                    'bought_bi_count': old_pos.get('bought_bi_count', 0)
                }
                
                # 更新bought_bi_count（需要一个方式获取当前bi数量，这里简化处理）
                if result.get('bi_info') and result['bi_info'].get('bi_count'):
                    new_pos['bought_bi_count'] = result['bi_info']['bi_count']
                
                new_positions[symbol] = new_pos
        
        self.positions = new_positions
    
    def run_picker(self, all_symbols, start_date='2020-01-01', output_file='stock_pick_result.json'):
        """
        运行选股策略
        
        参数:
            all_symbols: 股票列表
            start_date: 起始日期
            output_file: 输出JSON文件路径
        """
        print("=" * 80)
        print("黄金分割线选股策略 - 开始分析")
        print("=" * 80)
        print(f"分析股票数量: {len(all_symbols)}")
        print(f"起始日期: {start_date}")
        print(f"当前日期: {datetime.now().strftime('%Y-%m-%d')}")
        print("=" * 80)
        
        results = []
        processed = 0
        
        for symbol in all_symbols:
            processed += 1
            if processed % 100 == 0:
                print(f"进度: {processed}/{len(all_symbols)}")
            
            # 加载数据
            df = self.load_stock_data(symbol, start_date)
            if df is None:
                continue
            
            # 分析股票
            result = self.analyze_stock(symbol, df)
            results.append(result)
        
        # 更新持仓记录
        self.update_positions(results)
        
        # 分类汇总
        buy_list = [r for r in results if r.get('buy_signal')]
        add_list = [r for r in results if r.get('add_signal')]
        sell_list = [r for r in results if r.get('sell_signal')]
        
        # 构建输出结果
        output_result = {
            'analysis_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'next_trade_date': self._get_next_trade_day(),
            'total_analyzed': len(results),
            'summary': {
                'buy_count': len(buy_list),
                'add_count': len(add_list),
                'sell_count': len(sell_list)
            },
            'buy_signals': [
                {
                    'symbol': r['symbol'],
                    'current_price': r['current_price'],
                    'golden_val': r['golden_val'],
                    'reason': r['reason'],
                    'suggested_amount': self.stake
                }
                for r in buy_list
            ],
            'add_signals': [
                {
                    'symbol': r['symbol'],
                    'current_price': r['current_price'],
                    'golden_val': r['golden_val'],
                    'reason': r['reason'],
                    'buy_price': r.get('position_info', {}).get('buy_price', 0),
                    'add_count': r.get('position_info', {}).get('add_count', 0),
                    'suggested_amount': self.stake
                }
                for r in add_list
            ],
            'sell_signals': [
                {
                    'symbol': r['symbol'],
                    'current_price': r['current_price'],
                    'reason': r['reason'],
                    'buy_price': r.get('position_info', {}).get('buy_price', 0),
                    'hold_days': (datetime.now().date() - r.get('position_info', {}).get('buy_date', datetime.now().date())).days if r.get('position_info') else 0
                }
                for r in sell_list
            ],
            'positions': [
                {
                    'symbol': symbol,
                    'buy_price': pos['buy_price'],
                    'buy_date': pos['buy_date'].strftime('%Y-%m-%d') if hasattr(pos['buy_date'], 'strftime') else str(pos['buy_date']),
                    'add_count': pos['add_count'],
                    'current_price': next((r['current_price'] for r in results if r['symbol'] == symbol), 0),
                    'profit_pct': (next((r['current_price'] for r in results if r['symbol'] == symbol), 0) - pos['buy_price']) / pos['buy_price'] * 100 if pos['buy_price'] > 0 else 0
                }
                for symbol, pos in self.positions.items()
            ]
        }
        
        # 保存到JSON文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_result, f, ensure_ascii=False, indent=2)
        
        # 打印汇总信息
        self._print_summary(output_result)
        
        print(f"\n结果已保存到: {output_file}")
        
        return output_result
    
    def _get_next_trade_day(self):
        """
        获取下一个交易日
        """
        today = datetime.now().date()
        # 简单处理：跳过周六周日
        next_day = today + timedelta(days=1)
        while next_day.weekday() >= 5:  # 5=周六, 6=周日
            next_day += timedelta(days=1)
        return next_day.strftime('%Y-%m-%d')
    
    def _print_summary(self, output_result):
        """
        打印汇总信息
        """
        print("\n" + "=" * 80)
        print("选股结果汇总")
        print("=" * 80)
        
        print(f"\n分析日期: {output_result['analysis_date']}")
        print(f"下一个交易日: {output_result['next_trade_date']}")
        print(f"分析股票总数: {output_result['total_analyzed']}")
        
        print(f"\n📈 建仓信号 ({output_result['summary']['buy_count']}只):")
        for item in output_result['buy_signals'][:20]:  # 只显示前20只
            print(f"  {item['symbol']}: 价格={item['current_price']:.2f}, 黄金位={item['golden_val']:.2f}")
        if len(output_result['buy_signals']) > 20:
            print(f"  ... 共{len(output_result['buy_signals'])}只")
        
        print(f"\n💰 补仓信号 ({output_result['summary']['add_count']}只):")
        for item in output_result['add_signals'][:20]:
            print(f"  {item['symbol']}: 价格={item['current_price']:.2f}, 已补仓{item['add_count']}次")
        if len(output_result['add_signals']) > 20:
            print(f"  ... 共{len(output_result['add_signals'])}只")
        
        print(f"\n📉 卖出信号 ({output_result['summary']['sell_count']}只):")
        for item in output_result['sell_signals'][:20]:
            print(f"  {item['symbol']}: 价格={item['current_price']:.2f}, 原因={item['reason']}")
        if len(output_result['sell_signals']) > 20:
            print(f"  ... 共{len(output_result['sell_signals'])}只")
        
        print("\n" + "=" * 80)


def main():
    """主函数"""
    print("=" * 80)
    print("黄金分割线策略 - 选股版本")
    print("=" * 80)

    # 登录baostock
    lg = bs.login()
    print('login respond error_code:' + lg.error_code)
    print('login respond  error_msg:' + lg.error_msg)
        
    # 获取股票列表
    try:
        all_symbols = get_daily_symbols()
        print(f"获取到 {len(all_symbols)} 只股票")
    except Exception as e:
        print(f"获取股票列表失败: {e}")
        print("使用测试列表...")
        all_symbols = ['000001', '000002', '600000', '600004', '600006', '600007', '600008', '600009', '600010']
    
    # 可选：限制分析数量（测试用）
    # all_symbols = all_symbols[:100]
    
    # 创建选股策略实例
    picker = GoldenLineStockPicker(
        threshold=1.7,
        klines=10,
        min_angle=12,
        stake=40000
    )
    
    # 运行选股
    start_date = "2024-01-01"
    output_file = "stock_pick_result.json"
    
    result = picker.run_picker(
        all_symbols=all_symbols,
        start_date=start_date,
        output_file=output_file
    )
    
    print("\n选股分析完成！")
    # 登出系统
    bs.logout()

if __name__ == '__main__':
    main()