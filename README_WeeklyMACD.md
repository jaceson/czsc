# 周线MACD背离+金叉选股策略

## 策略说明

这是一个基于周线MACD指标的选股策略，筛选同时满足以下两个条件的股票：

1. **MACD底背离**：周线价格创新低，但MACD（DIF）没有创新低，表明下跌动能减弱
2. **MACD金叉**：最后一个交易日周线MACD出现金叉（DIF上穿DEA），表明短期趋势转强

## 策略逻辑

### MACD底背离检测
- 在最近30周内寻找局部低点
- 比较最近两个低点：
  - 价格：当前低点 < 前一个低点
  - MACD：当前低点的DIF > 前一个低点的DIF
- 满足以上条件则判定为底背离

### MACD金叉检测
- 检查最后一个交易周：
  - 前一周：DIF < DEA
  - 当前周：DIF > DEA
- 满足条件则判定为金叉

## 使用方法

### 1. 运行完整选股策略

```bash
python CZSCStragegy_WeeklyMACDDivergence.py
```

这将：
- 遍历所有股票
- 筛选符合条件的股票
- 输出结果到控制台
- 保存结果到 `data/weekly_macd_divergence_stocks.json`

### 2. 测试单只股票

```bash
python test_weekly_macd.py
```

### 3. 在代码中使用

```python
from CZSCStragegy_WeeklyMACDDivergence import check_weekly_macd_strategy

# 检查单只股票
symbol = "000001.SZ"
is_match, info = check_weekly_macd_strategy(symbol)

if is_match:
    print(f"{symbol} 符合策略条件")
    print(f"日期: {info['last_date']}")
    print(f"收盘价: {info['last_close']}")
    print(f"DIF: {info['last_dif']}, DEA: {info['last_dea']}")
```

## 输出结果

策略会输出符合条件的股票列表，包括：
- 股票代码
- 最后交易日
- 收盘价
- DIF值
- DEA值
- MACD值

结果同时保存为JSON文件，方便后续分析。

## 注意事项

1. **数据要求**：需要至少50周的周线数据才能进行有效分析
2. **计算时间**：全市场扫描可能需要较长时间，建议在非交易时间运行
3. **策略限制**：
   - 仅基于技术指标，不包含基本面分析
   - 需要结合其他分析方法综合判断
   - 历史表现不代表未来收益

## 参数调整

可以在代码中调整以下参数：

- `lookback_period`：背离检测的回看周期（默认30周）
- `start_date`：数据起始日期（默认'2020-01-01'）

## 策略优势

1. **趋势反转信号**：底背离通常预示下跌趋势可能结束
2. **确认信号**：金叉提供趋势转强的确认
3. **周线级别**：过滤短期噪音，关注中长期趋势

## 风险提示

1. 技术指标存在滞后性
2. 背离信号可能失效
3. 需要结合市场环境和其他指标综合判断
4. 建议设置止损位，控制风险
