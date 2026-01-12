import akshare as ak


def get_stock_concept(stock_code):
    """
    根据股票代码获取股票的题材概念（适配 akshare 1.16.98 版本，接口无参数）

    参数:
        stock_code (str): 股票代码，如 "600519"（贵州茅台）、"000858"（五粮液）

    返回:
        dict: 包含股票名称和题材概念的字典
    """
    try:
        # 1. 获取全市场所有股票的题材概念数据（接口无参数）
        concept_df = ak.stock_board_concept_name_ths()

        # 2. 检查数据是否为空
        if concept_df.empty:
            return {"error": "获取全市场题材数据失败，可能是网络或数据源问题"}

        # 3. 根据股票代码筛选对应数据（代码字段名为 '代码'）
        stock_data = concept_df[concept_df['code'] == stock_code]

        # 4. 处理筛选结果
        if stock_data.empty:
            return {"error": f"未找到股票代码 {stock_code} 的题材概念信息，请检查代码是否正确"}

        # 5. 提取并格式化信息
        concepts = stock_data.iloc[0]['name'].split(';')  # 字段名是 '概念' 而非 '概念题材'

        return {
            "股票代码": stock_code,
            "题材概念": concepts
        }

    except Exception as e:
        # 详细打印异常，方便排查
        print(f"异常类型：{type(e).__name__}")
        print(f"异常详情：{str(e)}")
        return {"error": f"获取失败: {str(e)}"}


# 测试示例
if __name__ == "__main__":
    # 可替换为任意有效股票代码
    test_code = "600519"  # 贵州茅台
    # test_code = "000858"  # 五粮液
    # test_code = "300750"  # 宁德时代

    result = get_stock_concept(test_code)

    # 打印结果
    if "error" in result:
        print(f"❌ {result['error']}")
    else:
        print(f"✅ 股票代码：{result['股票代码']}")
        print("✅ 题材概念：")
        for idx, concept in enumerate(result['题材概念'], 1):
            print(f"   {idx}. {concept}")