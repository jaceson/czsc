class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, initial_capital=1000000):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.positions = {}  # {stock_code: {'shares': int, 'avg_price': float, 'entry_date': date}}
        self.trades = []     # 交易记录
        self.daily_values = []  # 每日净值
        self.returns = []     # 每日收益
        
    def execute_trade(self, date, stock_code, action, price, shares, reason=''):
        """执行交易"""
        cost = price * shares
        if action == 'BUY':
            if cost <= self.capital:
                self.capital -= cost
                
                # 判断是首次建仓还是加仓
                is_add_position = stock_code in self.positions
                
                if is_add_position:
                    # 加仓
                    old_shares = self.positions[stock_code]['shares']
                    old_avg_price = self.positions[stock_code]['avg_price']
                    total_shares = old_shares + shares
                    total_cost = old_avg_price * old_shares + cost
                    self.positions[stock_code]['shares'] = total_shares
                    self.positions[stock_code]['avg_price'] = total_cost / total_shares
                    
                    print(f"【加仓】{date} | {stock_code} | 价格:{price:.2f} | "
                          f"数量:{shares}股 | 金额:{cost:.2f}元 | "
                          f"原持仓:{old_shares}股@{old_avg_price:.2f} | "
                          f"新持仓:{total_shares}股@{self.positions[stock_code]['avg_price']:.2f} | "
                          f"原因:{reason}")
                else:
                    # 首次建仓
                    self.positions[stock_code] = {
                        'shares': shares,
                        'avg_price': price,
                        'entry_date': date,
                        'reason': reason
                    }
                    
                    print(f"【买入】{date} | {stock_code} | 价格:{price:.2f} | "
                          f"数量:{shares}股 | 金额:{cost:.2f}元 | "
                          f"可用资金:{self.capital:.2f}元 | 原因:{reason}")
                
                self.trades.append({
                    'date': date,
                    'stock_code': stock_code,
                    'action': 'BUY',
                    'price': price,
                    'shares': shares,
                    'cost': cost,
                    'reason': reason
                })

                return True
            else:
                print(f"【买入失败】{date} | {stock_code} | 资金不足: "
                      f"需要{cost:.2f}元, 可用{self.capital:.2f}元")
                return False
                
        elif action == 'SELL':
            if stock_code in self.positions and self.positions[stock_code]['shares'] >= shares:
                avg_price = self.positions[stock_code]['avg_price']
                profit = (price - avg_price) * shares
                profit_pct = (price - avg_price) / avg_price
                
                self.capital += cost
                remaining_shares = self.positions[stock_code]['shares'] - shares
                self.positions[stock_code]['shares'] = remaining_shares
                
                # 打印卖出日志
                profit_icon = "✓" if profit > 0 else "✗"
                print(f"【卖出】{date} | {stock_code} | 价格:{price:.2f} | "
                      f"数量:{shares}股 | 金额:{cost:.2f}元 | "
                      f"成本价:{avg_price:.2f} | {profit_icon}盈亏:{profit:.2f}元({profit_pct:+.2%}) | "
                      f"剩余持仓:{remaining_shares}股")
                
                self.trades.append({
                    'date': date,
                    'stock_code': stock_code,
                    'action': 'SELL',
                    'price': price,
                    'shares': shares,
                    'proceeds': cost,
                    'profit': profit,
                    'profit_pct': profit_pct
                })

                # 清仓
                if remaining_shares == 0:
                    del self.positions[stock_code]
                    print(f"【清仓】{date} | {stock_code} | 已完全平仓")
                
                return True
            else:
                if stock_code not in self.positions:
                    print(f"【卖出失败】{date} | {stock_code} | 无持仓记录")
                else:
                    print(f"【卖出失败】{date} | {stock_code} | 持仓不足: "
                          f"需要{shares}股, 实际{self.positions[stock_code]['shares']}股")
                return False
    
    def get_current_value(self, current_prices):
        """计算当前总资产"""
        position_value = 0
        for code, pos in self.positions.items():
            if code in current_prices:
                position_value += current_prices[code] * pos['shares']
        return self.capital + position_value
    
    def get_portfolio_summary(self, current_prices):
        """获取持仓摘要"""
        summary = []
        for code, pos in self.positions.items():
            current_price = current_prices.get(code, pos['avg_price'])
            pnl = (current_price - pos['avg_price']) * pos['shares']
            pnl_pct = (current_price - pos['avg_price']) / pos['avg_price']
            summary.append({
                'code': code,
                'shares': pos['shares'],
                'avg_price': pos['avg_price'],
                'current_price': current_price,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'entry_date': pos['entry_date']
            })
        return summary
    
    def get_performance_metrics(self):
        """计算业绩指标"""
        if len(self.daily_values) < 2:
            return {}
        
        series = pd.Series(self.daily_values)
        returns = series.pct_change().dropna()
        
        total_return = (series.iloc[-1] - self.initial_capital) / self.initial_capital
        
        # 年化收益率
        days = len(self.daily_values)
        annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0
        
        # 夏普比率
        risk_free_rate = 0.03
        sharpe = (returns.mean() * 252 - risk_free_rate) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # 最大回撤
        cummax = series.expanding().max()
        drawdown = (series - cummax) / cummax
        max_drawdown = drawdown.min()
        
        # 胜率
        winning_trades = [t for t in self.trades if t.get('profit', 0) > 0 and t['action'] == 'SELL']
        total_sells = [t for t in self.trades if t['action'] == 'SELL']
        win_rate = len(winning_trades) / len(total_sells) if total_sells else 0
        
        return {
            'initial_capital': self.initial_capital,
            'final_value': series.iloc[-1] if len(series) > 0 else self.initial_capital,
            'total_return': total_return,
            'total_return_pct': total_return * 100,
            'annual_return': annual_return,
            'annual_return_pct': annual_return * 100,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'max_drawdown_pct': max_drawdown * 100,
            'win_rate': win_rate,
            'win_rate_pct': win_rate * 100,
            'total_trades': len(self.trades),
            'buy_trades': len([t for t in self.trades if t['action'] == 'BUY']),
            'sell_trades': len([t for t in self.trades if t['action'] == 'SELL'])
        }