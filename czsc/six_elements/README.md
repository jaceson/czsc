# 六大环节结合交易系统

本模块实现了一个完整的六大环节结合交易系统，包括：

## 系统架构

### 1. 产业研究 (IndustryResearch)
- 行业景气度分析
- 政策面分析
- 产业链上下游分析
- 行业轮动判断

### 2. 板块人气龙头 (BlockPopularity)
- 板块热度分析
- 人气股识别（多概念叠加）
- 龙头股识别
- 板块轮动判断

### 3. 产业赛道龙头 (TrackLeader)
- 赛道识别
- 龙头筛选
- 成长性分析
- 竞争格局分析

### 4. 前瞻动态PE (ForwardPE)
- 动态PE计算
- PE分位数分析
- PEG分析
- 估值预测

### 5. 情绪周期 (SentimentCycle)
- 市场情绪指标（PSY、VR、BRAR、CR、MFI）
- 恐慌贪婪指数
- 情绪周期阶段识别
- 极端情绪预警

### 6. 图形量价 (PriceVolumePattern)
- K线形态识别
- 成交量分析
- 趋势判断
- 支撑阻力位
- 量价背离

## 快速开始

```python
from czsc.six_elements import SixElementSystem

# 初始化系统
system = SixElementSystem(data_source='akshare')

# 运行完整分析
result = system.run_full_analysis(
    stock_code="600519",
    industry_name="白酒",
    block_name="白酒",
    track_name="白酒",
    market_data=market_data,
    price_data=price_data,
)

# 生成报告
report = system.generate_report(result)
print(report)
```

## 单独使用各模块

### 产业研究

```python
from czsc.six_elements import IndustryResearch

research = IndustryResearch(data_source='akshare')

# 寻找热门行业
hot_industries = research.find_hot_industries(top_n=10)

# 生成行业报告
report = research.get_industry_report("白酒")
```

### 板块人气龙头

```python
from czsc.six_elements import BlockPopularity

block = BlockPopularity(data_source='akshare')

# 寻找多概念叠加股
multi_concept = block.find_multi_concept_stocks(min_blocks=5)

# 寻找热门板块
hot_blocks = block.find_hot_blocks(block_type='concept', top_n=10)
```

### 产业赛道龙头

```python
from czsc.six_elements import TrackLeader

track = TrackLeader(data_source='akshare')

# 寻找高成长赛道
high_growth = track.find_high_growth_tracks(top_n=5)

# 识别赛道龙头
leaders = track.identify_leader("新能源", top_n=5)
```

### 前瞻动态PE

```python
from czsc.six_elements import ForwardPE

pe = ForwardPE(data_source='akshare')

# 计算前瞻PE
forward_pe = pe.calculate_forward_pe("600519", expected_growth=0.15)

# 寻找低估股票
undervalued = pe.find_undervalued_stocks(["600519", "000858", "000568"])
```

### 情绪周期

```python
from czsc.six_elements import SentimentCycle

sentiment = SentimentCycle()

# 计算情绪评分
result = sentiment.calculate_sentiment_score(market_data)

# 识别情绪阶段
stage = sentiment.identify_sentiment_stage(result['total_score'])
```

### 图形量价

```python
from czsc.six_elements import PriceVolumePattern

pv = PriceVolumePattern()

# 识别K线形态
patterns = pv.identify_kline_patterns(opens, highs, lows, closes)

# 分析量价关系
volume_price = pv.analyze_volume_price(closes, volumes)
```

## 综合评分机制

系统会对每个环节独立评分（0-100分），然后加权平均计算综合评分：

- 产业研究：15%
- 板块人气龙头：20%
- 产业赛道龙头：20%
- 前瞻动态PE：15%
- 情绪周期：15%
- 图形量价：15%

根据综合评分，系统会给出投资建议：

- 80分以上：强烈推荐
- 65-80分：推荐
- 50-65分：中性
- 35-50分：谨慎
- 35分以下：不推荐

## 运行示例

```bash
cd /Users/jack/workspace/czsc
python examples/six_elements_example.py
```

## 依赖项

- pandas
- numpy
- akshare (可选)
- baostock (可选)
- ta-lib (可选)
- loguru
