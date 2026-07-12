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

## 筛选六步（顺序重要）

| 步 | 做什么 | 说明 |
|----|--------|------|
| 1 | 算 `last_board_date` | 用于活跃股 / 折叠 |
| 2 | 统计各概念组**活跃股数** | 尚未做个股形态筛选 |
| 3 | 按活跃数排名 → **预分配名额 N** | 只定每组最多选几只，不选股 |
| 4 | **逐组**筛候选 → 排序 → 取 Top N | 见下文「组内筛选」 |
| 5 | 从各组 qualified 池分离**大龙股** | 30日首尾涨幅 ≥ 100%，不占名额 |
| 6 | 大龙占用的名额 → 从剩余候选补位 | 补位仍走普通龙头池规则 |

**不是**「全市场先按形态筛一批，再按板块分名额」。  
正确顺序：**先定各组名额 → 再在组内**用门槛筛股并取 Top N。同一只股票可在多个概念组各筛一次。

---

## 组内筛选（第 4 步明细）

对每个概念组，在**活跃股**（默认）上依次：

```
连板门槛  AND  形态门槛  AND  近3日涨幅上限
        ↓
    qualified 列表（组内排序）
        ↓
bottom_to_high 模式：剔除 120日高危（仅普通龙头名额池）
        ↓
    取 Top N（N = 第 3 步预分配名额）
```

组内排序键（降序）：`long_period_change`（30日首尾）→ `short_period_change`（近10日）→ `max_board_level`

| 活跃度排名 | 名额 N |
|-----------|--------|
| 第1 | 5 |
| 第2 | 4 |
| 第3 | 3 |
| 第4 | 2 |
| 第5 ~ 前35% | 1 |
| 后65% | 1 |

---

## 「活跃股」定义

与【概念分组】sheet 折叠逻辑一致：

- **断板天数** = 最后连板日 → 复盘截止日 的交易日数
- 断板 > `COLLAPSE_DAYS_AFTER_BREAK`(10) 天 → **折叠**（非活跃）
- 长周期(30日)首尾涨幅 > 110% 的强龙 → 折叠阈值 +6 天（=16天）

`SELECT_LEADERS_FROM_ACTIVE_ONLY=True`（默认）时，**只从活跃股中选**。

---

## 单股门槛（进入 qualified 池）

进入 qualified 须同时满足下面 **A + B**。A 与模式无关；B 随 `LEADER_MORPHOLOGY_MODE` 切换。

### A. 通用门槛（两种模式相同）

| 市场 | 最低连板数 | 近3日涨幅上限 |
|------|-----------|--------------|
| 主板 | ≥ 1 | 严格小于 13% |
| 非主板 | ≥ 0 | 严格小于 19% |

近3日上限用于过滤「预期已兑现」的急涨股。

### B. 形态门槛（按模式，条件1 或 条件2 满足其一即可）

> 实现：`analysis/helper/leader_morphology.py`  
> 开关：`LEADER_MORPHOLOGY_MODE`（`head_tail` | `bottom_to_high`）

**条件1 — 趋势龙**（须 + 均线上升趋势 `is_ma_trend_rising`）

| 模式 | 涨幅口径 | 主板 | 非主板 |
|------|----------|------|--------|
| `head_tail` | 近30日首尾收盘涨幅 ≥ 下限 | ≥ 30% | ≥ 37% |
| `bottom_to_high` | 近30日低点→其后高点收盘涨幅（闭区间） | 25% ~ 35% | 32% ~ 42% |

> `head_tail` 的 30%/37% 在条件1 里，**不是**通用门槛。  
> `bottom_to_high` **不要求**首尾 30 日 ≥ 30%，只看低点→高点区间。

**条件2 — 二波/老牌**（两种模式共用）

- 近60根有效K 振幅 `(max高-min低)/max高×100` ≥ 95%（非主板 105%）
- 最新收盘 > 窗口最早收盘
- MA20 > MA10，且收盘或最高落在 MA10~MA20 之间
- 非明显下跌趋势

> 无法解析复盘截止日时，条件1/2 均不成立。

### C. 普通龙头附加（仅 `bottom_to_high`，不影响进 qualified 池）

- 120日**首尾**涨幅 **>** 250% → 不可占**普通龙头**名额
- 仍保留在 qualified 池，**大龙股**识别照常（见下节）

### 排除

- 概念组 `默默上涨`：不分配名额、不参与筛选

---

## 大龙股

- 来源：各组 **完整 qualified 池**（含 120 日高危股）
- 条件：30日**首尾**涨幅 ≥ **100%**（`LEADER_EXTRA_LONG_PERIOD_THRESHOLD`）
- **不占名额**，列在 sheet 下半区
- 若大龙占了普通名额 → 从**普通龙头池**（已剔高危）补位

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

元组约定均为 **(主板, 非主板)**，区间为元组嵌套 `((main_lo, main_hi), (non_main_lo, non_main_hi))`。

| 参数 | 值 | 含义 |
|------|-----|------|
| `LEADER_MORPHOLOGY_MODE` | head_tail / bottom_to_high | 形态模式 |
| `LEADER_MORPHOLOGY_HEAD_TAIL_MIN_CHANGE` | (30, 37) | head_tail 条件1 下限（%） |
| `LEADER_MORPHOLOGY_BOTTOM_TO_HIGH_CHANGE_RANGE` | ((25,35),(32,42)) | bottom_to_high 条件1 闭区间 |
| `LEADER_MORPHOLOGY_BOTTOM_TO_HIGH_HIGH_RISK_*` | 120日 / 250% | 普通龙头高危过滤 |
| `PERIOD_DAYS_LONG` | 30 | 30日窗口（形态条件1） |
| `PERIOD_DAYS_VERY_LONG` | 60 | 二波振幅窗口 |
| `LEADER_ULTRA_SHORT_PERIOD_DAYS` | 3 | 通用近3日过滤 |
| `LEADER_EXTRA_LONG_PERIOD_THRESHOLD` | 100% | 大龙阈值（设0关闭） |
| `LEADER_EXCLUDE_CONCEPTS` | `['默默上涨']` | 排除概念组 |
