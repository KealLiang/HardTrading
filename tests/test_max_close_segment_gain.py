"""max_close_segment_gain_pct 单元测试。"""

import pandas as pd

from analysis.helper import ladder_chart_helpers as helpers


def test_max_close_segment_gain_pct_basic(monkeypatch):
    """先跌后涨：首尾整体涨幅低，但段涨幅应达标。"""
    df = pd.DataFrame({
        '日期': pd.date_range('2026-01-01', periods=30, freq='B'),
        '收盘': [100.0] * 15 + [140.0] * 15,
        '最高': [100.0] * 30,
        '最低': [100.0] * 30,
    })

    monkeypatch.setattr(helpers, 'get_stock_data_df', lambda code: df.copy())
    helpers.max_close_segment_gain_pct.cache_clear()

    gain = helpers.max_close_segment_gain_pct('sh600000', '20260220', 30)
    assert gain is not None
    assert abs(gain - 40.0) < 1e-6


def test_max_close_segment_gain_pct_insufficient_bars(monkeypatch):
    df = pd.DataFrame({
        '日期': pd.date_range('2026-01-01', periods=10, freq='B'),
        '收盘': [10.0] * 10,
    })
    monkeypatch.setattr(helpers, 'get_stock_data_df', lambda code: df.copy())
    helpers.max_close_segment_gain_pct.cache_clear()

    assert helpers.max_close_segment_gain_pct('sh600000', '20260115', 30) is None
