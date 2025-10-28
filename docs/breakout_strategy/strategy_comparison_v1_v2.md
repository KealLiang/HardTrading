# BreakoutStrategy V1 vs V2 对比文档

## 核心差异概述

**V2核心升级**：引入**动态仓位管理系统**，基于VCP和PSQ分数实现智能化的仓位分配、加仓和止盈。

---

## 一、新增参数 (V2)

### 1. 动态初始仓位参数
```python
('vcp_min_stake_pct', 0.2)     # 基于VCP分数的最小初始仓位比例
('vcp_max_stake_pct', 0.8)     # 基于VCP分数的最大初始仓位比例
```

### 2. 部分止盈参数
```python
('psq_profit_taking_score', 6.0)   # 触发部分止盈的PSQ分数阈值
('profit_taking_pct', 0.3)         # 部分止盈卖出的仓位比例
('min_profit_for_taking', 0.15)    # 触发部分止盈所需的最小浮盈
```

### 3. 加仓参数
```python
('psq_add_on_threshold', 0.5)      # 考虑加仓的PSQ分数阈值（降低至0.5）
('add_on_pullback_atr', 0.5)       # 加仓时要求的最小回调ATR倍数
('add_on_size_pct', 0.25)          # 每次加仓的头寸（占初始仓位比例）
```

---

## 二、状态变量新增 (V2)

```python
self.initial_size = 0           # 初始仓位数量，用于加仓和部分止盈计算
self.entry_stake_pct = 0.0      # 记录初始建仓时的仓位比例（用于加仓计算）
```

---

## 三、核心逻辑变化

### 3.1 初始仓位计算

**V1**: 固定仓位
```python
stake = self.broker.getvalue() * self.p.initial_stake_pct
size = int(stake / self.data.close[0])
```

**V2**: 基于VCP分数动态计算
```python
scaling_factor = vcp_score / 5.0
actual_stake_pct = self.p.vcp_min_stake_pct + \
                   (self.p.vcp_max_stake_pct - self.p.vcp_min_stake_pct) * scaling_factor
self.entry_stake_pct = actual_stake_pct

plan_stake = total_value * self.p.initial_stake_pct
actual_stake = plan_stake * actual_stake_pct
size = int(actual_stake / self.data.close[0])
```
**说明**: VCP分数越高（0-5分），初始仓位从20%逐步增加到80%。

---

### 3.2 持仓管理逻辑重构

**V1**: 所有逻辑在`next()`方法中平铺
```python
if self.position:
    if self.in_coiled_spring_probation:
        # 考察期逻辑...
    else:
        # ATR止损逻辑...
```

**V2**: 模块化分离
```python
if self.position:
    if self.in_coiled_spring_probation:
        self._manage_probation_period()  # 提取为独立方法
        return
    
    is_stopped = self._manage_atr_stop()  # 提取为独立方法
    if is_stopped:
        return
    
    self._dynamic_position_management(current_psq_score)  # 新增动态管理
```

---

### 3.3 新增功能：动态仓位管理

**V2新增方法**: `_dynamic_position_management(psq_score)`

#### 功能1：部分止盈
触发条件（AND关系）：
- PSQ分数 > 6.0
- 浮盈 > 15%

执行：卖出30%仓位

#### 功能2：加仓
触发条件（ALL条件必须满足）：
1. **仓位空间检查**: `position.size < max_plan_size`
2. **趋势健康度**: 价格在MA10之上 且 MA5 > MA10
3. **建设性回调**: 从最高点回调 >= 0.5倍ATR
4. **动能企稳**: PSQ分数 >= 0.5

执行：买入初始仓位的25%

---

### 3.4 订单通知逻辑增强

**V1**: 不区分初始建仓和加仓

**V2**: 明确区分
```python
is_initial_entry = (self.position.size == order.executed.size)

if is_initial_entry:
    self.log('初始建仓成功: ...')
    self.initial_size = order.executed.size
    # 切换PSQ跟踪状态
else:
    self.log('加仓成功: ...')
```

**V2**: 区分部分止盈和清仓
```python
if order.issell():
    if self.position:
        self.log('部分止盈卖出: ...')
    else:
        self.log('卖出成交: ...')
```

---

## 四、日志输出差异

### V1输出
```
*** 二次确认信号已执行，解除观察模式，
    当前过热分: X.XX 
    (VCP 参考: VCP-X, Score: X.XX) ***
```

### V2输出
```
*** 二次确认信号已执行，解除观察模式，
    当前过热分: X.XX 
    (VCP: VCP-X, Score: X.XX) 
    --> 动态初始仓位: XX.X% ***
```

---

## 五、策略哲学变化

| 维度 | V1 | V2 |
|------|----|----|
| **仓位策略** | 固定仓位，All-in或空仓 | 动态仓位，根据信号质量分级建仓 |
| **风险管理** | 单一ATR止损 | ATR止损 + 部分止盈 |
| **盈利优化** | 趋势跟踪至止损 | 部分止盈锁定利润 + 剩余仓位追趋势 |
| **仓位构建** | 一次性建仓 | 初始建仓 + 回调加仓 |
| **信号利用** | VCP仅作参考 | VCP分数直接决定仓位大小 |

---

## 六、性能预期

### V2预期优势
1. **降低单笔交易风险**: 低质量信号使用小仓位试错
2. **提高资金效率**: 高质量信号使用大仓位获取收益
3. **改善收益曲线**: 部分止盈减少回撤，提升夏普比率
4. **捕捉大趋势**: 加仓机制在强趋势中放大盈利

### V2潜在风险
1. **频繁交易**: 加仓和止盈增加交易次数，手续费成本上升
2. **参数敏感度**: 新增7个参数，过拟合风险增加
3. **复杂度**: 逻辑复杂度提升，调试难度加大

---

## 七、代码质量改进

### V2优化点
1. **模块化**: 将400+行的`next()`方法拆解为多个职责单一的方法
2. **可读性**: 持仓管理逻辑清晰分层
3. **可维护性**: 新增功能可独立开发和测试

---

## 总结

**V1**: 经典的突破策略，逻辑简洁，适合快速验证信号系统有效性。

**V2**: 在V1基础上引入专业的仓位管理系统，更符合真实交易中"信号分级+仓位分级"的理念，但需要更多回测验证参数有效性。

**选择建议**:
- 初期测试/信号研发 → 使用V1
- 实盘交易/参数优化完成后 → 使用V2 