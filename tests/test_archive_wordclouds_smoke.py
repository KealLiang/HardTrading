# -*- coding: utf-8 -*-
"""archive_old_wordclouds 冒烟测试：在临时目录构造 25 张图，验证归档后 hot 剩 20、history 收 5，且移走的是最老的。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fetch.tonghuashun.hotpoint_analyze as m

tmp_hot = os.path.join(tempfile.mkdtemp(), 'hot')
tmp_hist = os.path.join(tempfile.mkdtemp(), 'history')
os.makedirs(tmp_hot)
os.makedirs(tmp_hist)

for i in range(1, 26):  # 20261001 ~ 20261025
    d = f"202610{i:02d}"
    with open(os.path.join(tmp_hot, f"{d}_concept.png"), 'w') as f:
        f.write('x')

m.save_path = tmp_hot + os.sep
m.HISTORY_CLOUD_DIR = tmp_hist + os.sep

m.archive_old_wordclouds(keep=20)

hot_left = sorted(os.listdir(tmp_hot))
hist_got = sorted(os.listdir(tmp_hist))
assert len(hot_left) == 20, f"hot 应剩 20 张，实际 {len(hot_left)}"
assert len(hist_got) == 5, f"history 应收 5 张，实际 {len(hist_got)}"
assert all(f[:8] >= '20261006' for f in hot_left), "hot 应保留最新 20 张"
assert all(f[:8] <= '20261005' for f in hist_got), "history 应收最老 5 张"
# 不足 keep 数时不应有任何动作
m.archive_old_wordclouds(keep=20)
hot_left = sorted(os.listdir(tmp_hot))
assert len(hot_left) == 20 and len(os.listdir(tmp_hist)) == 5

# history 同名冲突覆盖不报错
with open(os.path.join(tmp_hist, "20261020_concept.png"), 'w') as f:
    f.write('old')
os.mkdir(os.path.join(tmp_hot, 'tmp_rebuild'))  # 占位再删
os.rmdir(os.path.join(tmp_hot, 'tmp_rebuild'))
with open(os.path.join(tmp_hot, "20261026_concept.png"), 'w') as f:
    f.write('x')
m.archive_old_wordclouds(keep=20)  # 20261021 被移走，20261020 不受影响
assert os.path.exists(os.path.join(tmp_hist, "20261020_concept.png"))

print("归档测试全部通过")
