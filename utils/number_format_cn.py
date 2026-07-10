"""
中文场景下的数值展示（A 股习惯等）。

说明：常见库如 humanize 多为英文单位；cn2an 等侧重中文数字读写，
对「成交额 → xx万 / xx亿」这类展示没有标准封装，故用轻量规则函数维护在此，便于复用。
"""

from __future__ import annotations

import math
from typing import Any, Optional


def format_turnover_amount_cn(amount: Any) -> Optional[str]:
    """
    将成交额（单位：元）格式化为「xx万」「xx亿」等展示。

    规则：
    - >= 1 亿：保留两位小数 + 「亿」
    - >= 1 万：保留两位小数 + 「万」
    - 更小：整数 + 「元」（千分位）
    """
    if amount is None:
        return None
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    if v < 0:
        return None
    yi = 100_000_000.0
    wan = 10_000.0
    if v >= yi:
        return f"{v / yi:.2f}亿"
    if v >= wan:
        return f"{v / wan:.2f}万"
    return f"{v:,.0f}元"
