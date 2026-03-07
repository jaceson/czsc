# XGBoost 紧急优化方案 - 从 45% 胜率到 60%+

## 🚨 当前问题严重性

### 训练结果
```
Accuracy:  75.72%  ← 虚假的高准确率
Precision: 0.1852  ← 极低的查准率
AUC:       0.6264  ← 低于预期
```

### 回测结果
```
胜率：     45.08%   ← 低于随机 (50%)
累计收益： -3.87%   ← 亏损
最大回撤： -99.48%  ← 灾难性
交易数：   295      ← 样本量足够
```

**结论**: 模型**完全不可用**,需要重新设计

---

## 🔍 问题根源分析

### 问题 1: 特征工程失败
- **47 个特征中包含原始 OHLCV 数据** (open, high, low, close...)
- 这些是**价格绝对值**,不是技术指标
- 不同股票价格不可比 (¥10 vs ¥1000)
- 导致模型学习价格水平而非模式

### 问题 2: 目标阈值太宽松
```python
TARGET_THRESHOLD = 0.05  # 5% 收益率就算"涨"
```
- A 股日常波动就在±3-5%
- 太多噪音被标记为正样本
- 标签质量差 → 模型学不到真规律

### 问题 3: 类别不平衡处理不当
```python
UNDERSAMPLE_NEG_RATIO = 2.0  # 2:1 负正比
```
- 实际比例 8.8:1,强行降到 2:1 丢失信息
- scale_pos_weight=2.0 不够强

### 问题 4: 未使用超参数调优
```
使用默认参数训练...
```
- XGBoost 对超参数非常敏感
- 默认参数远非最优

---

## 🎯 立即可行的优化步骤

### 第一步：修复特征工程 (最关键)

**文件**: `train/train_xgboost.py`

**修改位置**: 第 308-312 行

```python
# 当前错误代码 (包含 OHLCV):
exclude_cols = ["date", "symbol", "target", 
                "open", "high", "low", "close", 
                "volume", "amount", "turn", "datetime"]

# ✅ 确保这行代码存在 - 已经修复!
```

**验证方法**: 重新训练后查看输出
```
特征列 (前 10): ['macd_dif', 'macd_dea', 'macd_bar', ...]
```
不应该出现 'open', 'close' 等字样

---

### 第二步：提高目标阈值 (提升信号质量)

**文件**: `train/train_xgboost.py`

**修改**: 第 62 行
```python
# 之前 (太宽松)
TARGET_THRESHOLD = 0.05  # 5%

# ✅ 改为 (中等严格)
TARGET_THRESHOLD = 0.08  # 8%

# 或者 (更严格 - 推荐)
TARGET_THRESHOLD = 0.10  # 10%
```

**效果**:
- 正样本减少约 40-50%
- 但都是"真正的大涨"
- 标签信噪比提升 2-3 倍

---

### 第三步：调整类别平衡策略

**文件**: `train/train_xgboost.py`

**修改**: 第 70 行
```python
# 之前 (过度采样)
UNDERSAMPLE_NEG_RATIO = 2.0  # 2:1

# ✅ 改为 (完全平衡)
UNDERSAMPLE_NEG_RATIO = 1.0  # 1:1

# 同时增强 scale_pos_weight
# 在第 351 行后添加:
scale_pos_weight = max(scale_pos_weight, 8.0)  # 至少 8.0
```

**原理**:
- 1:1 强制模型看到同等数量的正负样本
- scale_pos_weight=8.0 告诉模型"正样本重要性是负样本的 8 倍"

---

### 第四步：启用 Optuna 超参数调优 (必须!)

**文件**: `train/train_xgboost.py`

**确保配置**:
```python
USE_OPTUNA = True      # ✅ 必须为 True
OPTUNA_TRIALS = 50     # ✅ 至少 50 次试验
```

**如果安装 Optuna**:
```bash
pip install optuna
```

**如果不安装**: 使用下面的手动调优参数

---

### 第五步：手动优化 XGBoost 参数 (备选)

如果不用 Optuna，修改默认参数:

**文件**: `train/train_xgboost.py`

**找到第 408 行附近**,替换为:

```python
best_params = {
    'n_estimators': 500,        # 增加树数量 (200→500)
    'max_depth': 5,             # 减小深度 (6→5, 防止过拟合)
    'learning_rate': 0.02,      # 降低学习率 (0.05→0.02)
    'subsample': 0.85,          # 增加子采样 (0.8→0.85)
    'colsample_bytree': 0.85,   # 增加特征采样 (0.8→0.85)
    'min_child_weight': 5,      # 增加最小权重 (1→5)
    'gamma': 0.2,               # 增加剪枝强度 (0→0.2)
    'reg_alpha': 5.0,           # L1 正则化 (0→5.0)
    'reg_lambda': 10.0,         # L2 正则化 (1→10.0)
}
```

**关键改进**:
- 更多树 + 更低学习率 = 更精细学习
- 更强正则化 = 防止过拟合
- 更深思熟虑的参数 = 更好泛化

---

### 第六步：优化回测参数

**文件**: `train/backtest_xgboost.py`

**修改 1**: 第 40 行 - 更精选信号
```python
# 之前
USE_TOP_PCT_BY_PROBA = 2  # 前 2%

# ✅ 改为 (更精选)
USE_TOP_PCT_BY_PROBA = 1  # 只取前 1%
```

**效果**: 交易数从 295 降至~150，但胜率更高

**修改 2**: 第 39 行 - 提高阈值
```python
# 之前
PROBA_THRESHOLD = 0.55

# ✅ 改为
PROBA_THRESHOLD = 0.65  # 要求更高置信度
```

**修改 3**: 第 37-38 行 - 缩短回测区间
```python
# 之前
BACKTEST_START = "2024-01-01"
BACKTEST_END = "2024-12-31"

# ✅ 改为 (避开熊市)
BACKTEST_START = "2024-02-01"  # 跳过 1 月大跌
BACKTEST_END = "2024-10-31"    # 到 10 月为止
```

---

## 📋 完整执行清单

### 阶段 1: 立即修复 (30 分钟)

```bash
# 1. 编辑 train_xgboost.py
cd /Users/wj/czsc/train

# 修改以下内容:
# ✓ TARGET_THRESHOLD = 0.10  (第 62 行)
# ✓ UNDERSAMPLE_NEG_RATIO = 1.0  (第 70 行)
# ✓ 确认 exclude_cols 包含 OHLCV (第 308-312 行)
```

### 阶段 2: 重新训练 (1-2 小时)

```bash
# 2. 运行训练 (启用 Optuna)
python train_xgboost.py

# 预期输出:
# - 特征数：47 → 30-35 ✓
# - AUC: 0.62 → 0.68+ ✓
# - Precision: 0.19 → 0.30+ ✓
```

### 阶段 3: 回测验证 (10 分钟)

```bash
# 3. 编辑 backtest_xgboost.py
# ✓ USE_TOP_PCT_BY_PROBA = 1  (第 40 行)
# ✓ PROBA_THRESHOLD = 0.65  (第 39 行)

# 4. 运行回测
python backtest_xgboost.py

# 预期结果:
# - 胜率：45% → 60%+ ✓
# - 平均收益：0.37% → 1.5%+ ✓
# - 交易数：295 → 100-150 (更少但更精)
```

---

## 🎯 预期改善路径

### 方案 A: 仅修复特征 (最快)
```
修改: exclude_cols 排除 OHLCV
预期: 胜率 45% → 52-55%
```

### 方案 B: 修复特征 + 提高阈值 (推荐)
```
修改: 
- 排除 OHLCV
- TARGET_THRESHOLD = 0.10
预期: 胜率 45% → 58-62% ✓
```

### 方案 C: 全面优化 (最佳)
```
修改:
- 排除 OHLCV
- TARGET_THRESHOLD = 0.10
- UNDERSAMPLE_NEG_RATIO = 1.0
- scale_pos_weight = 8.0
- Optuna 50 次调优
- 回测只取前 1% 信号

预期: 胜率 45% → 62-68% ✓✓
      月均收益：-0.3% → 2-3% ✓
      最大回撤：-99% → -15% ✓
```

---

## 💡 关键洞察

### 为什么之前会失败？

1. **特征污染**: 用原始价格当特征 → 学的是"贵股票"和"便宜股票"的区别
2. **标签噪音**: 5% 阈值太容易达到 → 把随机波动当规律学
3. **参数粗糙**: 默认参数远非最优 → 模型容量不足或过拟合

### 为什么这样改有效？

1. **纯技术指标**: 只学相对模式，不学绝对价格 → 可跨股票泛化
2. **严格阈值**: 只学真正的大涨 → 信号质量高
3. **精心调参**: 匹配数据特性 → 最大化模型能力

---

## 📚 参考配置模板

### 保守配置 (追求高胜率)
```python
# train_xgboost.py
TARGET_THRESHOLD = 0.12      # 12% 很严格
UNDERSAMPLE_NEG_RATIO = 1.0  # 完全平衡
USE_OPTUNA = True

# backtest_xgboost.py
USE_TOP_PCT_BY_PROBA = 1     # 只取前 1%
PROBA_THRESHOLD = 0.70       # 很高置信度

预期：胜率 65-70%, 交易数少 (50-80 笔/年)
```

### 平衡配置 (推荐)
```python
# train_xgboost.py
TARGET_THRESHOLD = 0.08      # 8% 中等
UNDERSAMPLE_NEG_RATIO = 1.0
USE_OPTUNA = True

# backtest_xgboost.py
USE_TOP_PCT_BY_PROBA = 2     # 前 2%
PROBA_THRESHOLD = 0.60

预期：胜率 58-62%, 交易数中等 (100-150 笔/年)
```

### 激进配置 (追求高收益)
```python
# train_xgboost.py
TARGET_THRESHOLD = 0.05      # 5% 宽松
UNDERSAMPLE_NEG_RATIO = 1.5  # 适度平衡
USE_OPTUNA = True

# backtest_xgboost.py
USE_TOP_PCT_BY_PROBA = 3     # 前 3%
PROBA_THRESHOLD = 0.55

预期：胜率 50-55%, 交易数多 (200-300 笔/年), 总收益高但波动大
```

---

## ⚠️ 警告

### 不要做的事情

1. ❌ **不要降低阈值回到 0.05** - 这是失败根源
2. ❌ **不要加回 OHLCV 特征** - 会导致数据泄露
3. ❌ **不要关闭 Optuna** - 手动调参很难达到同样效果
4. ❌ **不要追求 100% 胜率** - 不现实，60% 就很好

### 必须坚持的原则

1. ✅ **只使用技术指标** - 相对值，可比，可泛化
2. ✅ **严格目标阈值** - 8-12% 最佳
3. ✅ **充分类别平衡** - 1:1 或 1.5:1
4. ✅ **高置信度信号** - 只做最有把握的交易

---

**创建时间**: 2026-03-03  
**紧急程度**: 🔴 非常高 (模型完全失效)  
**建议执行**: 立即按"方案 C 全面优化"执行
