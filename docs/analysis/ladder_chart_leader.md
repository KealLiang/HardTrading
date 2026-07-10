# ladder_chart 龙头 sheet 筛选逻辑

> 代码入口：`analysis/ladder_chart.py` → `select_leader_stocks_from_concept_groups()`  
> 开关：`create_leader_sheet=True` 时生成，sheet 名 `龙头{MMDD}`

---

## 整体流程（简）

```
连板/首板数据 → 显著连板识别 → 【概念分组】sheet 数据
                                      ↓
                              龙头筛选（6步）
                                      ↓
                         普通龙头 + 大龙 → 写入龙头 sheet
                                      ↓
                    超 MAX_LEADER_SHEETS(5) 的旧 sheet 归档
```

---

## 筛选六步

| 步 | 做什么 |
|----|--------|
| 1 | 算每只股票的 `last_board_date`（最后连板日） |
| 2 | 按概念组统计**活跃股数**（未被折叠的行） |
| 3 | 按活跃数排名 → 分配各组**龙头名额** |
| 4 | 各组内筛候选 → 按名额取 Top N |
| 5 | 从候选中分离**大龙股**（长周期涨幅 ≥ 100%，不占名额） |
| 6 | 大龙占用的名额 → 从剩余候选中补位（仍须 < 100% 阈值） |

---

## 「活跃股」定义

与【概念分组】sheet 折叠逻辑一致：

- **断板天数** = 最后连板日 → 复盘截止日 的交易日数
- 断板 > `COLLAPSE_DAYS_AFTER_BREAK`(10) 天 → **折叠**（非活跃）
- 长周期(30日)涨幅 > 110% 的强龙 → 折叠阈值 +6 天（=16天）

`SELECT_LEADERS_FROM_ACTIVE_ONLY=True`（默认）时，**只从活跃股中选**。

---

## 单股入选条件（须全部满足）

### 基础门槛

| 市场 | 最低连板数 | 近30日涨幅 | 近3日涨幅上限 |
|------|-----------|-----------|--------------|
| 主板 | ≥ 1 | ≥ 30% | **<** 13% |
| 非主板 | ≥ 0 | ≥ 37% | **<** 19% |

> 近3日涨幅上限：过滤「预期已兑现」的急涨股（严格小于）。

### 形态条件（二选一，OR）

> 实现：`analysis/helper/leader_morphology.py`  
> 模式开关：`LEADER_MORPHOLOGY_MODE`（`head_tail` | `bottom_to_high`，默认 `head_tail`）

**条件1 — 趋势龙**（两种模式二选一，均须 + 均线上升趋势）

| 模式 | 涨幅口径 | 主板 | 非主板 |
|------|----------|------|--------|
| `head_tail` | 近30日**首尾**收盘涨幅 ≥ 下限 | ≥ 30% | ≥ 37% |
| `bottom_to_high` | 近30日**低点→其后高点**收盘涨幅 **闭区间** | 25% ~ 35% | 32% ~ 42% |

参数常量（`ladder_chart.py`，元组约定均为 **(主板, 非主板)**）：
- `LEADER_MORPHOLOGY_HEAD_TAIL_MIN_CHANGE = (30, 37)`
- `LEADER_MORPHOLOGY_BOTTOM_TO_HIGH_CHANGE_RANGE = ((25, 35), (32, 42))`
- `LEADER_MORPHOLOGY_BOTTOM_TO_HIGH_HIGH_RISK_*`：120日涨幅 > 250% 不入**普通龙头**（大龙不受影响）

**条件2 — 二波/老牌**（两种模式共用）

- 近60根有效K 振幅 `(max高-min低)/max高×100` ≥ 95%（非主板 105%）
- 最新收盘 > 窗口最早收盘（方向向上）
- MA20 > MA10，且收盘或最高落在 MA10~MA20 之间
- 非明显下跌趋势

> 无法解析复盘截止日时，条件1/2 均不成立。

### 排除

- 概念组 `默默上涨` 不参与筛选、不分配名额

---

## 组内排序 & 取名额

排序键（降序）：`long_period_change` → `short_period_change`(近10日) → `max_board_level`

每组取前 N 只，N 由活跃度排名决定：

| 活跃度排名 | 名额 |
|-----------|------|
| 第1 | 5 |
| 第2 | 4 |
| 第3 | 3 |
| 第4 | 2 |
| 第5 ~ 前35% | 1 |
| 后65% | 1 |

> 当前默认/冷门名额均为 1，分界线主要供日后调参。

---

## 大龙股

- 条件：通过上述全部筛选 **且** 近30日涨幅 ≥ **100%**
- **不占名额**，单独列在 sheet 下半区
- 若大龙原本占了名额 → 从该组剩余候选补位（跳过 ≥100% 的）

---

## sheet 输出结构

```
表头 + 大盘指标
  ↓
普通龙头（按概念优先级排序）
  ↓ 空行
名额汇总日志（各组入选/落选名单）
  ↓ 空行
大龙股
```

最终排序：`concept_priority` → `concept_group` → `first_significant_date` → 涨幅 → 首板连板数

---

## 归档

- 主簿最多保留 **5** 张龙头 sheet
- 超出 → 写入 `excel/ladder_analysis_龙头归档.xlsx`（单文件超 100 sheet 自动拆分）
- 历史龙头 sheet 会**回填**最新交易日数据

---

## 关键参数速查

| 参数 | 值 | 含义 |
|------|-----|------|
| `LEADER_MORPHOLOGY_MODE` | head_tail / bottom_to_high | 形态模式 |
| `LEADER_MORPHOLOGY_HEAD_TAIL_MIN_CHANGE` | (30, 37) | head_tail 涨幅下限，(主板, 非主板) |
| `LEADER_MORPHOLOGY_BOTTOM_TO_HIGH_CHANGE_RANGE` | ((25,35),(32,42)) | bottom_to_high 闭区间 |
| `PERIOD_DAYS_LONG` | 30 | 长周期涨幅窗口 |
| `PERIOD_DAYS_VERY_LONG` | 60 | 二波振幅窗口 |
| `LEADER_ULTRA_SHORT_PERIOD_DAYS` | 3 | 超短过滤窗口 |
| `LEADER_EXTRA_LONG_PERIOD_THRESHOLD` | 100% | 大龙阈值（设0关闭） |
| `LEADER_EXCLUDE_CONCEPTS` | `['默默上涨']` | 排除概念组 |
