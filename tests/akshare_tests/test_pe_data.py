"""
测试沪深300 PE数据获取途径
"""
import akshare as ak
import pandas as pd
import sys

print(f"akshare 版本: {ak.__version__}")
print("=" * 60)

# ── 方案1：乐咕乐股 stock_index_pe_lg ──────────────────────
print("\n【方案1】stock_index_pe_lg（乐咕乐股）")
try:
    df1 = ak.stock_index_pe_lg(symbol="沪深300")
    print(f"  字段: {list(df1.columns)}")
    print(f"  行数: {len(df1)}")
    print(f"  日期范围: {df1.iloc[0, 0]} ~ {df1.iloc[-1, 0]}")
    print(df1.tail(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

# ── 方案2：中证指数官网 stock_zh_index_value_csindex ────────
print("\n【方案2】stock_zh_index_value_csindex（中证指数）")
try:
    import inspect
    print("  函数签名:", inspect.signature(ak.stock_zh_index_value_csindex))
    df2 = ak.stock_zh_index_value_csindex(symbol="000300")
    print(f"  字段: {list(df2.columns)}")
    print(f"  行数: {len(df2)}")
    print(df2.tail(3).to_string())
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("结论：")
print("  - 若方案1可用：直接获取沪深300历史PE（从约2010年起）")
print("  - 若方案2可用：中证官方数据，权威性更高")
print("  - 若均不可用：需手动导入PE数据，或使用代理指标")

