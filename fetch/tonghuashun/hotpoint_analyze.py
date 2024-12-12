import time
from datetime import datetime, timedelta

import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd
import pandas_market_calendars as mcal
import pywencai
from wordcloud import WordCloud

# 确保字体文件路径正确
font_path = 'fonts/微软雅黑.ttf'
save_path = "wordclouds/hot/"  # 指定保存目录


def pd_setting():
    # 列名与数据对其显示
    pd.set_option('display.unicode.ambiguous_as_wide', True)
    pd.set_option('display.unicode.east_asian_width', True)
    pd.set_option('display.max_rows', None)  # 设置显示无限制行
    pd.set_option('display.max_columns', None)  # 设置显示无限制列
    pd.set_option('display.expand_frame_repr', False)  # 设置不折叠数据
    pd.set_option('display.max_colwidth', 100)


def get_trading_day(start_date, end_date):
    cal = mcal.get_calendar('SSE')  # 上交所交易日历
    schedule = cal.schedule(start_date=start_date, end_date=end_date)
    return schedule.index.strftime('%Y%m%d').tolist()


def hot_words_cloud(days):
    pd_setting()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    trading_days = get_trading_day(start_date, end_date)
    # trading_days = ['20241202']
    for date in trading_days:
        try:
            print(f"正在处理日期: {date}")
            param = f"{date}涨停，非涉嫌信息披露违规且非立案调查且非ST，非科创板，非北交所"
            df = pywencai.get(query=param, sort_key='成交金额', sort_order='desc', loop=True)

            selected_columns = ['股票代码', '股票简称', '最新价', '最新涨跌幅', '首次涨停时间[' + date + ']',
                                '连续涨停天数[' + date + ']', '涨停原因类别[' + date + ']',
                                'a股市值(不含限售股)[' + date + ']', '涨停类型[' + date + ']']
            jj_df = df[selected_columns]

            # 按照'连板数'列进行降序排序
            sorted_temp_df = jj_df.sort_values(by='连续涨停天数[' + date + ']', ascending=False)

            # 概念词云
            generate_concept_cloud(date, sorted_temp_df)

            # 行业词云
            generate_industry_cloud(date, sorted_temp_df)

            # 防止高频拉取被拦截，稍微 sleep 一下
            time.sleep(1.5)

        except Exception as e:
            print(f"处理日期 {date} 时出错: {e}")


def generate_industry_cloud(date, sorted_temp_df):
    # 为涨停个股数据添加所属行业列
    sorted_temp_df['所属行业'] = sorted_temp_df['股票代码'].apply(get_industry_by_code)
    # 统计各行业出现的频次，用于生成词云图
    industry_counts = sorted_temp_df['所属行业'].value_counts()
    # 生成词云图
    wordcloud = WordCloud(
        font_path=font_path,  # 设置中文字体路径，确保能正确显示中文，需提前下载好字体文件
        background_color='white',
        width=800,
        height=600
    ).generate_from_frequencies(
        dict(industry_counts))
    # 保存词云图到文件
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    plt.savefig(f"{save_path}{date}_industry.png", format='png')
    plt.close()
    # 打印成功信息
    print(f"词云图已保存: {date}_industry.png")


def generate_concept_cloud(date, sorted_temp_df):
    # 按照 '+' 分割涨停原因类别
    concepts = sorted_temp_df['涨停原因类别[' + date + ']'].str.split('+').explode().reset_index(drop=True)
    # 统计每个概念的出现次数
    concept_counts = concepts.value_counts().reset_index()
    concept_counts.columns = ['概念', '出现次数']
    # 生成词云
    wordcloud = WordCloud(width=800, height=400, background_color='white',
                          font_path=font_path).generate_from_frequencies(
        dict(zip(concept_counts['概念'], concept_counts['出现次数'])))
    # 保存词云图到文件
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    plt.savefig(f"{save_path}{date}_concept.png", format='png')
    plt.close()
    # 打印成功信息
    print(f"词云图已保存: {date}_concept.png")


# 通过AKShare获取个股所属行业信息
def get_industry_by_code(code):
    code = code.split('.')[0]  # 去除股票代码后缀
    stock_info = ak.stock_individual_info_em(symbol=code)
    if not stock_info.empty:
        return stock_info.loc[6, 'value']
    return None
