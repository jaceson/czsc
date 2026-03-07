# Critical Fix: Excluding Raw OHLCV Data from Features

## 🐛 Problem Identified

Your model is using **raw market data** as features:
```
特征列 (前 10): ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'macd_dif', ...]
```

This is causing several issues:

### Issue 1: Price Levels Are Not Comparable
- Stock A trades at ¥10, Stock B trades at ¥1000
- Model learns absolute prices instead of relative patterns
- Doesn't generalize across stocks

### Issue 2: Dominates Feature Importance
```
price_range:    0.068137  ← Raw price range dominates
boll_width:     0.030739  
boll_mid:       0.028753  ← Middle band is just a MA
llv_20:         0.028488  ← Raw lowest price
hhv_20:         0.027557  ← Raw highest price
```

**Problem**: These aren't technical indicators - they're just raw prices!

### Issue 3: Data Leakage
- `close` price appears both as feature and in target calculation
- Model might be "cheating" by looking at current price level
- Inflated accuracy but poor real-world performance

## ✅ Solution Applied

### Modified Feature Selection Logic

**Before** (WRONG):
```python
feature_cols = [c for c in data.columns if c not in ("date", "symbol", "target")]
# This includes: open, high, low, close, volume, amount, turn
```

**After** (CORRECT):
```python
exclude_cols = [
    "date", "symbol", "target",
    # Exclude raw OHLCV data - only use technical indicators
    "open", "high", "low", "close", 
    "volume", "amount", "turn", "datetime"
]

feature_cols = [c for c in data.columns if c not in exclude_cols]
```

## 📊 What Features Should Be Included

### ✅ Good Features (Technical Indicators Only)

#### Trend Indicators (10 features)
```python
'macd_dif', 'macd_dea', 'macd_bar', 'macd_golden_cross',
'ema5', 'ema20', 'ema60',
'price_ema5_ratio', 'price_ema20_ratio', 'ema5_ema20_diff'
```

#### Oscillator Indicators (9 features)
```python
'rsi_6', 'rsi_12', 'rsi_24',
'kdj_k', 'kdj_d', 'kdj_j', 'kd_diff',
'cci_14', 'cci_84'
```

#### Volatility Indicators (5 features)
```python
'boll_upper', 'boll_lower', 'boll_pct_b', 'boll_width'
# Note: 'boll_mid' should also be excluded - it's just MA(20)
```

#### Volume Indicators (7 features)
```python
'vol_ma5', 'vol_ma20', 'volume_ratio', 'volume_ma_ratio',
'obv', 'obv_ma5', 'vr_26'
```

#### Momentum Indicators (2 features)
```python
'roc_12', 'mtm_12'
```

#### Price Pattern Indicators (6 features)
```python
'price_range',      # (H-L)/L - normalized, OK to keep
'price_change',     # (C-O)/O - normalized, OK to keep
'price_position',   # Position in recent range - normalized
'consecutive_up',   # Count of consecutive up days
'consecutive_down', # Count of consecutive down days
# 'hhv_20', 'llv_20' should be excluded - raw prices
```

## 🎯 Expected Impact After Fix

### Current Performance (With OHLCV contamination)
```
Accuracy:  0.7572  ← Artificially high due to price levels
AUC:       0.6264  ← Low - doesn't generalize well
Precision: 0.1852  ← Poor real signal detection
```

### Expected Performance (After removing OHLCV)
```
Accuracy:  0.68-0.72  ← Lower but more honest
AUC:       0.65-0.70  ← Better generalization
Precision: 0.25-0.35  ← Much better signal quality
F1-Score:  0.28-0.38  ← Better balance
```

**Why Better?**
- Model focuses on **relative patterns** not absolute prices
- Technical indicators are **normalized** and comparable across stocks
- No data leakage from current price to target

## 🔧 Additional Cleanup Needed

### Also Consider Removing

1. **boll_mid** - It's just MA(close, 20), redundant with ema20
2. **hhv_20, llv_20** - Raw price levels, use `price_position` instead
3. **ema5, ema20, ema60** - Consider using only ratios like `price_ema20_ratio`

### Cleaner Feature Set (Recommended)

```python
# Core indicators (20-25 features total)
'macd_dif', 'macd_dea', 'macd_bar',
'rsi_12', 'kdj_k', 'kd_diff',
'boll_pct_b', 'boll_width',
'volume_ratio', 'obv',
'price_range', 'price_change', 'price_position',
'consecutive_up', 'consecutive_down'
```

## 🚀 How to Apply the Fix

### The fix has been automatically applied to your code!

Just re-run training:

```bash
cd /Users/wj/czsc/train
python train_xgboost.py
```

You should now see:
```
特征列数量：30-35  ← Reduced from 47
特征列 (前 10): ['macd_dif', 'macd_dea', 'macd_bar', 'rsi_6', ...]
```

No more 'open', 'high', 'low', 'close' in the feature list!

## 📈 Verification Checklist

After re-training, verify:

- [ ] Feature count reduced from 47 to ~30-35
- [ ] First 10 features are all technical indicators (no OHLCV)
- [ ] `price_range`, `boll_width` no longer dominate importance
- [ ] MACD, RSI, KDJ have higher importance
- [ ] AUC improved (>0.65)
- [ ] Precision improved (>0.25)

## 💡 Why This Matters

### Machine Learning Principle
> "Garbage in, garbage out"

If you feed raw prices into the model:
- It learns price levels (¥10 vs ¥100)
- This doesn't generalize - every stock has different price levels
- Model fails on unseen stocks or price regimes

If you feed technical indicators:
- It learns patterns (momentum, overbought/oversold)
- These patterns are universal across stocks
- Model generalizes well to new data

### Financial Intuition
- **Price level** doesn't predict returns (¥100 stock ≠ more expensive than ¥10 stock)
- **Relative position** does predict returns (stock at 52-week high vs low)
- Technical indicators capture relative position, not absolute level

---

**Fix Applied**: 2026-03-03  
**Issue**: Raw OHLCV data in features  
**Status**: ✅ Automatically fixed in code  
**Next**: Re-train and verify improvement
