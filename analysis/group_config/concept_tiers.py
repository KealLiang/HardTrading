# 概念正统度分层配置（首版）

# 主类 -> 层级（1 硬核最高, 2 次硬核, 3 泛/弱）
GROUP_TIER = {
    "AI大模型": 2,
    "算力半导体": 1,
    "机器人": 2,
    "汽车工业": 2,
    "小米概念": 2,
    "华为概念": 2,
    "预期改善": 3,
    "新型能源": 2,
    "消费电子": 2,
}

# 主类 -> 角色（brand/event/chain/industry/generic）
GROUP_ROLE = {
    "AI大模型": "generic",
    "算力半导体": "chain",
    "机器人": "industry",
    "汽车工业": "industry",
    "小米概念": "brand",
    "华为概念": "brand",
    "预期改善": "event",
    "新型能源": "industry",
    "消费电子": "industry",
}

# 层级权重与角色权重（可调）
TIER_WEIGHT = {1: 1.0, 2: 0.6, 3: 0.3}
ROLE_WEIGHT = {"brand": 0.2, "event": 0.2, "chain": 0.4, "industry": 0.3, "generic": 0.1}

# 核心关键词（命中加分），建议持续补充
CORE_KEYWORDS = {
    "算力半导体": [
        "GPU", "加速卡", "AI芯片", "HBM", "CPO", "光模块", "高速互连",
        "服务器", "服务器电源", "PSU", "电源管理", "液冷", "数据中心电源",
    ],
    "机器人": ["减速器", "伺服", "本体", "关节模组", "人形机器人", "视觉"]
}

CORE_KEYWORD_BONUS = 0.5
FREQ_WEIGHT = 0.2
HOT_WEIGHT = 0.1

# 人工矫正（可选），key 可为原始短语子串或分组名
REASON_OVERRIDES = {
    # "AI营销": {"bonus": -0.3},
    # "AI文创": {"bonus": -0.3},
    # "AI服务器": {"bonus": +0.2},
}

