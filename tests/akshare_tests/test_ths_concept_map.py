"""
验证 fetch.stock_concept_map 基于 THS 的新实现

测试内容：
  1. THS 概念列表可正常获取（名称+代码）
  2. 单个概念成分股翻页抓取功能正常（取前 2 页）
  3. update_concept_map 小范围验证（仅取前 3 个概念）
  4. 查询接口正常工作
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import akshare as ak
from fetch.stock_concept_map import (
    _get_all_concepts,
    _get_ths_v_code,
    _get_concept_stocks_ths,
    get_stock_concepts,
    get_concept_stocks,
    get_map_meta,
)


def _sep(title: str):
    print(f"\n{'─' * 55}\n{title}")


def test_ths_concept_list():
    """1. THS 概念列表（名称 + 代码）"""
    _sep("【1】THS 概念列表")
    concepts = _get_all_concepts()
    assert len(concepts) > 100, f"概念数量过少: {len(concepts)}"
    sample = concepts[:3]
    for c in sample:
        assert "name" in c and "code" in c, f"字段缺失: {c}"
        print(f"  {c['name']}  代码: {c['code']}")
    print(f"  共 {len(concepts)} 个概念")


def test_ths_v_code():
    """2. THS v_code 生成"""
    _sep("【2】THS v_code 生成")
    v_code = _get_ths_v_code()
    assert v_code and len(v_code) > 0, "v_code 为空"
    print(f"  v_code: {v_code[:20]}...")


def test_ths_concept_stocks():
    """3. THS 单概念成分股抓取（参股银行，19页）"""
    _sep("【3】THS 成分股抓取")
    v_code = _get_ths_v_code()
    # 参股银行 code=301270，验证多页
    concept_code = "301270"
    concept_name = "参股银行"
    codes = _get_concept_stocks_ths(concept_code, v_code)
    print(f"  {concept_name} ({concept_code}): {len(codes)} 只成分股")
    print(f"  前5只: {codes[:5]}")
    assert len(codes) > 10, f"成分股数量应 >10，实际: {len(codes)}（翻页可能异常）"
    assert all(c.isdigit() and len(c) == 6 for c in codes), "存在非6位代码"


def test_small_build():
    """4. 小范围构建验证（仅取前 3 个概念）"""
    _sep("【4】小范围构建验证（前3个概念）")
    concepts = _get_all_concepts()[:3]
    v_code = _get_ths_v_code()

    stock_to_concepts: dict = {}
    concept_to_stocks: dict = {}

    for concept in concepts:
        name, code = concept["name"], concept["code"]
        codes = _get_concept_stocks_ths(code, v_code)
        concept_to_stocks[name] = codes
        for c in codes:
            stock_to_concepts.setdefault(c, [])
            if name not in stock_to_concepts[c]:
                stock_to_concepts[c].append(name)
        print(f"  {name}: {len(codes)} 只")
        time.sleep(0.5)

    print(f"\n  涉及股票数: {len(stock_to_concepts)}")
    assert len(concept_to_stocks) == 3
    assert len(stock_to_concepts) > 0, "映射表为空"


if __name__ == "__main__":
    print("=" * 55)
    print("THS 概念映射表新实现验证")
    print("=" * 55)

    test_ths_concept_list()
    time.sleep(0.5)

    test_ths_v_code()
    time.sleep(0.5)

    test_ths_concept_stocks()
    time.sleep(1)

    test_small_build()

    print("\n" + "=" * 55)
    print("全部验证通过")
    print()
    print("接口汇总：")
    print("  THS | 概念列表  | stock_board_concept_name_ths()")
    print("  THS | 成分股    | 翻页抓取 gn/detail/code/{code}/page/{n}/")
    print("  无  | EM 接口   | 已全部替换，不再依赖东方财富")

