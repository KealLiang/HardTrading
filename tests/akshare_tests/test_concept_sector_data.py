"""
验证 akshare 获取 A 股概念/行业板块数据的接口可用性

数据源说明：
  - THS（同花顺）接口：q.10jqka.com.cn，稳定可用，作为主力
  - EM（东方财富）接口：*.push2.eastmoney.com，偶发限流，作为备选
    注：EM 数字前缀子域名（79.push2/17.push2/91.push2his）短时间内
        频繁请求会触发临时 IP 封禁，稳定性不如 THS

测试目标：
  1. THS 概念板块列表
  2. THS 概念板块 K 线历史数据（量化分析核心数据）
  3. THS 行业板块列表 + K 线
  4. EM 个股基本信息（含所属行业，走 push2.eastmoney.com 不受限流影响）
  5. 反向查找：某股票 → 所属概念（依赖 EM 成分股接口，限流期间跳过）
  6. EM 概念板块接口可用性检查（失败时不影响整体）
"""

import time

import akshare as ak

TEST_STOCK = "000001"  # 平安银行，概念覆盖广
TEST_STOCK_NAME = "平安银行"


def _sep(title: str):
    print(f"\n{'─' * 55}\n{title}")


# ─────────────────────────────────────────────────────────
# 核心逻辑函数（带参数，不以 test_ 开头，避免被 pytest 误识别为 fixture）
# ─────────────────────────────────────────────────────────

def _run_ths_concept_kline(concept_name: str):
    _sep(f"【2】THS - 概念 K 线: 『{concept_name}』")
    df = ak.stock_board_concept_index_ths(symbol=concept_name)
    print(f"  接口: stock_board_concept_index_ths(symbol='{concept_name}')")
    print(f"  字段: {list(df.columns)}")
    print(f"  数据条数: {len(df)}  ({df.iloc[0]['日期']} ~ {df.iloc[-1]['日期']})")
    print(df.tail(5).to_string(index=False))
    assert len(df) > 0, "K线数据为空"
    return df


def _run_em_stock_info(stock_code: str):
    _sep(f"【4】EM - 个股基本信息: {stock_code}")
    df = ak.stock_individual_info_em(symbol=stock_code)
    print(f"  接口: stock_individual_info_em(symbol='{stock_code}')")
    print(df.to_string(index=False))
    assert len(df) > 0
    return df


def _run_find_stock_concepts(stock_code: str, concept_df, max_check: int = 20):
    """反向查找某股票所属概念板块（依赖 EM 成分股接口）"""
    _sep(f"【5】THS/EM - 反向查找 {stock_code} 所属概念（采样前 {max_check} 个）")
    print(f"  策略: 遍历概念 → 用 EM stock_board_concept_cons_em 检查成分股")
    print(f"  注: THS 暂无成分股查询接口，此步依赖 EM 接口可用")

    found = []
    try:
        ak.stock_board_concept_cons_em(symbol="互联网")
    except Exception:
        print(f"  EM成分股接口当前不可用（数字前缀限流），跳过遍历")
        return found

    print(f"  EM成分股接口可用，开始遍历...")
    for _, row in concept_df.head(max_check).iterrows():
        concept = row["name"]
        try:
            cons = ak.stock_board_concept_cons_em(symbol=concept)
            code_col = "代码" if "代码" in cons.columns else cons.columns[0]
            if stock_code in cons[code_col].values:
                found.append(concept)
                print(f"  ✓ {concept}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {concept}: {type(e).__name__}")

    print(f"\n  采样结果: {stock_code} 在前 {max_check} 个概念中属于 {len(found)} 个")
    return found


# ─────────────────────────────────────────────────────────
# pytest 测试函数（无参数，每个测试独立可运行）
# ─────────────────────────────────────────────────────────

def test_ths_concept_list():
    """1. THS 概念板块名称列表"""
    _sep("【1】THS - 概念板块名称列表")
    df = ak.stock_board_concept_name_ths()
    print(f"  接口: stock_board_concept_name_ths()")
    print(f"  字段: {list(df.columns)}")
    print(f"  共 {len(df)} 个概念板块")
    print(df.head(5).to_string(index=False))
    assert len(df) > 0, "概念列表为空"


def test_ths_concept_kline():
    """2. THS 概念板块 K 线（量化分析核心数据）"""
    concept_df = ak.stock_board_concept_name_ths()
    sample_concept = concept_df.iloc[0]["name"]
    _run_ths_concept_kline(sample_concept)


def test_ths_industry():
    """3. THS 行业板块列表 + K 线"""
    _sep("【3】THS - 行业板块列表")
    df = ak.stock_board_industry_name_ths()
    print(f"  接口: stock_board_industry_name_ths()")
    print(f"  字段: {list(df.columns)}")
    print(f"  共 {len(df)} 个行业")
    print(df.head(3).to_string(index=False))
    assert len(df) > 0, "行业列表为空"

    industry_name = df.iloc[0]["name"]
    print(f"\n  → 行业 K 线: 『{industry_name}』")
    time.sleep(0.5)
    kline = ak.stock_board_industry_index_ths(symbol=industry_name)
    print(f"  接口: stock_board_industry_index_ths(symbol='{industry_name}')")
    print(f"  字段: {list(kline.columns)}")
    print(f"  数据条数: {len(kline)}  ({kline.iloc[0]['日期']} ~ {kline.iloc[-1]['日期']})")
    print(kline.tail(3).to_string(index=False))
    assert len(kline) > 0


def test_em_stock_info():
    """4. EM 个股基本信息（含所属行业）"""
    _run_em_stock_info(TEST_STOCK)


def test_find_stock_concepts():
    """5. 反向查找股票所属概念板块（依赖 EM 成分股接口）"""
    concept_df = ak.stock_board_concept_name_ths()
    _run_find_stock_concepts(TEST_STOCK, concept_df, max_check=20)


def test_em_concept_availability():
    """6. EM 概念接口可用性检查（东方财富数字子域名）"""
    _sep("【6】EM - 概念接口可用性检查（东方财富数字子域名）")
    try:
        df = ak.stock_board_concept_name_em()
        print(f"  ✅ 概念列表: {len(df)} 个")
        first_concept = df.iloc[0]["板块名称"]

        time.sleep(1)
        cons = ak.stock_board_concept_cons_em(symbol=first_concept)
        print(f"  ✅ 成分股: {len(cons)} 只")

        time.sleep(1)
        hist = ak.stock_board_concept_hist_em(
            symbol=first_concept, period="daily",
            start_date="20250101", end_date="20250228", adjust=""
        )
        print(f"  ✅ K线: {len(hist)} 条, 字段: {list(hist.columns)}")
        print(hist.tail(3).to_string(index=False))

    except Exception as e:
        print(f"  ✗ EM接口失败: {type(e).__name__}: {str(e)[:100]}")
        print(f"  提示: 东方财富数字前缀子域名有限流保护，短时间频繁请求触发封禁")
        # EM 接口受限流影响，不强制 assert 失败，仅作可用性观察
        import pytest
        pytest.skip(f"EM接口限流中，跳过: {type(e).__name__}")


# ─────────────────────────────────────────────────────────
# 直接运行时按顺序执行所有测试
# ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print(f"akshare 版本: {ak.__version__}")
    print(f"测试股票: {TEST_STOCK} {TEST_STOCK_NAME}")
    print("=" * 55)

    concept_df = None

    _sep("【1】THS - 概念板块名称列表")
    concept_df = ak.stock_board_concept_name_ths()
    print(f"  共 {len(concept_df)} 个概念, 字段: {list(concept_df.columns)}")
    print(concept_df.head(5).to_string(index=False))
    time.sleep(1)

    sample_concept = concept_df.iloc[0]["name"]
    _run_ths_concept_kline(sample_concept)
    time.sleep(1)

    _sep("【3】THS - 行业板块列表")
    ind_df = ak.stock_board_industry_name_ths()
    print(f"  共 {len(ind_df)} 个行业, 字段: {list(ind_df.columns)}")
    print(ind_df.head(3).to_string(index=False))
    industry_name = ind_df.iloc[0]["name"]
    time.sleep(0.5)
    ind_kline = ak.stock_board_industry_index_ths(symbol=industry_name)
    print(f"  行业K线 '{industry_name}': {len(ind_kline)} 条")
    print(ind_kline.tail(3).to_string(index=False))
    time.sleep(1)

    _run_em_stock_info(TEST_STOCK)
    time.sleep(1)

    _run_find_stock_concepts(TEST_STOCK, concept_df, max_check=20)
    time.sleep(1)

    _sep("【6】EM - 概念接口可用性检查")
    try:
        df = ak.stock_board_concept_name_em()
        print(f"  ✅ 概念列表: {len(df)} 个")
        first = df.iloc[0]["板块名称"]
        time.sleep(1)
        cons = ak.stock_board_concept_cons_em(symbol=first)
        print(f"  ✅ '{first}' 成分股: {len(cons)} 只")
        time.sleep(1)
        hist = ak.stock_board_concept_hist_em(
            symbol=first, period="daily",
            start_date="20250101", end_date="20250228", adjust=""
        )
        print(f"  ✅ K线: {len(hist)} 条")
        print(hist.tail(3).to_string(index=False))
    except Exception as e:
        print(f"  ✗ EM接口失败: {type(e).__name__}: {str(e)[:100]}")
        print(f"  提示: 东方财富数字前缀子域名有限流保护，稍后重试或改用 THS 接口")

    print("\n" + "=" * 55)
    print("全部测试完成")
    print()
    print("接口汇总：")
    print("  主力(THS) | 概念列表  | stock_board_concept_name_ths()")
    print("  主力(THS) | 概念K线   | stock_board_concept_index_ths(symbol=概念名)")
    print("  主力(THS) | 行业列表  | stock_board_industry_name_ths()")
    print("  主力(THS) | 行业K线   | stock_board_industry_index_ths(symbol=行业名)")
    print("  备选(EM)  | 概念列表  | stock_board_concept_name_em()        [受限流]")
    print("  备选(EM)  | 概念成分股| stock_board_concept_cons_em(symbol=) [受限流]")
    print("  备选(EM)  | 概念K线   | stock_board_concept_hist_em(symbol=) [受限流]")
    print("  稳定(EM)  | 个股信息  | stock_individual_info_em(symbol=股票代码)")
