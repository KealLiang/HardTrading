"""重构后 V4 信号路径与配置绑定自检（不依赖网络时可部分运行）。"""
import inspect

from alerting.t_trade_alert_base import TMonitorBase
from alerting.t_trade_alert_v4 import TMonitorConfigV4, TMonitorV4


def test_v4_inherits_base_not_v3():
    assert TMonitorV4.__bases__ == (TMonitorBase,)
    assert TMonitorV4.CONFIG is TMonitorConfigV4
    assert TMonitorV4.cfg.fget is TMonitorBase.cfg.fget


def test_v4_config_runtime_values():
    assert TMonitorConfigV4.MAX_HISTORY_BARS_1M == 241
    assert TMonitorConfigV4.WARMUP_BARS == 240
    assert TMonitorConfigV4.min_history_bars() == 60


def test_v4_signal_methods_are_own_not_base():
    assert TMonitorV4._generate_signal is not TMonitorBase._generate_signal
    assert TMonitorV4._prepare_indicators is not TMonitorBase._prepare_indicators
    assert TMonitorV4._trigger_signal is not TMonitorBase._trigger_signal
    assert hasattr(TMonitorV4, '_check_signal_cooldown')


def test_process_and_backtest_live_on_base():
    assert TMonitorV4._process_1m_data is TMonitorBase._process_1m_data
    assert TMonitorV4._run_live is TMonitorBase._run_live
    assert TMonitorV4._run_backtest is TMonitorBase._run_backtest


def test_run_live_uses_v4_history_count():
    from alerting.t_trade_alert_base import TDX_KLINE_1M

    src = inspect.getsource(TMonitorBase._run_live)
    assert 'self.cfg.MAX_HISTORY_BARS_1M' in src
    assert 'TDX_KLINE_1M' in src
    assert TDX_KLINE_1M == 7
