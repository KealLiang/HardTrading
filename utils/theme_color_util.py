import re
from collections import Counter

# 同义词组定义
synonym_groups = {
    "医药": ["%医药%", "创新药", "%疫苗%", "%医疗器械%", "%养老%", "%合成生物%", "%重组蛋白%", "%原料药%", "中成药"],
    "新消费": ["%宠物%", "艺术黄金", "%珠宝%", "%首饰%", "%新消费%", "%AR%", "%VR%"],
    "无人经济": ["%无人驾驶%", "%智能物流%", "%自动驾驶%", "%无人配送%", "%无人机%"],
    "新传媒": ["%IP经济%", "IP", "小红书"],
    "半导体": ["%半导体%", "%芯片%", "%存储芯片%", "%集成电路%", "%光刻%", "%集成电路%"],
    "电子元件": ["%铜缆%", "%电子元件%", "%PCB%", "%连接器%", "%卫星通信%", "%雷达%", "%电线电缆%"],
    "AI": ["%AI%", "%人工智能%", "%DeepSeek%", "%大模型%", "%GPT%", "%AIGC%", "%MCP%", "%脑机接口%"],
    "算力": ["%算力%", "%液冷%", "%数据中心电源%", "%服务器测试%", "数据中心"],
    "新能源": ["%新能源%", "%电动车%", "%动力电池%", "%光伏%", "%锂电池%", "%氢%", "%可控核聚变%", "%节能环保%",
               "特斯拉", "固态电池", "%核电%", "%核能%"],
    "重组": ["%重组%", "%控制权%"],
    "电力": ["%风电%", "%电力%", "%核电%", "%电网设备%", "电机"],
    "化工": ["%化工%", "%环氧丙烷%", "%氯碱%", "%化纤%", "%涂料%", "%季戊四醇%", "%聚酯%", "%钛白粉%", "%造纸%", "%纺织%"],
    "新材料": ["%PEEK材料%", "%碳纤维%", "%高温合金%", "%稀土永磁%"],
    "军工": ["%军工%", "%国防%", "%航空%", "%战斗机%", "%大飞机%", "%军贸%", "%成飞%"],
    "航天": ["%航天%", "%低空经济%", "%飞行汽车%"],
    "机器人": ["%机器人%", "%减速器%"],
    "跨境": ["%跨境%", "%外销%", "%港口%", "%一带一路%", "%航运%", "%出海%", "统一大市场"],
    "房地产": ["%房地产%", "%城市更新%", "%建筑%", "%室内设计%"],
    "汽车": ["%汽车%", "%压缩机%"],
    "消费电子": ["%消费电子%", "%苹果%", "%智能穿戴%", "%光学元件%", "%汽车电子%", "%智能座舱%", "%智能家居%"],
    "大消费": ["消费", "白酒", "食品", "饮料", "零售", "商超", "免税", "化妆品", "麦角硫因", "电商", "电子商务",
               "消费电子", "家电", "%益生菌%"],
    "旅游": ["旅游", "酒店", "民航", "免税", "出行"],
    "金融": ["%金融%", "%保险%", "%银行%", "%信托%", "%AH%", "腾讯"],
    "华为": ["%华为%", "%鸿蒙%"],
    "国企": ["%国企%", "%国资%", "%央企%", "%中字头%", "%兵装%"],
    "业绩增长": ["%业绩%", "%报增%", "%净利%", "%预增%"],
    "扭亏为盈": ["%扭亏%", "%减亏%", "%摘帽%"]
}

# 排除列表 - 这些原因不会被选为热门原因
EXCLUDED_REASONS = [
    "业绩增长",
    "扭亏为盈",
    "国企",
]

# 选取top n的原因着色
TOP_N = 9

# 颜色列表 - 彩虹色系(深色)
COLORS = [
    "FF5A5A",  # 红色
    "FF8C42",  # 橙色
    "FFCE30",  # 黄色
    "6AD15A",  # 绿色
    "45B5FF",  # 蓝色
    "9966FF",  # 紫色
    "FF66B3",  # 粉色
    "5ACDCD",  # 青色
    "DDA0DD",  # 浅紫红
    "FFB366",  # 浅橙色
    "FFF066",  # 浅黄色
    "90EE90",  # 浅绿色
    "87CEFA",  # 浅蓝色
    "B19CD9",  # 浅紫色
    "FFB6C1",  # 浅粉色
    "E1FFFF",  # 浅青色
]

def normalize_reason(reason):
    """
    将原因标准化，处理同一类型的不同表述，优先匹配最具体的模式
    """
    # 移除所有空格
    reason = re.sub(r'\s+', '', reason)
    original_reason = reason

    # 存储所有匹配结果及其匹配信息
    matches = []

    # 检查原因属于哪个组
    for main_reason, synonyms in synonym_groups.items():
        for synonym in synonyms:
            # 处理通配符匹配
            if '%' in synonym:
                # 转换SQL风格通配符为正则表达式
                pattern = synonym.replace('%', '(.*)')
                regex = re.compile(f"^{pattern}$")
                match = regex.search(reason)
                
                if match:
                    # 计算匹配的具体部分
                    matched_text = reason
                    for group in match.groups():
                        matched_text = matched_text.replace(group, '')
                    
                    # 匹配强度 = 匹配文本长度 / 原文长度
                    match_strength = len(matched_text) / len(reason)
                    matches.append((main_reason, match_strength, synonym))
            
            # 保留原有的包含匹配
            elif synonym in reason:
                match_strength = len(synonym) / len(reason)
                matches.append((main_reason, match_strength, synonym))

    # 如果有匹配，选择匹配强度最高的
    if matches:
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0]

    return f"未分类_{original_reason}"

def extract_reasons(reason_text):
    """
    从原因文本中提取所有原因
    """
    if not reason_text or isinstance(reason_text, float):  # 处理pd.isna()的情况
        return []

    # 以"+"分割不同原因
    reasons = reason_text.split('+')
    return [normalize_reason(r.strip()) for r in reasons if r.strip()]

def get_reason_colors(all_reasons, top_n=TOP_N):
    """
    根据原因出现频率，为热门原因分配颜色
    
    Args:
        all_reasons: 所有原因的列表
        top_n: 选取的热门原因数量
        
    Returns:
        tuple: (reason_colors, top_reasons) - 原因到颜色的映射字典和热门原因列表
    """
    # 统计所有原因出现次数
    reason_counter = Counter(all_reasons)
    
    # 过滤掉未分类的原因和排除列表中的原因
    classified_reasons = [reason for reason in reason_counter.keys()
                          if not reason.startswith('未分类_') and reason not in EXCLUDED_REASONS]
    
    # 确保所有原因的出现次数都被正确计算
    # 首先创建包含所有可能原因的计数字典
    all_reason_counts = {reason: 0 for reason in synonym_groups.keys()}
    
    # 然后用实际统计的次数更新
    for reason, count in reason_counter.items():
        if not reason.startswith('未分类_'):
            all_reason_counts[reason] = count
    
    # 选择热门原因 (排除指定的原因)
    # 按出现次数倒序选择TOP_N个原因
    top_reasons = [reason for reason, count in sorted(all_reason_counts.items(),
                                                  key=lambda x: x[1],
                                                  reverse=True)
                   if count > 0 and reason not in EXCLUDED_REASONS][:top_n]
    
    # 为每个原因分配颜色
    reason_colors = {reason: COLORS[i % len(COLORS)] for i, reason in enumerate(top_reasons)}
    
    return reason_colors, top_reasons

def get_stock_reason_group(all_stocks, top_reasons):
    """
    确定每支股票主要属于哪个原因组
    
    Args:
        all_stocks: 股票信息字典，包含每只股票的原因列表
        top_reasons: 热门原因列表
        
    Returns:
        dict: 股票到主要原因的映射字典
    """
    stock_reason_group = {}
    
    for stock_key, data in all_stocks.items():
        if not data['reasons']:
            continue
        
        # 统计该股票的原因
        stock_reason_counter = Counter(data['reasons'])
        
        # 先检查哪些原因是热门原因
        top_reasons_found = [reason for reason in top_reasons if reason in stock_reason_counter]
        
        if top_reasons_found:
            # 如果有多个热门原因，选择出现次数最多的
            top_reason_counts = [(reason, stock_reason_counter[reason]) for reason in top_reasons_found]
            top_reason_counts.sort(key=lambda x: x[1], reverse=True)
            stock_reason_group[stock_key] = top_reason_counts[0][0]
        elif stock_reason_counter:
            # 如果没有热门原因，使用该股票最常见的原因
            most_common_reason = stock_reason_counter.most_common(1)[0][0]
            stock_reason_group[stock_key] = most_common_reason
    
    return stock_reason_group 