# -*- coding: utf-8 -*-
"""轮动图渲染冒烟测试：mock 6 天 x 若干概念计数，验证河流图渲染与边界情况。
通过 monkeypatch 模块级 COUNTS_CSV，全程不触碰真实数据文件。"""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch.tonghuashun.hot_concept_rotation as m

tmpdir = tempfile.mkdtemp()
csv_path = os.path.join(tmpdir, 'mock_counts.csv')
m.COUNTS_CSV = csv_path  # 让 save_concept_counts 写到临时目录

MOCK = {
    '20261016': {'算力租赁': 12, '固态电池': 5, '机器人': 8, '低空经济': 3, '军工': 4, '重组蛋白': 2, '储能': 6, '算力': 9, '消费电子': 5, 'CPO': 7},
    '20261019': {'算力租赁': 9, '固态电池': 11, '机器人': 7, '低空经济': 5, '军工': 3, '重组蛋白': 4, '储能': 4, '算力': 12, '消费电子': 6, 'CPO': 5},
    '20261020': {'算力租赁': 6, '固态电池': 14, '机器人': 10, '低空经济': 2, '军工': 6, '重组蛋白': 3, '储能': 7, '算力': 8, '消费电子': 4, 'CPO': 6},
    '20261021': {'算力租赁': 13, '固态电池': 9, '机器人': 6, '低空经济': 6, '军工': 2, '重组蛋白': 5, '储能': 3, '算力': 10, '消费电子': 7, 'CPO': 4},
    '20261022': {'算力租赁': 15, '固态电池': 6, '机器人': 9, '低空经济': 4, '军工': 5, '重组蛋白': 2, '储能': 8, '算力': 7, '消费电子': 3, 'CPO': 9},
    '20261023': {'算力租赁': 11, '固态电池': 8, '机器人': 12, '低空经济': 3, '军工': 4, '重组蛋白': 6, '储能': 5, '算力': 13, '消费电子': 8, 'CPO': 2},
}

for d, counts in MOCK.items():
    m.save_concept_counts(d, counts)
    m.save_concept_counts(d, counts)  # 覆盖测试：同日重存不应产生重复

df = pd.read_csv(csv_path, dtype={'date': str})
dup = df.duplicated(subset=['date', 'concept']).sum()
assert dup == 0, f"存在重复行: {dup}"
assert len(df) == sum(len(v) for v in MOCK.values()), "行数不符"
print(f"CSV OK: {len(df)} 行, 日期 {sorted(df['date'].unique())}")

out = os.path.join(tmpdir, 'rotation_test.png')
r = m.build_rotation_chart(days=5, top_n=8, output_path=out, counts_csv=csv_path)
assert r and os.path.exists(r) and os.path.getsize(r) > 10000, "渲染失败"
print(f"渲染 OK: {os.path.getsize(r)} bytes")

# 边界：仅 1 天数据时应拒绝渲染而不是报错
single_csv = os.path.join(tmpdir, 'single.csv')
m.COUNTS_CSV = single_csv
m.save_concept_counts('20261023', {'算力': 5})
r2 = m.build_rotation_chart(days=5, output_path=os.path.join(tmpdir, 'x.png'))
assert r2 is None, "单日数据应返回 None"
print("单日边界 OK")

print("全部通过")
