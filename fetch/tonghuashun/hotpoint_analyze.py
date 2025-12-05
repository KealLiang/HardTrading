import os
import shutil
from datetime import datetime

import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd
import pywencai
from matplotlib.font_manager import FontProperties
from wordcloud import WordCloud

from config.holder import config
from utils.date_util import get_current_or_prev_trading_day

# 确保字体文件路径正确
font_path = 'fonts/微软雅黑.ttf'
save_path = "images/wordcloud/hot/"  # 指定保存目录
latest_save_path = "images/"  # 最新图片保存目录（每次更新覆盖）


def pd_setting():
    # 列名与数据对其显示
    pd.set_option('display.unicode.ambiguous_as_wide', True)
    pd.set_option('display.unicode.east_asian_width', True)
    pd.set_option('display.max_rows', None)  # 设置显示无限制行
    pd.set_option('display.max_columns', None)  # 设置显示无限制列
    pd.set_option('display.expand_frame_repr', False)  # 设置不折叠数据
    pd.set_option('display.max_colwidth', 100)


def hot_words_cloud(date: str = None, concept_only: bool = True):
    """
    生成每日A股热门股的概念词云图（或合并图）
    
    Args:
        date: 日期字符串，格式为 'YYYYMMDD'，默认为 None 表示最近一个交易日
        concept_only: 是否仅生成概念词云图，默认为 True。为 False 时生成概念+行业合并图
    """
    pd_setting()

    # 处理日期参数
    if date is None:
        # 获取最近一个交易日
        today = datetime.now().strftime('%Y%m%d')
        date = get_current_or_prev_trading_day(today)
        if date is None:
            print("无法获取最近的交易日")
            return

    try:
        print(f"正在处理日期: {date}")
        param = f"{date}涨停，非涉嫌信息披露违规且非立案调查且非ST"
        df = pywencai.get(query=param, sort_key='成交金额', sort_order='desc', loop=True, cookie=config.ths_cookie)

        selected_columns = ['股票代码', '股票简称', '最新价', '最新涨跌幅', '首次涨停时间[' + date + ']',
                            '连续涨停天数[' + date + ']', '涨停原因类别[' + date + ']']
        jj_df = df[selected_columns]

        # 按照'连板数'列进行降序排序
        sorted_temp_df = jj_df.sort_values(by='连续涨停天数[' + date + ']', ascending=False)

        # 根据开关生成对应的词云图
        if concept_only:
            generate_concept_cloud(date, sorted_temp_df)
        else:
            generate_combined_cloud(date, sorted_temp_df)

    except Exception as e:
        print(f"处理日期 {date} 时出错: {e}")


def generate_concept_cloud(date, sorted_temp_df):
    """
    仅生成概念词云图
    
    Args:
        date: 日期字符串
        sorted_temp_df: 排序后的股票数据
    """
    try:
        # 创建单个图像
        fig, ax = plt.subplots(figsize=(8, 5))

        # 创建字体对象
        font_prop = FontProperties(fname=font_path)

        # 生成概念词云
        concepts = sorted_temp_df['涨停原因类别[' + date + ']'].str.split('+').explode().reset_index(drop=True)
        concept_counts = concepts.value_counts().reset_index()
        concept_counts.columns = ['概念', '出现次数']

        # 检查概念数据是否可用
        has_concept_data = not concept_counts.empty and concept_counts['概念'].notna().any()

        if has_concept_data:
            concept_wordcloud = WordCloud(width=800, height=500, background_color='white',
                                          font_path=font_path).generate_from_frequencies(
                dict(zip(concept_counts['概念'].fillna('未知概念'), concept_counts['出现次数'])))

            # 显示概念词云
            ax.imshow(concept_wordcloud, interpolation='bilinear')
            ax.set_title(f'{date} 概念词云', fontsize=14, fontproperties=font_prop)
        else:
            ax.text(0.5, 0.5, '无概念数据可用',
                    fontsize=14, fontproperties=font_prop,
                    ha='center', va='center')
        ax.axis('off')

        # 确保目录存在
        os.makedirs(save_path, exist_ok=True)
        os.makedirs(latest_save_path, exist_ok=True)

        # 调整布局并保存到原始位置
        plt.tight_layout()
        original_file = f"{save_path}{date}_concept.png"
        plt.savefig(original_file, format='png', dpi=120,
                    bbox_inches='tight', pad_inches=0.1)
        plt.close()

        # 复制一份到 images/ 目录（固定文件名，每次覆盖）
        latest_file = f"{latest_save_path}hot_concept.png"
        shutil.copy2(original_file, latest_file)

        # 打印成功信息
        print(f"概念词云图已保存: {original_file}")
        print(f"最新概念词云图已更新: {latest_file}")

    except Exception as e:
        print(f"生成概念词云图时出错 {date}: {e}")
        # 确保图形被关闭，防止资源泄漏
        plt.close('all')


def generate_combined_cloud(date, sorted_temp_df):
    """
    生成概念+行业合并词云图
    
    Args:
        date: 日期字符串
        sorted_temp_df: 排序后的股票数据
    """
    try:
        # 创建一个包含两个子图的图像，减小图像尺寸
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

        # 创建字体对象
        font_prop = FontProperties(fname=font_path)

        # 生成概念词云
        concepts = sorted_temp_df['涨停原因类别[' + date + ']'].str.split('+').explode().reset_index(drop=True)
        concept_counts = concepts.value_counts().reset_index()
        concept_counts.columns = ['概念', '出现次数']

        # 检查概念数据是否可用
        has_concept_data = not concept_counts.empty and concept_counts['概念'].notna().any()

        if has_concept_data:
            concept_wordcloud = WordCloud(width=600, height=300, background_color='white',
                                          font_path=font_path).generate_from_frequencies(
                dict(zip(concept_counts['概念'].fillna('未知概念'), concept_counts['出现次数'])))

            # 在子图中显示概念词云
            ax1.imshow(concept_wordcloud, interpolation='bilinear')
            ax1.set_title('概念词云', fontsize=14, fontproperties=font_prop)
        else:
            ax1.text(0.5, 0.5, '无概念数据可用',
                     fontsize=14, fontproperties=font_prop,
                     ha='center', va='center')
        ax1.axis('off')

        # 生成行业词云
        sorted_temp_df['所属行业'] = sorted_temp_df['股票代码'].apply(get_industry_by_code)
        # 过滤掉可能的None值和空字符串
        industry_df = sorted_temp_df[sorted_temp_df['所属行业'].notna() & (sorted_temp_df['所属行业'] != '')]
        industry_counts = industry_df['所属行业'].value_counts()

        # 检查是否有行业数据可用
        if len(industry_counts) > 0:
            industry_wordcloud = WordCloud(
                font_path=font_path,
                background_color='white',
                width=600,
                height=300
            ).generate_from_frequencies(dict(industry_counts))

            # 在子图中显示行业词云
            ax2.imshow(industry_wordcloud, interpolation='bilinear')
            ax2.set_title('行业词云', fontsize=14, fontproperties=font_prop)
        else:
            ax2.text(0.5, 0.5, '无行业数据可用',
                     fontsize=14, fontproperties=font_prop,
                     ha='center', va='center')
        ax2.axis('off')

        # 确保目录存在
        os.makedirs(save_path, exist_ok=True)
        os.makedirs(latest_save_path, exist_ok=True)

        # 调整布局并保存到原始位置
        plt.tight_layout()
        original_file = f"{save_path}{date}_combined.png"
        plt.savefig(original_file, format='png', dpi=120,
                    bbox_inches='tight', pad_inches=0.1)
        plt.close()

        # 复制一份到 images/ 目录（固定文件名，每次覆盖）
        latest_file = f"{latest_save_path}hot_combined.png"
        shutil.copy2(original_file, latest_file)

        # 打印成功信息
        print(f"合并词云图已保存: {original_file}")
        print(f"最新合并词云图已更新: {latest_file}")

    except Exception as e:
        print(f"生成词云图时出错 {date}: {e}")
        # 确保图形被关闭，防止资源泄漏
        plt.close('all')


# 通过AKShare获取个股所属行业信息
def get_industry_by_code(code):
    try:
        code = code.split('.')[0]  # 去除股票代码后缀
        stock_info = ak.stock_individual_info_em(symbol=code)
        if not stock_info.empty:
            industry = stock_info.loc[6, 'value']
            # 检查industry是否为float类型，如果是则转为字符串或使用默认值
            if isinstance(industry, float):
                return "未知行业"
            return industry
    except Exception as e:
        print(f"获取股票{code}行业信息时出错: {e}")
        return "未知行业"
    return "未知行业"
