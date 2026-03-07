# XGBoost Training Results Analysis & Optimization

## 📊 Current Results Summary

```
Accuracy:  0.7572  ✓ Good
AUC:       0.6264  ⚠️ Below target (need 0.65+)
Precision: 0.1852  ❌ Very low (only 19% accurate for rising predictions)
Recall:    0.3424  ⚠️ Low (missing 66% of actual rises)
F1-Score:  0.2404  ❌ Poor balance
```

### Class Distribution
- **下跌/平**: 7,832 samples (88.8%)
- **上涨**: 990 samples (11.2%)
- **Ratio**: 8.8:1 (severe imbalance)

## 🔍 Problem Diagnosis

### Issue 1: Severe Class Imbalance
Despite using `scale_pos_weight`, the model still favors the majority class.

**Evidence**: 
- Precision for "上涨" is only 0.19
- Model predicts "下跌/平" 81% of the time but should be more balanced

### Issue 2: Feature Importance Mismatch
Top features are dominated by price range and Bollinger Bands:
```
price_range:        0.0681  ← Too dominant
boll_width:         0.0307
boll_mid:           0.0288
llv_20:             0.0285
macd_golden_cross:  0.0280
```

**Problem**: Traditional indicators (MACD, RSI, KDJ) have lower importance than expected.

### Issue 3: Threshold Too Lenient
`TARGET_THRESHOLD = 0.05` (5% return) might be too easy to achieve, creating noisy labels.

## ✅ Optimization Solutions

### Solution 1: Increase Target Threshold (Recommended)

**Change**: Make the prediction target more strict

```python
# In train_xgboost.py
TARGET_THRESHOLD = 0.08  # Was 0.05 (5% → 8%)
# or even stricter:
TARGET_THRESHOLD = 0.10  # 10% return threshold
```

**Why**: 
- Fewer positive samples but higher quality
- Clearer signal for the model to learn
- Reduces label noise

**Expected Impact**:
- Better precision (fewer false positives)
- Lower recall (but that's OK - we want quality over quantity)
- Higher AUC

### Solution 2: Adjust Class Imbalance Handling

**Current**: 
```python
UNDERSAMPLE_NEG_RATIO = 2.0  # 2:1 negative:positive
```

**Try More Aggressive Undersampling**:
```python
UNDERSAMPLE_NEG_RATIO = 1.0  # 1:1 perfectly balanced
# or
UNDERSAMPLE_NEG_RATIO = 1.5  # 1.5:1 moderately balanced
```

**Why**: 
- Forces model to see more positive samples
- Reduces majority class dominance

### Solution 3: Tune scale_pos_weight

**Current**: Automatic calculation based on class ratio

**Manual Override**:
```python
SCALE_POS_WEIGHT = True  # Keep automatic
# But you can also try manual values:
# Add this line after line 340:
scale_pos_weight = 5.0  # Experiment with higher values
```

**Suggested Values to Test**: 3.0, 5.0, 8.0, 10.0

### Solution 4: Feature Engineering Improvements

#### A. Remove Redundant Features
The top feature `price_range` dominates but may not generalize well.

Consider removing or reducing:
```python
# In build_features(), comment out:
# df["price_range"] = (H - L) / (L + 1e-10)
```

#### B. Create Interaction Features
Add combinations of important indicators:

```python
# Add to build_features()
df['macd_rsi_interaction'] = df['macd_dif'] * df['rsi_12']
df['boll_volume'] = df['boll_pct_b'] * df['volume_ratio']
df['trend_momentum'] = df['ema5_ema20_diff'] * df['roc_12']
```

### Solution 5: Hyperparameter Tuning (Most Impact)

**If using Optuna**, adjust the search space:

```python
def objective(trial, ...):
    param = {
        'n_estimators': trial.suggest_int('n_estimators', 200, 800),  # Increased
        'max_depth': trial.suggest_int('max_depth', 3, 8),  # Reduced from 10
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.2, log=True),  # Reduced
        'subsample': trial.suggest_float('subsample', 0.7, 1.0),  # Increased
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.7, 1.0),
        'min_child_weight': trial.suggest_int('min_child_weight', 2, 10),  # Increased
        'gamma': trial.suggest_float('gamma', 0.1, 0.5),  # Increased regularization
        'reg_alpha': trial.suggest_float('reg_alpha', 1, 20, log=True),  # Increased
        'reg_lambda': trial.suggest_float('reg_lambda', 5, 20, log=True),  # Increased
        'scale_pos_weight': scale_pos_weight,
        ...
    }
```

**Key Changes**:
- Deeper trees (more capacity)
- Lower learning rate (more careful learning)
- Higher regularization (prevent overfitting)

### Solution 6: Prediction Threshold Adjustment

Instead of changing training, adjust the prediction threshold in backtest:

```python
# In backtest_xgboost.py
PROBA_THRESHOLD = 0.65  # Was 0.55 (require higher confidence)
# or
USE_TOP_PCT_BY_PROBA = 1  # Only top 1% most confident predictions
```

## 🎯 Recommended Action Plan

### Phase 1: Quick Wins (Try First)

1. **Increase TARGET_THRESHOLD**:
   ```python
   TARGET_THRESHOLD = 0.08  # 5% → 8%
   ```
   
2. **More Aggressive Undersampling**:
   ```python
   UNDERSAMPLE_NEG_RATIO = 1.0  # 2:1 → 1:1
   ```

3. **Retrain and Compare**:
   ```bash
   python train_xgboost.py
   python backtest_xgboost.py
   ```

**Expected Improvement**:
- Precision: 0.19 → 0.25-0.30
- Recall: 0.34 → 0.30-0.35 (slight drop OK)
- AUC: 0.62 → 0.65+

### Phase 2: If Phase 1 Not Enough

4. **Manual scale_pos_weight**:
   ```python
   # After line 340 in train_xgboost.py, add:
   scale_pos_weight = max(scale_pos_weight, 5.0)  # Ensure minimum weight
   ```

5. **Enable Feature Weights** (already implemented):
   ```python
   FEATURE_WEIGHTS = {
       'macd_dif': 1.5,
       'macd_dea': 1.3,
       'rsi_12': 1.4,
       'boll_pct_b': 1.5,
   }
   ```

### Phase 3: Advanced Optimization

6. **Feature Engineering**: Add interaction terms
7. **Hyperparameter Search Space**: Expand Optuna ranges
8. **Ensemble Methods**: Train multiple models and vote

## 📈 Expected Results After Optimization

| Metric | Current | After Phase 1 | Target |
|--------|---------|---------------|--------|
| Accuracy | 0.7572 | 0.70-0.75 | 0.65+ |
| AUC | 0.6264 | **0.65-0.70** | 0.65+ |
| Precision (上涨) | 0.1852 | **0.25-0.35** | 0.30+ |
| Recall (上涨) | 0.3424 | 0.30-0.40 | 0.35+ |
| F1-Score | 0.2404 | **0.27-0.37** | 0.30+ |

## 🚀 Immediate Next Steps

### Step 1: Modify Configuration
Edit `train_xgboost.py`:

```python
# Line ~60
TARGET_THRESHOLD = 0.08  # Changed from 0.05

# Line ~70
UNDERSAMPLE_NEG_RATIO = 1.0  # Changed from 2.0
```

### Step 2: Retrain
```bash
cd /Users/wj/czsc/train
python train_xgboost.py
```

### Step 3: Evaluate
Check if metrics improved:
- Is AUC > 0.65?
- Is Precision > 0.25?
- Is the model more balanced?

### Step 4: Backtest
```bash
python backtest_xgboost.py
```

Compare win rate with previous version.

## 💡 Key Insights

1. **High accuracy ≠ Good model**: Your 75% accuracy is misleading due to class imbalance
2. **Focus on AUC and Precision**: These better reflect true model performance
3. **Quality over Quantity**: Better to predict fewer signals with higher confidence
4. **Iterative Process**: Expect to run 3-5 iterations to find optimal config

---

**Analysis Date**: 2026-03-03  
**Status**: ⚠️ Needs Optimization  
**Priority**: Increase TARGET_THRESHOLD first
