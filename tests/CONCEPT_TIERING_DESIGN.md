# 多标签正统度分层：概设说明

## 目标
- 在现有“同义词分组”基础上，为每只股票生成“主标签 + 若干次标签”，并对概念进行“正统度”打分，区分硬核与蹭概念。
- 尽量最小侵入实现：不改变既有着色/分组的对外行为，只新增元信息（主/次标签、正统分）。

## 设计要点
- 保留现有 normalize_reason/synonym_groups 的一级主类归并。
- 新增“正统度配置”文件（analysis/group_config/concept_tiers.py）：
  - GROUP_TIER: 主类 -> 层级（1=硬核高，2=次硬核，3=泛/弱）。
  - GROUP_ROLE: 主类 -> 角色（brand/event/chain/industry/generic）。
  - TIER_WEIGHT/ROLE_WEIGHT: 层级与角色的权重（可调参）。
  - CORE_KEYWORDS: 主类 -> 关键硬核词（命中加分）。
  - REASON_OVERRIDES: 针对特定短语/模式的人工矫正（可选）。
- 新增“原始短语保留 + 打分 + 主次标签”能力：
  - extract_reasons_with_original(text) -> [(original, group)]，不丢失原始短语。
  - score_reason(original, group) -> float：基于 tier/role/核心词/频次/热度计算分数。
  - get_stock_reason_labels(all_stocks, top_reasons, k=2) -> {stock: {primary, secondaries}}。
- 报表集成（analysis/whimsical.py）：
  - 仍然使用原有 get_stock_reason_group 上色，不破坏既有表现。
  - 在单元格批注中附加“主/次标签 + 分数”。

## 打分公式（首版简化）
- base = TIER_WEIGHT[ tier(group) ] + ROLE_WEIGHT[ role(group) ]
- bonus_core = + CORE_KEYWORD_BONUS（若 original 命中该组核心关键词）
- bonus_freq = + 0.2 * count(group)（该股内该组出现次数）
- bonus_hot = + 0.1 * (TOP_N 排名逆序分)（若该组位于 top_reasons）
- score = base + bonus_core + bonus_freq + bonus_hot
- 并列打破：tier 优先（1 更硬核）> 组内最高 original 分 > 频次 > 全局热度

## 变更点（文件与接口）
- 新增：analysis/group_config/concept_tiers.py（配置与默认权重、核心词、示例 overrides）。
- 修改：utils/theme_color_util.py
  - 新增 extract_reasons_with_original()
  - 新增 score_reason() / get_reason_meta() / get_stock_reason_labels()
  - 兼容无配置时的安全降级（不报错，返回空标签）。
- 修改：analysis/whimsical.py
  - 构建 all_stocks 时同时保存 reason_details（original+group）。
  - 生成 labels，并在批注中展示。

## 风险与回退
- 配置问题：若概念配置导入失败，labels 功能自动禁用，不影响原有流程。
- 分数偏置：通过配置可调参，并支持 overrides 手动修正。

## 后续演进（可选）
- 共现/PMI、事件窗口超额收益、供应链图谱、向量相似度作为二排序键。
- 导出“高频未分类/冲突清单”，闭环改进配置。

