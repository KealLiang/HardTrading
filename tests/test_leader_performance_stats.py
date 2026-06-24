"""leader_performance_stats 单元测试。"""

from analysis.leader_performance_stats import (
    LEADER_TYPE_NORMAL,
    LeaderSample,
    TradeOutcome,
    _split_entries_by_row_gap,
    compute_horizon_stats,
    parse_leader_quota_log,
    resolve_concept_group,
)


def test_parse_leader_quota_log():
    log = (
        "存储芯片: 3; 柏诚股份, 博敏电子, 江南新材\n"
        "CPO: 2; 某甲, (某乙)"
    )
    mapping = parse_leader_quota_log(log)
    assert mapping['柏诚股份'] == '存储芯片'
    assert mapping['某甲'] == 'CPO'
    assert '某乙' not in mapping


def test_compute_horizon_stats_basic():
    sample = LeaderSample(
        '600000', '浦发银行', '[测试]', '测试', LEADER_TYPE_NORMAL, '2026-01-05', '龙头0105'
    )
    outcomes = [
        TradeOutcome(sample, '20260106', '20260107', 10.0, 11.0, 10.0),
        TradeOutcome(sample, '20260106', '20260107', 10.0, 9.0, -10.0),
        None,
    ]
    st = compute_horizon_stats(outcomes, 'T+2', 2, total_samples=3)
    assert st.valid_samples == 2
    assert st.skipped_samples == 1
    assert st.win_rate == 50.0
    assert abs(st.profit_loss_ratio - 1.0) < 1e-6


def test_resolve_concept_group_prefers_quota_log():
    group = resolve_concept_group(
        '[长鑫产业链+存储芯片+洁净室]',
        '柏诚股份 ↑',
        {'柏诚股份': '存储芯片'},
        ['长鑫产业链', '存储芯片'],
    )
    assert group == '存储芯片'


def test_split_entries_by_row_gap():
    entries = [
        (4, '600000', 'A', 'c1'),
        (5, '600001', 'B', 'c2'),
        (7, '600002', 'C', 'c3'),
    ]
    groups = _split_entries_by_row_gap(entries)
    assert len(groups) == 2
    assert len(groups[0]) == 2
    assert len(groups[1]) == 1
