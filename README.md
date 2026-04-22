# CZSC - 缠中说禅技术分析工具

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue" alt="Python Version">
  <img src="https://img.shields.io/badge/License-Apache%202.0-green" alt="License">
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Platform">
</p>

## 📖 项目简介

CZSC是一个基于**缠中说禅技术分析理论**的专业量化交易工具包，提供完整的股票、期货技术分析解决方案。该项目实现了缠论的核心概念（分型、笔、线段、中枢等），并在此基础上构建了丰富的量化交易策略体系。

项目不仅包含了基础的技术分析功能，还提供了策略回测、实时交易、风险管理等完整的量化交易工具链。

## ✨ 核心特性

### 🔍 技术分析核心
- **缠论完整实现**：分型、笔、线段、中枢识别算法
- **多周期分析**：支持分钟、日线、周线等多时间周期分析
- **可视化展示**：K线图、笔段标记、买卖点标注
- **质量检测**：K线数据质量评估工具

### 🤖 量化交易系统
- **策略框架**：灵活的策略开发框架
- **信号引擎**：丰富的技术指标信号库
- **回测系统**：完整的策略回测和绩效分析
- **实时交易**：支持多种交易接口（QMT、掘金、通达信等）

### 📊 分析工具
- **因子分析**：特征工程和因子有效性检验
- **组合优化**：资产配置和风险控制
- **绩效评估**：夏普比率、最大回撤等关键指标
- **Streamlit组件**：交互式数据分析界面

## 🚀 快速开始

### 环境要求
- Python 3.8+
- 推荐使用虚拟环境

### 安装方式

```bash
# 克隆项目
git clone https://github.com/waditu/czsc.git
cd czsc

# 安装依赖
pip install -r requirements.txt

# 安装czsc包
pip install -e .
```

### 基础使用示例

```python
import czsc
import pandas as pd
from czsc.connectors import research

# 获取股票数据
symbol = "000001.XSHE"
bars = research.get_raw_bars(symbol, freq="日线", sdt="20230101", edt="20240101")

# 创建缠论分析对象
czsc_analyzer = czsc.CZSC(bars)

# 查看分析结果
print(f"识别到 {len(czsc_analyzer.bi_list)} 笔")
print(f"识别到 {len(czsc_analyzer.xd_list)} 线段")
```

## 📁 项目结构

```
czsc/
├── czsc/                   # 核心模块
│   ├── analyze.py          # 缠论分析核心
│   ├── strategies.py       # 策略框架
│   ├── traders/            # 交易器模块
│   ├── signals/            # 信号函数库
│   ├── sensors/            # 传感器模块
│   ├── utils/              # 工具函数
│   └── connectors/         # 数据连接器
├── examples/               # 使用示例
│   ├── animotion/          # 动画演示
│   └── develop/            # 开发示例
├── test/                   # 测试用例
├── docs/                   # 文档
├── data/                   # 数据文件
└── lib/                    # 第三方库
```

## 🎯 主要功能模块

### 1. 缠论分析 (analyze.py)
实现了缠中说禅理论的核心算法：
- 分型识别
- 笔的划分
- 线段识别
- 中枢定位
- 买卖点判断

### 2. 策略框架 (strategies.py)
提供策略开发的基础类：
- `CzscStrategyBase`：策略基类
- 事件驱动的持仓管理
- 多周期信号整合

### 3. 交易器 (traders/)
完整的交易执行系统：
- `CzscTrader`：核心交易器
- 回测和实盘统一接口
- 风险控制机制

### 4. 信号库 (signals/)
丰富的技术信号函数：
- 量价关系信号
- 技术指标信号
- 形态识别信号
- 自定义信号开发

## 📈 策略示例

### 黄金分割策略
```python
# 基于黄金分割点的交易策略
# 条件：上涨笔涨幅>1.7倍，K线数>10根，角度>20度
def is_golden_point(symbol, df, threshold=1.7, klines=10, min_angle=20):
    # 策略逻辑实现
    pass
```

### 笔非多即空策略
```python
# 30分钟笔向上的做多，向下的做空
class LongShortStrategy(czsc.CzscStrategyBase):
    @property
    def positions(self):
        return [
            create_long_position(),
            create_short_position()
        ]
```

## 🛠️ 开发工具

### 数据连接器
支持多种数据源：
- **Tushare**：专业金融数据接口
- **Baostock**：免费股票数据
- **掘金量化**：专业量化平台
- **QMT**：迅投QMT系统

### 可视化工具
- **Echarts**：交互式图表
- **Plotly**：高级图表绘制
- **Matplotlib**：基础图表
- **Streamlit**：Web应用界面

## 📊 性能监控

内置完善的绩效评估体系：
- 收益率统计
- 风险指标计算
- 交易成本分析
- 持仓时间分布
- 胜率和盈亏比

## 🔧 配置说明

### 环境变量
```python
import czsc.envs as envs

# 设置最小笔长度
envs.set_min_bi_len(5)

# 设置最大笔数量
envs.set_max_bi_num(5000)
```

### 参数调优
```python
# 使用Optuna进行参数优化
from czsc.utils.optuna import optuna_study

study = optuna_study(
    objective_func=your_strategy,
    param_space=param_ranges,
    n_trials=100
)
```

## 📚 学习资源

### 文档
- [官方文档](https://czsc.readthedocs.io/)
- [API参考](https://czsc.readthedocs.io/en/latest/api/modules.html)
- [使用教程](./docs/source/学习资料.md)

### 示例代码
```bash
# 查看策略示例
cd examples
cat 30分钟笔非多即空.py

# 运行回测示例
python run_dummy_backtest.py
```

## ⚠️ 重要提醒

### 风险提示
- 本项目仅供**学习研究**使用
- 不构成任何**投资建议**
- 实盘交易风险自负
- 历史回测结果不代表未来表现

### 使用建议
- 建议先在模拟环境中测试
- 充分理解策略逻辑后再考虑实盘
- 控制仓位，做好风险管理
- 定期回顾和优化策略

## 🤝 贡献指南

欢迎提交Issue和Pull Request：

1. Fork项目
2. 创建特性分支
3. 提交更改
4. 发起Pull Request

## 📄 许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证。

## 👥 作者信息

- **作者**：zengbin93
- **邮箱**：zeng_bin8888@163.com
- **创建时间**：2019年10月
- **当前版本**：0.9.62

## 🙏 致谢

感谢缠中说禅先生的技术理论贡献，以及开源社区的支持。

---

<p align="center">
  ⭐ 如果你觉得这个项目有用，请给它一个Star！⭐
</p>

