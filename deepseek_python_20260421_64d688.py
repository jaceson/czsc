# second_buy_backtest_fixed.py
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import baostock as bs

from czsc import CzscTrader, CZSC
from czsc.objects import RawBar, Freq, Signal
from czsc.signals import (
    cxt_second_bs_V230320,  # 官方二买信号
    tas_macd_bs1_V230411,   # MACD背驰信号
    tas_ma_system_V230513   # 均线系统信号
)


class SecondBuyDetector:
    """30分钟二买点检测器 - 使用CZSC官方信号"""
    
    def __init__(self, symbol: str, symbol_name: str = ""):
        self.symbol = symbol
        self.symbol_name = symbol_name or symbol
        self._logged_in = False
        
    def _login(self) -> bool:
        if not self._logged_in:
            lg = bs.login()
            if lg.error_code != '0':
                print(f"baostock登录失败: {lg.error_msg}")
                return False
            self._logged_in = True
        return True
    
    def _logout(self):
        if self._logged_in:
            bs.logout()
            self._logged_in = False
    
    def _convert_code(self, code: str) -> str:
        code = code.strip().upper()
        if code.startswith('SH.') or code.startswith('SZ.'):
            return code.lower()
        if '.SH' in code:
            return f"sh.{code.replace('.SH', '')}"
        if '.SZ' in code:
            return f"sz.{code.replace('.SZ', '')}"
        if code.isdigit():
            if code.startswith('6'):
                return f"sh.{code}"
            else:
                return f"sz.{code}"
        return code.lower()
    
    def _freq_str_to_enum(self, freq: str) -> Freq:
        freq_map = {'5': Freq.F5, '15': Freq.F15, '30': Freq.F30, '60': Freq.F60, 'D': Freq.D}
        return freq_map.get(freq, Freq.F30)
    
    def fetch_kline_data(self, start_date: str, end_date: str, freq: str = '30') -> List[RawBar]:
        if not self._login():
            return []
        
        bs_code = self._convert_code(self.symbol)
        print(f"  获取数据: {bs_code}, {freq}分钟, {start_date} 至 {end_date}")
        
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,time,code,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency=freq,
                adjustflag="3"
            )
            
            if rs.error_code != '0':
                print(f"获取数据失败: {rs.error_msg}")
                return []
            
            bars = []
            idx = 0
            while rs.next():
                row = rs.get_row_data()
                date = row[0]
                time = row[1]
                dt_str = f"{date} {time[:2]}:{time[2:4]}:{time[4:6]}"
                dt = pd.to_datetime(dt_str)
                
                bar = RawBar(
                    symbol=self.symbol,
                    id=idx,
                    dt=dt,
                    freq=self._freq_str_to_enum(freq),
                    open=float(row[3]),
                    close=float(row[6]),
                    high=float(row[4]),
                    low=float(row[5]),
                    vol=float(row[7]),
                    amount=float(row[8])
                )
                bars.append(bar)
                idx += 1
            
            bars.sort(key=lambda x: x.dt)
            for i, bar in enumerate(bars):
                bar.id = i
                
            print(f"  ✓ 获取 {len(bars)} 根K线")
            return bars
            
        except Exception as e:
            print(f"获取数据异常: {e}")
            return []
    
    def get_signals_at_position(self, c: CZSC) -> Dict:
        """
        获取当前位置的所有CZSC官方信号
        
        这里使用框架内置的信号函数，而不是自己编逻辑
        """
        signals = {}
        
        # 1. 二买/二卖信号（核心！）
        try:
            second_bs = cxt_second_bs_V230320(c)
            signals.update(second_bs)
        except Exception as e:
            pass
        
        # 2. MACD背驰信号（识别一买）
        try:
            macd_bs = tas_macd_bs1_V230411(c)
            signals.update(macd_bs)
        except Exception as e:
            pass
        
        # 3. 均线系统信号（确认趋势）
        try:
            ma_system = tas_ma_system_V230513(c)
            signals.update(ma_system)
        except Exception as e:
            pass
        
        return signals
    
    def is_second_buy(self, signals: Dict) -> Tuple[bool, str]:
        """
        根据官方信号判断是否为二买
        
        关键：信号格式是 "k1_k2_k3_v1_v2_v3_score"
        使用“任意”通配符进行模糊匹配[citation:6]
        """
        
        # 遍历所有信号，查找二买信号
        for key, value in signals.items():
            # 检查是否是二买信号
            # 官方二买信号格式示例：'15分钟_D1SMA21_BS2辅助V230320_二买_任意_任意_0'
            if '二买' in str(value) or ('BS2辅助' in key and '二买' in str(value)):
                return True, f"检测到二买信号: {key}={value}"
            
            # 辅助判断：有底背驰 + 均线多头排列，也可能是二买区域
            has_divergence = False
            has_bullish = False
            
            if '底背驰' in str(value):
                has_divergence = True
            if '多头排列' in str(value):
                has_bullish = True
            
            if has_divergence and has_bullish:
                return True, f"底背驰+多头排列，二买区域: {key}={value}"
        
        return False, ""
    
    def detect_second_buy_points(self, bars: List[RawBar]) -> List[Dict]:
        """检测所有二买点"""
        if len(bars) < 60:
            print(f"数据不足，需要至少60根K线，当前{len(bars)}根")
            return []
        
        second_buy_points = []
        total = len(bars)
        
        print(f"\n开始检测二买点，共{total}根K线...")
        print("（使用CZSC官方信号：cxt_second_bs_V230320）")
        
        # 从第60根开始，确保有足够数据构建笔和线段
        for i in range(60, total):
            history_bars = bars[:i+1]
            
            try:
                # 创建CZSC对象
                c = CZSC(history_bars)
                
                # 获取官方信号
                signals = self.get_signals_at_position(c)
                
                # 判断是否为二买
                is_buy, reason = self.is_second_buy(signals)
                
                if is_buy:
                    point = {
                        "time": bars[i].dt,
                        "price": bars[i].close,
                        "low": bars[i].low,
                        "high": bars[i].high,
                        "volume": bars[i].vol,
                        "reason": reason,
                        "signals": signals,
                        "index": i
                    }
                    second_buy_points.append(point)
                    
                    # 实时打印
                    time_str = bars[i].dt.strftime('%Y-%m-%d %H:%M')
                    print(f"  📍 二买点: {time_str} @ {bars[i].close:.2f}")
                    print(f"     原因: {reason[:80]}...")
                    
            except Exception as e:
                # 单个点失败不影响整体
                continue
        
        return second_buy_points
    
    def generate_report(self, points: List[Dict], start_date: str, end_date: str):
        """生成报告"""
        print(f"\n{'='*70}")
        print(f"📊 {self.symbol_name} ({self.symbol}) 30分钟二买点回测报告")
        print(f"   回测区间: {start_date} 至 {end_date}")
        print(f"{'='*70}")
        
        if not points:
            print("\n❌ 未发现30分钟二买点")
            print("\n可能原因：")
            print("  1. 该时间段内确实没有符合缠论二买定义的走势")
            print("  2. 需要更多K线数据来构建完整的笔结构（建议至少120根）")
            print("  3. 可以尝试使用更短周期（如15分钟）重新检测")
            return
        
        print(f"\n✅ 共发现 {len(points)} 个30分钟二买点\n")
        
        print(f"{'序号':<4} {'时间':<20} {'价格':<10} {'成交量(手)':<12}")
        print("-" * 50)
        
        for i, p in enumerate(points, 1):
            time_str = p['time'].strftime('%Y-%m-%d %H:%M')
            volume = f"{p['volume']/100:.0f}"
            print(f"{i:<4} {time_str:<20} {p['price']:<10.2f} {volume:<12}")
        
        # 导出CSV
        self.export_to_csv(points)
    
    def export_to_csv(self, points: List[Dict], filename: str = None):
        if not points:
            return
        
        if filename is None:
            filename = f"{self.symbol}_second_buy_points.csv"
        
        data = []
        for p in points:
            data.append({
                "时间": p['time'].strftime('%Y-%m-%d %H:%M:%S'),
                "价格": p['price'],
                "最低价": p['low'],
                "最高价": p['high'],
                "成交量": p['volume'],
                "信号原因": p['reason']
            })
        
        df = pd.DataFrame(data)
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"\n✓ 已导出到: {filename}")
    
    def run_backtest(self, start_date: str, end_date: str, freq: str = '30'):
        """运行回测"""
        print(f"\n{'='*70}")
        print(f"🚀 开始回测: {self.symbol_name}")
        print(f"{'='*70}")
        
        # 获取数据（多取一些，确保有足够数据构建笔）
        bars = self.fetch_kline_data(start_date, end_date, freq)
        if len(bars) < 100:
            print("数据不足，至少需要100根K线")
            self._logout()
            return []
        
        # 检测二买点
        points = self.detect_second_buy_points(bars)
        
        # 生成报告
        self.generate_report(points, start_date, end_date)
        
        self._logout()
        return points


# ========== 使用示例 ==========

def analyze_single_stock():
    """分析单只股票"""
    print("\n" + "="*70)
    print("30分钟二买点回测工具")
    print("="*70)
    
    # 输入股票信息
    symbol = input("\n请输入股票代码（如 600519 或 sh.600519）: ").strip()
    name = input("请输入股票名称（可选）: ").strip()
    
    if not name:
        name = symbol
    
    # 输入回测时间范围
    print("\n请输入回测时间范围（格式：YYYY-MM-DD）")
    start_date = input("开始日期（如 2024-01-01）: ").strip()
    end_date = input("结束日期（如 2024-12-31）: ").strip()
    
    if not start_date:
        start_date = "2024-01-01"
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')
    
    # 创建检测器并运行
    detector = SecondBuyDetector(symbol=symbol, symbol_name=name)
    points = detector.run_backtest(start_date, end_date, freq='30')
    
    return points


def batch_analysis():
    """批量分析多只股票"""
    
    # 配置股票列表
    stocks = [
        {"symbol": "sh.600519", "name": "贵州茅台"},
        {"symbol": "sz.000858", "name": "五粮液"},
        {"symbol": "sh.600036", "name": "招商银行"},
    ]
    
    start_date = "2024-01-01"
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    all_results = {}
    
    for stock in stocks:
        print(f"\n{'#'*70}")
        print(f"分析: {stock['name']}")
        print(f"{'#'*70}")
        
        detector = SecondBuyDetector(
            symbol=stock["symbol"],
            symbol_name=stock["name"]
        )
        
        points = detector.run_backtest(start_date, end_date, freq='30')
        all_results[stock["symbol"]] = points
    
    return all_results


def compare_multi_stocks():
    """对比多只股票的二买点数量"""
    
    stocks = [
        {"symbol": "sh.600519", "name": "贵州茅台"},
        {"symbol": "sz.000858", "name": "五粮液"},
        {"symbol": "sh.600036", "name": "招商银行"},
        {"symbol": "sh.601318", "name": "中国平安"},
        {"symbol": "sz.000333", "name": "美的集团"},
    ]
    
    start_date = "2024-01-01"
    end_date = datetime.now().strftime('%Y-%m-%d')
    
    print("\n" + "="*70)
    print("多股票二买点对比分析")
    print(f"回测区间: {start_date} 至 {end_date}")
    print("="*70)
    
    results = []
    
    for stock in stocks:
        detector = SecondBuyDetector(
            symbol=stock["symbol"],
            symbol_name=stock["name"]
        )
        
        bars = detector.fetch_kline_data(start_date, end_date, '30')
        if len(bars) >= 100:
            points = detector.detect_second_buy_points(bars)
            results.append({
                "name": stock["name"],
                "symbol": stock["symbol"],
                "buy_count": len(points),
                "kline_count": len(bars)
            })
        else:
            results.append({
                "name": stock["name"],
                "symbol": stock["symbol"],
                "buy_count": 0,
                "kline_count": len(bars)
            })
        
        detector._logout()
    
    # 打印对比结果
    print(f"\n{'股票名称':<12} {'股票代码':<12} {'二买点数量':<10} {'K线数量':<10}")
    print("-" * 50)
    
    for r in sorted(results, key=lambda x: x['buy_count'], reverse=True):
        print(f"{r['name']:<12} {r['symbol']:<12} {r['buy_count']:<10} {r['kline_count']:<10}")
    
    return results


if __name__ == "__main__":
    print("="*70)
    print("30分钟二买点回测分析工具")
    print("基于CZSC框架 + baostock数据源")
    print("="*70)
    
    print("\n请选择运行模式:")
    print("1. 分析单只股票（输出所有二买点）")
    print("2. 批量分析预设股票列表")
    print("3. 多股票二买点数量对比")
    
    choice = input("\n请输入选项 (1/2/3): ").strip()
    
    if choice == '1':
        analyze_single_stock()
    elif choice == '2':
        batch_analysis()
    elif choice == '3':
        compare_multi_stocks()
    else:
        print("无效选项，运行默认单股票分析")
        analyze_single_stock()