"""
简单测试：验证 THS 概念 300037（智能电网）的成分股抓取是否正常。

用法（先激活环境）：
    conda activate trading
    python -m tests.test_ths_concept_300037
"""

from fetch.stock_concept_map import _get_ths_v_code, _get_concept_stocks_ths


def main():
    concept_code = "300037"  # 智能电网
    # concept_code = "308606"  # 智慧政务

    print(f"开始测试 THS 概念 {concept_code} ...")
    v_code = _get_ths_v_code()
    print(f"v_code = {v_code!r}")

    codes = _get_concept_stocks_ths(concept_code, v_code)

    print(f"抓取到 {len(codes)} 只成分股：")
    # 为了避免输出太长，只看前 30 个
    print(codes[:30])


if __name__ == "__main__":
    main()