"""leader_morphology 形态筛选单元测试。"""

from unittest.mock import patch

import pandas as pd
import pytest

from analysis.helper.leader_morphology import (
    LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
    LEADER_MORPHOLOGY_MODE_HEAD_TAIL,
    build_leader_morphology_config,
    calc_window_bottom_to_high_change,
    check_leader_morphology,
    clear_leader_morphology_cache,
)


@pytest.fixture
def morphology_config():
    return build_leader_morphology_config(
        period_days_long=30,
        period_days_very_long=60,
        head_tail_min_change=(30.0, 37.0),
        bottom_to_high_change_range=((25.0, 35.0), (32.0, 42.0)),
        second_wave_min_range=(95.0, 105.0),
        bottom_to_high_high_risk_period_days=120,
        bottom_to_high_high_risk_max_change=250.0,
    )


def _call(config, **kwargs):
    defaults = dict(
        stock_code="sh600000",
        market_type="main",
        long_period_change=35.0,
        end_date_yyyymmdd="20260707",
        config=config,
        mode=LEADER_MORPHOLOGY_MODE_HEAD_TAIL,
    )
    defaults.update(kwargs)
    return check_leader_morphology(**defaults)


def test_no_end_date_returns_false(morphology_config):
    assert not _call(morphology_config, end_date_yyyymmdd=None)


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
def test_head_tail_condition1_pass(mock_ma, mock_sw, morphology_config):
    assert _call(morphology_config, long_period_change=30.0)
    mock_ma.assert_called_once()
    mock_sw.assert_called_once()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
def test_head_tail_condition1_fail_below_threshold(mock_ma, _mock_sw, morphology_config):
    assert not _call(morphology_config, long_period_change=29.9)
    mock_ma.assert_not_called()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=False)
def test_head_tail_condition1_fail_ma_not_rising(_mock_ma, _mock_sw, morphology_config):
    assert not _call(morphology_config, long_period_change=35.0)


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=True)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=False)
def test_condition2_pass_without_condition1(_mock_ma, _mock_sw, morphology_config):
    assert _call(morphology_config, long_period_change=0.0)


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
def test_head_tail_non_main_threshold(_mock_ma, mock_sw, morphology_config):
    assert not _call(morphology_config, market_type="gem", long_period_change=36.0)
    assert _call(morphology_config, market_type="gem", long_period_change=37.0)
    mock_sw.assert_called()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
@patch("analysis.helper.leader_morphology.calc_window_bottom_to_high_change", return_value=30.0)
def test_bottom_to_high_passes_in_range(mock_calc, mock_ma, _mock_sw, morphology_config):
    assert _call(
        morphology_config,
        mode=LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
        long_period_change=5.0,
    )
    mock_calc.assert_called_once_with("sh600000", "20260707", 30)
    mock_ma.assert_called_once()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
@patch("analysis.helper.leader_morphology.calc_window_bottom_to_high_change", return_value=24.9)
def test_bottom_to_high_fails_below_range(_mock_calc, mock_ma, _mock_sw, morphology_config):
    assert not _call(
        morphology_config,
        mode=LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
    )
    mock_ma.assert_not_called()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
@patch("analysis.helper.leader_morphology.calc_window_bottom_to_high_change", return_value=35.1)
def test_bottom_to_high_fails_above_range(_mock_calc, mock_ma, _mock_sw, morphology_config):
    assert not _call(
        morphology_config,
        mode=LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
    )
    mock_ma.assert_not_called()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
@patch("analysis.helper.leader_morphology.calc_window_bottom_to_high_change", return_value=31.9)
def test_bottom_to_high_non_main_fails_below_range(_mock_calc, mock_ma, _mock_sw, morphology_config):
    assert not _call(
        morphology_config,
        mode=LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
        market_type="gem",
    )
    mock_ma.assert_not_called()


@patch("analysis.helper.leader_morphology.is_leader_second_wave_long_ok", return_value=False)
@patch("analysis.helper.leader_morphology.is_ma_trend_rising", return_value=True)
@patch("analysis.helper.leader_morphology.calc_window_bottom_to_high_change", return_value=38.0)
def test_bottom_to_high_non_main_passes_in_range(_mock_calc, mock_ma, _mock_sw, morphology_config):
    assert _call(
        morphology_config,
        mode=LEADER_MORPHOLOGY_MODE_BOTTOM_TO_HIGH,
        market_type="gem",
    )
    mock_ma.assert_called_once()


def test_unsupported_mode_raises(morphology_config):
    with pytest.raises(ValueError, match="Unsupported leader morphology mode"):
        _call(morphology_config, mode="unknown_mode")


@patch("analysis.helper.leader_morphology._calc_head_tail_period_change", return_value=251.0)
def test_high_risk_when_change_above_threshold(mock_calc, morphology_config):
    from analysis.helper.leader_morphology import is_bottom_to_high_high_risk_leader

    assert is_bottom_to_high_high_risk_leader("sh600000", "20260707", morphology_config)
    mock_calc.assert_called_once()


@patch("analysis.helper.leader_morphology._calc_head_tail_period_change", return_value=250.0)
def test_not_high_risk_at_threshold(_mock_calc, morphology_config):
    from analysis.helper.leader_morphology import is_bottom_to_high_high_risk_leader

    assert not is_bottom_to_high_high_risk_leader("sh600000", "20260707", morphology_config)


@patch("analysis.helper.leader_morphology.is_bottom_to_high_high_risk_leader", side_effect=[True, False])
def test_pool_excludes_high_risk(_mock_risk, morphology_config):
    from analysis.helper.leader_morphology import pool_excluding_bottom_to_high_high_risk

    df = pd.DataFrame({"stock_code": ["sh600000", "sh600001"], "stock_name": ["A", "B"]})
    result = pool_excluding_bottom_to_high_high_risk(df, "20260707", morphology_config)
    assert len(result) == 1
    assert result.iloc[0]["stock_code"] == "sh600001"


def _make_close_df(closes):
    dates = [f"2026-06-{10 + i:02d}" for i in range(len(closes))]
    return pd.DataFrame({"日期": dates, "收盘": closes})


@patch("analysis.helper.leader_morphology.get_stock_data_df")
def test_calc_bottom_to_high_v_shape(mock_get_df):
    clear_leader_morphology_cache()
    mock_get_df.return_value = _make_close_df([10.0, 9.0, 8.0, 12.0, 15.0])
    result = calc_window_bottom_to_high_change("sh600000", "20260614", 5)
    assert result == pytest.approx(87.5)


@patch("analysis.helper.leader_morphology.get_stock_data_df")
def test_calc_bottom_to_high_uses_earliest_low_on_tie(mock_get_df):
    clear_leader_morphology_cache()
    mock_get_df.return_value = _make_close_df([10.0, 8.0, 8.0, 12.0, 15.0])
    result = calc_window_bottom_to_high_change("sh600000", "20260614", 5)
    assert result == pytest.approx(87.5)


@patch("analysis.helper.leader_morphology.get_stock_data_df")
def test_calc_bottom_to_high_ignores_pre_dip_high(mock_get_df):
    clear_leader_morphology_cache()
    mock_get_df.return_value = _make_close_df([20.0, 10.0, 8.0, 10.0, 12.0])
    result = calc_window_bottom_to_high_change("sh600000", "20260614", 5)
    assert result == pytest.approx(50.0)


@patch("analysis.helper.leader_morphology.get_stock_data_df")
def test_calc_bottom_to_high_insufficient_window(mock_get_df):
    clear_leader_morphology_cache()
    mock_get_df.return_value = _make_close_df([10.0, 11.0, 12.0])
    assert calc_window_bottom_to_high_change("sh600000", "20260612", 5) is None
