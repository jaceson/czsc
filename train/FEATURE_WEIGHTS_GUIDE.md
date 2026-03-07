# 特征权重配置指南

## 📊 什么是特征权重？

特征权重允许你为不同的技术指标设置不同的重要性级别。权重越高的特征，在模型训练中的影响力越大。

### 为什么要使用权重？

1. **领域知识应用**：根据技术分析经验，某些指标（如 MACD、RSI）可能更重要
2. **平衡特征重要性**：如果模型过于依赖某些特征，可以降低它们的权重
3. **实验优化**：尝试不同的权重组合，找到最佳配置

## ⚙️ 配置方法

### 位置
在 `train_xgboost.py` 文件开头部分（第 73-96 行左右）

### 基本语法

```python
FEATURE_WEIGHTS = {
    '特征名': 权重值,
    ...
}
```

### 示例配置

当前默认配置：

```python
FEATURE_WEIGHTS = {
    # 趋势指标权重
    'macd_dif': 1.5,      # MACD DIF 线 - 权重最高，最重要
    'macd_dea': 1.3,      # MACD DEA 线
    'macd_bar': 1.2,      # MACD 柱状图
    
    # 摆动指标权重
    'rsi_12': 1.4,        # RSI(12) - 较重要
    'kdj_k': 1.2,         # KDJ K 线
    'kd_diff': 1.3,       # K-D 差值
    
    # 波动率指标权重
    'boll_pct_b': 1.5,    # 布林带%B - 权重最高
    'boll_width': 1.3,    # 布林带宽度
    
    # 成交量指标权重
    'volume_ratio': 1.2,  # 成交量比率
    'obv': 1.1,           # OBV 能量潮
}
```

## 🎯 权重值说明

| 权重值 | 含义 | 使用场景 |
|--------|------|----------|
| **1.0** | 基准权重 | 不特别调整（默认） |
| **> 1.0** | 增强权重 | 认为该特征更重要 |
| **< 1.0** | 降低权重 | 认为该特征不太重要 |
| **2.0** | 双倍权重 | 非常重要，影响力翻倍 |
| **0.5** | 减半权重 | 不太重要，影响力减半 |

### 权重效果示例

假设原始特征值为 `[1, 2, 3]`：
- 权重 1.0 → `[1.0, 2.0, 3.0]`（不变）
- 权重 1.5 → `[1.5, 3.0, 4.5]`（增强 50%）
- 权重 2.0 → `[2.0, 4.0, 6.0]`（增强 100%）
- 权重 0.5 → `[0.5, 1.0, 1.5]`（减弱 50%）

## 🔧 常用配置方案

### 方案 1：均衡配置（推荐新手）
```python
FEATURE_WEIGHTS = None  # 所有特征权重相等
```

### 方案 2：趋势跟踪策略
```python
FEATURE_WEIGHTS = {
    'macd_dif': 2.0,      # MACD 最重要
    'macd_dea': 1.8,
    'ema5': 1.5,
    'ema20': 1.3,
    'price_ema5_ratio': 1.4,
}
```

### 方案 3：超买超卖策略
```python
FEATURE_WEIGHTS = {
    'rsi_12': 2.0,        # RSI 最重要
    'kdj_k': 1.8,
    'kdj_d': 1.6,
    'kdj_j': 1.5,
    'boll_pct_b': 1.7,    # 布林带位置
}
```

### 方案 4：波动率策略
```python
FEATURE_WEIGHTS = {
    'boll_width': 2.0,    # 布林带宽度最重要
    'boll_pct_b': 1.8,
    'price_range': 1.5,
    'macd_bar': 1.3,
}
```

### 方案 5：成交量策略
```python
FEATURE_WEIGHTS = {
    'volume_ratio': 2.0,  # 成交量比率最重要
    'obv': 1.8,
    'vr_26': 1.6,
    'volume_ma_ratio': 1.5,
}
```

## 📈 完整特征列表

可用的特征名称（共 30+ 个）：

### 趋势指标 (11 个)
```python
'macd_dif', 'macd_dea', 'macd_bar', 'macd_golden_cross',
'ema5', 'ema20', 'ema60',
'price_ema5_ratio', 'price_ema20_ratio', 'ema5_ema20_diff'
```

### 摆动指标 (9 个)
```python
'rsi_6', 'rsi_12', 'rsi_24',
'kdj_k', 'kdj_d', 'kdj_j', 'kd_diff',
'cci_14', 'cci_84'
```

### 波动率指标 (5 个)
```python
'boll_upper', 'boll_mid', 'boll_lower', 'boll_pct_b', 'boll_width'
```

### 成交量指标 (7 个)
```python
'vol_ma5', 'vol_ma20', 'volume_ratio', 'volume_ma_ratio',
'obv', 'obv_ma5', 'vr_26'
```

### 动量指标 (2 个)
```python
'roc_12', 'mtm_12'
```

### 价格形态 (6 个)
```python
'price_range', 'price_change', 'hhv_20', 'llv_20',
'price_position', 'consecutive_up', 'consecutive_down'
```

## 🚀 使用步骤

### 1. 编辑配置文件
打开 `train_xgboost.py`，找到 FEATURE_WEIGHTS 配置部分

### 2. 选择或自定义权重
- 使用上述预设方案之一，或
- 根据自己的分析自定义权重

### 3. 运行训练
```bash
cd /Users/wj/czsc/train
python train_xgboost.py
```

### 4. 查看应用结果
训练输出会显示应用的权重：

```
应用特征权重...
  ✓ 已应用权重的特征：macd_dif(×1.5), macd_dea(×1.3), rsi_12(×1.4), boll_pct_b(×1.5)...
```

## 📊 效果对比

### 测试不同配置

建议进行对比实验：

**实验 1：无权重 baseline**
```python
FEATURE_WEIGHTS = None
```

**实验 2：轻度加权**
```python
FEATURE_WEIGHTS = {
    'macd_dif': 1.3,
    'rsi_12': 1.3,
    'boll_pct_b': 1.3,
}
```

**实验 3：重度加权**
```python
FEATURE_WEIGHTS = {
    'macd_dif': 2.0,
    'rsi_12': 2.0,
    'boll_pct_b': 2.0,
}
```

### 对比指标
比较不同配置下的：
- Accuracy（准确率）
- AUC（ROC 曲线下面积）
- Precision（精确率）
- Recall（召回率）
- F1-Score
- **回测胜率**（最重要！）

## 💡 最佳实践建议

### ✅ DO（推荐）
1. **从 None 开始**：先用等权重跑 baseline
2. **逐步调整**：每次只调整 3-5 个特征的权重
3. **小幅度调整**：权重范围建议在 0.8-2.0 之间
4. **记录实验**：保存每次的配置和结果
5. **验证回测**：训练集好不代表回测好，一定要回测验证

### ❌ DON'T（避免）
1. **不要过度加权**：避免权重超过 3.0
2. **不要加权太多特征**：最好只加权 5-10 个关键特征
3. **不要盲目调整**：基于特征重要性分析或领域知识
4. **不要忘记归一化**：权重会在 StandardScaler 之后应用

## 🔍 高级技巧

### 技巧 1：基于特征重要性调整
1. 先训练一个无权重模型
2. 查看输出的"特征重要性 Top 10"
3. 对重要性高但你觉得不够的特征增加权重
4. 对重要性低但你认为重要的特征适度增加权重

### 技巧 2：网格搜索权重
```python
# 创建多个配置文件测试
test_weights = [1.0, 1.2, 1.5, 1.8, 2.0]
for w in test_weights:
    FEATURE_WEIGHTS = {'macd_dif': w}
    # 运行训练并记录结果
```

### 技巧 3：分组加权
```python
# 按指标类型分组加权
trend_weight = 1.5   # 所有趋势指标
oscillator_weight = 1.3  # 所有摆动指标
volume_weight = 1.2  # 所有成交量指标

FEATURE_WEIGHTS = {
    'macd_dif': trend_weight,
    'macd_dea': trend_weight,
    'rsi_12': oscillator_weight,
    'kdj_k': oscillator_weight,
    'volume_ratio': volume_weight,
}
```

## 📚 相关文档

- `FINAL_STATUS.md` - 完整训练指南
- `OPTIMIZATION_GUIDE.md` - 优化指南
- `README_QUICKSTART.md` - 快速开始

---

**更新时间**: 2026-03-03  
**版本**: v2.0 with Feature Weights  
**状态**: ✅ 功能已实现并测试
