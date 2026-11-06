# -*- coding: utf-8 -*-
"""近义词合并规则单测：验证合并正确、层级词与语义不同词不被误并、前缀族归并。"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetch.tonghuashun.hot_concept_rotation import _is_synonym, _merge_synonyms

# 应合并：一字之差且差异字夹在中间 / 增减一字
assert _is_synonym('AI短剧', 'AI漫剧')
assert _is_synonym('低温乳品', '低温乳制品')
# 子串关系（三季报增 ⊂ 三季报增长）按层级概念处理，不合并
assert not _is_synonym('三季报增', '三季报增长')

# 不应合并：包含关系（层级概念）
assert not _is_synonym('机器人', '人形机器人')
assert not _is_synonym('算力', '算力租赁')
assert not _is_synonym('电池', '固态电池')

# 不应合并：改的是核心字，语义不同
assert not _is_synonym('南京国资', '北京国资')
assert not _is_synonym('湖南国资', '河南国资')
assert not _is_synonym('光伏电站', '光伏电池')
assert not _is_synonym('电路板设计', '电路板设备')
assert not _is_synonym('半导体设备', '半导体材料')

# 不应合并：纯拉丁缩写
assert not _is_synonym('CPO', 'PCB')
assert not _is_synonym('CRO', 'CXO')

totals = pd.Series({
    '三季报增长': 10, '三季报预增': 6, '三季报亏损': 2, '三季报扭亏': 4,
    'AI短剧': 8, 'AI漫剧': 3,
    '机器人': 20, '人形机器人': 30, '算力': 12, '算力租赁': 7,
})
m = _merge_synonyms(totals)

# 前缀归并族：三季报xx 全部归到「三季报业绩」
assert m.get('三季报预增') == '三季报业绩', m
assert m.get('三季报亏损') == '三季报业绩', m
assert m.get('三季报扭亏') == '三季报业绩', m
assert m.get('三季报增长') == '三季报业绩', m
# 自动规则：低频词归到高频词
assert m.get('AI漫剧') == 'AI短剧', m
# 层级概念保持独立
assert '机器人' not in m and '人形机器人' not in m, m
assert '算力' not in m and '算力租赁' not in m, m

# 合并后总量守恒
merged = totals.copy()
for src, rep in m.items():
    merged[rep] = merged.get(rep, 0) + merged.pop(src)
assert merged['三季报业绩'] == 22, merged
assert merged['AI短剧'] == 11, merged
assert merged.sum() == totals.sum()

print("近义词合并测试全部通过")
print(m)
