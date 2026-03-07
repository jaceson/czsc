# -*- coding: utf-8 -*-
"""
调试脚本：检查特征构建和 VR 函数修复
Tests feature building and verifies VR function fix
"""
import os
import sys
import pandas as pd
import numpy as np

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from czsc_daily_util import get_daily_symbols
from czsc_sqlite import get_local_stock_data
from train_xgboost import build_features, MIN_BARS

def test_vr_function():
    """Test VR function with correct M1 parameter"""
    print("=" * 60)
    print("测试 VR 函数参数")
    print("=" * 60)
    
    from lib.MyTT import VR
    C = np.array([10.0, 10.5, 10.3, 10.8, 11.0, 11.2, 11.5, 11.3, 11.8, 12.0])
    V = np.array([1000, 1200, 1100, 1300, 1400, 1500, 1600, 1400, 1700, 1800])
    
    try:
        result = VR(C, V, M1=6)  # Use M1=6 for testing with small sample
        print("✓ VR function works with M1 parameter")
        print("  Result sample:", result[:3])
        return True
    except Exception as e:
        print("✗ VR function failed:", str(e))
        return False

def debug_feature_building():
    """Debug feature building process for first 5 stocks"""
    print("\n" + "=" * 60)
    print("特征构建调试")
    print("=" * 60)
    
    symbols = get_daily_symbols()[:5]
    print("Testing {} stocks | MIN_BARS requirement: {}".format(
        len(symbols), MIN_BARS))
    print("=" * 60)
    
    success_count = 0
    fail_count = 0
    
    for i, symbol in enumerate(symbols):
        print("\n[{}/{}] Stock: {}".format(i+1, len(symbols), symbol))
        print("-" * 60)
        
        try:
            # 1. Get raw data
            df_raw = get_local_stock_data(symbol, start_date="2020-01-01", frequency="d")
            
            if df_raw is None:
                print("  ✗ Data is None")
                fail_count += 1
                continue
            
            print("  ✓ Retrieved {} K-line bars".format(len(df_raw)))
            print("    Date range: {} ~ {}".format(
                df_raw['date'].min(), df_raw['date'].max()))
            
            if len(df_raw) < MIN_BARS:
                print("  ✗ Insufficient bars (need {}, got {})".format(
                    MIN_BARS, len(df_raw)))
                fail_count += 1
                continue
            
            # 2. Check data columns
            print("  Columns: {}".format(list(df_raw.columns)))
            
            # 3. Build features
            df_feat = build_features(df_raw)
            
            if df_feat is None:
                print("  ✗ build_features returned None")
                
                # Diagnose why
                C = df_raw["close"].values.astype(float)
                H = df_raw["high"].values.astype(float)
                L = df_raw["low"].values.astype(float)
                V = df_raw["volume"].values.astype(float)
                
                print("  Data quality check:")
                print("    close NaN count: {}".format(np.isnan(C).sum()))
                print("    high NaN count: {}".format(np.isnan(H).sum()))
                print("    low NaN count: {}".format(np.isnan(L).sum()))
                print("    volume NaN count: {}".format(np.isnan(V).sum()))
                fail_count += 1
                continue
            
            # Success!
            success_count += 1
            print("  ✓ Successfully built {} valid samples".format(len(df_feat)))
            print("    Feature columns: {}".format(len(df_feat.columns) - 3))
            print("    Positive ratio: {:.4f}".format(df_feat['target'].mean()))
            
            feat_cols = [c for c in df_feat.columns if c not in ['date', 'symbol', 'target']]
            print("    Top features: {}...".format(feat_cols[:5]))
            
            # 4. Check NaN situation
            nan_counts = df_feat[feat_cols].isna().sum()
            if nan_counts.any():
                print("  ⚠ Features still have NaN:")
                for col, count in nan_counts[nan_counts > 0].items():
                    print("    {}: {} NaN".format(col, count))
            
        except Exception as e:
            print("  ✗ Error: {}".format(str(e)))
            import traceback
            traceback.print_exc()
            fail_count += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print("Success: {}/{} stocks".format(success_count, len(symbols)))
    print("Failed: {}/{} stocks".format(fail_count, len(symbols)))
    
    if success_count > 0:
        print("\n✓ Feature building is working correctly!")
        print("  You can now run: python train_xgboost.py")
    else:
        print("\n✗ All stocks failed. Please check the errors above.")
    
    print("=" * 60)

if __name__ == "__main__":
    # Test 1: VR function
    vr_ok = test_vr_function()
    
    # Test 2: Full feature building
    if vr_ok:
        debug_feature_building()
    else:
        print("\nSkipping feature building test due to VR failure")
