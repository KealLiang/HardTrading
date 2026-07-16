"""股票代码格式转换（监控用 6 位 ↔ QMT 用 600000.SH）。"""


def to_qmt_code(symbol: str) -> str:
    code = str(symbol).strip().upper()
    if "." in code:
        return code
    if code.startswith(("SH", "SZ")) and len(code) >= 8:
        prefix, num = code[:2], code[2:]
        return f"{num}.{prefix}"
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    raise ValueError(f"无法识别交易所: {symbol}")


def to_symbol6(qmt_or_any: str) -> str:
    s = str(qmt_or_any).strip().upper()
    if "." in s:
        return s.split(".", 1)[0]
    if s.startswith(("SH", "SZ")) and len(s) >= 8:
        return s[2:8]
    return s[-6:] if len(s) >= 6 else s
