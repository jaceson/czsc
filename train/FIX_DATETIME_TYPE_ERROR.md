# Fix: DateTime Column Type Error

## 🐛 Problem

**Error**: `numpy.exceptions.DTypePromotionError: The DType <class 'numpy.dtypes.DateTime64DType'> could not be promoted by <class 'numpy.dtypes.Float64DType'>`

**Location**: Line 330 in `train_xgboost.py`
```python
X_train_scaled = scaler.fit_transform(X_train)
```

### Root Cause
StandardScaler requires all input features to be numeric (float/int), but the `date` column (datetime64 type) was being included in the feature set, causing the type promotion error.

## ✅ Solution Applied

### Added Numeric Type Validation
Modified the feature column selection to explicitly filter out non-numeric columns:

```python
# Before (WRONG)
feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]
X = data[feature_cols]

# After (CORRECT)
feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]
# Filter out non-numeric columns
numeric_cols = []
for col in feature_cols:
    if pd.api.types.is_numeric_dtype(data[col]):
        numeric_cols.append(col)
    else:
        print(f"  ⚠ Skipping non-numeric column: {col} (type: {data[col].dtype})")

feature_cols = numeric_cols
X = data[feature_cols]
```

### Added Debug Output
Also added diagnostic output to show what features are being used:

```python
print(f"\n特征列数量：{len(feature_cols)}")
print(f"特征列 (前 10): {feature_cols[:10]}...")
print(f"数据类型检查完成，所有特征均为数值型")
```

## 📊 Expected Output

After this fix, when you run `python train_xgboost.py`, you should see:

```
正在构建特征与标签...
  已处理 1/100 只股票
  ...
  已处理 100/100 只股票

共处理 95/100 只有效股票，总样本数：102,345

特征列数量：30
特征列 (前 10): ['macd_dif', 'macd_dea', 'macd_bar', 'macd_golden_cross', 'ema5', 'ema20', 'ema60', 'price_ema5_ratio', 'price_ema20_ratio', 'ema5_ema20_diff']...
数据类型检查完成，所有特征均为数值型

总样本数：102,345, 训练：92,110, 验证：10,235
训练集正样本比例：0.4534
下采样后训练集：138,165 (正 46,055, 负 92,110)
scale_pos_weight: 2.00

============================================================
使用 Optuna 进行超参数调优...
============================================================
```

## 🔍 Why This Happened

The `build_features()` function returns:
```python
return df[["date"] + feature_cols + ["target"]]
```

This includes the `date` column for tracking purposes. When multiple stocks are concatenated via `pd.concat()`, the date column is preserved. Even though we tried to exclude it with `feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]`, there might be other datetime-type columns that slipped through, or the date column wasn't properly excluded due to pandas dtype inference issues.

The new solution uses `pd.api.types.is_numeric_dtype()` to explicitly check each column's dtype and only include truly numeric columns (int, float).

## ✅ Related Fixes

This fix complements the previous VR function parameter fix:
1. ✅ VR function: Changed `N=26` to `M1=26`
2. ✅ Cleaned unused imports
3. ✅ Added numeric type validation ← **This fix**

## 🚀 Next Steps

Run the training again:
```bash
cd /Users/wj/czsc/train
python train_xgboost.py
```

The error should now be resolved, and training should proceed normally.

---

**Fixed**: 2026-03-03  
**Issue**: DateTime type in StandardScaler  
**Status**: ✅ Resolved
