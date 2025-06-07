import akshare as ak
import pandas as pd
import logging


def fetch_and_save_stock_concept(concept_list=None, industry_list=None, output_path="A股股票概念与行业.xlsx"):
    """
    拉取 A 股股票的概念和行业数据并保存为 Excel 文件。

    :param concept_list: 要筛选的概念名称列表（默认 None，表示拉取所有概念）。
    :param industry_list: 要筛选的行业名称列表（默认 None，表示拉取所有行业）。
    :param output_path: 输出的 Excel 文件路径（默认 "A股股票概念与行业.xlsx"）。
    """
    # 步骤 1: 获取所有概念和行业的板块名称
    logging.info("开始获取概念和行业的板块数据...")
    concept_board_df = ak.stock_board_concept_name_em()
    industry_board_df = ak.stock_board_industry_name_em()

    # 筛选特定概念和行业
    if concept_list is None:
        concept_list = concept_board_df['板块名称'].tolist()
    else:
        concept_list = [concept for concept in concept_list if concept in concept_board_df['板块名称'].tolist()]

    if industry_list is None:
        industry_list = industry_board_df['板块名称'].tolist()
    else:
        industry_list = [industry for industry in industry_list if industry in industry_board_df['板块名称'].tolist()]

    logging.info(f"将处理 {len(concept_list)} 个概念和 {len(industry_list)} 个行业。")

    # 初始化股票-概念与股票-行业的映射
    stock_concept_map = {}
    stock_industry_map = {}
    stock_name_map = {}  # 保存股票代码与名称的映射

    # 步骤 2: 遍历每个概念板块，获取成分股
    logging.info("开始拉取概念板块的成分股...")
    for concept in concept_list:
        logging.info(f"正在处理概念：{concept}")
        concept_stocks = ak.stock_board_concept_cons_em(symbol=concept)
        for _, row in concept_stocks.iterrows():
            stock_code = row['代码']
            stock_name = row['名称']
            stock_name_map[stock_code] = stock_name
            if stock_code not in stock_concept_map:
                stock_concept_map[stock_code] = []
            stock_concept_map[stock_code].append(concept)

    # 遍历每个行业板块，获取成分股
    logging.info("开始拉取行业板块的成分股...")
    for industry in industry_list:
        logging.info(f"正在处理行业：{industry}")
        industry_stocks = ak.stock_board_industry_cons_em(symbol=industry)
        for _, row in industry_stocks.iterrows():
            stock_code = row['代码']
            stock_name = row['名称']
            stock_name_map[stock_code] = stock_name
            if stock_code not in stock_industry_map:
                stock_industry_map[stock_code] = []
            stock_industry_map[stock_code].append(industry)

    # 步骤 3: 构造股票-概念的 DataFrame
    logging.info("开始构造概念数据表...")
    concept_columns = concept_list
    concept_df = pd.DataFrame(index=stock_concept_map.keys(), columns=concept_columns)
    concept_df = concept_df.fillna(0)

    # 填充概念 DataFrame
    for stock, concepts in stock_concept_map.items():
        for concept in concepts:
            concept_df.loc[stock, concept] = 1

    # 构造股票-行业的 DataFrame
    logging.info("开始构造行业数据表...")
    industry_columns = industry_list
    industry_df = pd.DataFrame(index=stock_industry_map.keys(), columns=industry_columns)
    industry_df = industry_df.fillna(0)

    # 填充行业 DataFrame
    for stock, industries in stock_industry_map.items():
        for industry in industries:
            industry_df.loc[stock, industry] = 1

    # 替换索引为 股票code_股票名称
    logging.info("更新索引为 股票code_股票名称...")
    concept_df.index = [f"{code}_{stock_name_map[code]}" for code in concept_df.index]
    industry_df.index = [f"{code}_{stock_name_map[code]}" for code in industry_df.index]

    # 步骤 4: 保存到 Excel 文件
    logging.info("开始保存数据到 Excel 文件...")
    with pd.ExcelWriter(output_path) as writer:
        concept_df.to_excel(writer, sheet_name="概念")
        industry_df.to_excel(writer, sheet_name="行业")

    logging.info(f"数据已成功保存到 {output_path}")


# 示例用法
if __name__ == "__main__":
    # 示例：只拉取特定的概念和行业
    fetch_and_save_stock_concept(
        concept_list=["云游戏", "新能源车"],
        industry_list=["银行", "房地产"],
        output_path="筛选的概念与行业数据.xlsx"
    )
