import time
from datetime import datetime, timedelta

import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd
import pandas_market_calendars as mcal
import pywencai
from wordcloud import WordCloud
from matplotlib.font_manager import FontProperties
from config.holder import config

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
            df = pywencai.get(query=param, sort_key='成交金额', sort_order='desc', loop=True, cookie=config.ths_cookie)

            selected_columns = ['股票代码', '股票简称', '最新价', '最新涨跌幅', '首次涨停时间[' + date + ']',
                                '连续涨停天数[' + date + ']', '涨停原因类别[' + date + ']',
                                'a股市值(不含限售股)[' + date + ']', '涨停类型[' + date + ']']
            jj_df = df[selected_columns]

            # 按照'连板数'列进行降序排序
            sorted_temp_df = jj_df.sort_values(by='连续涨停天数[' + date + ']', ascending=False)

            # 生成合并的词云图
            generate_combined_cloud(date, sorted_temp_df)

            # 防止高频拉取被拦截，稍微 sleep 一下
            time.sleep(1.5)

        except Exception as e:
            print(f"处理日期 {date} 时出错: {e}")


def generate_combined_cloud(date, sorted_temp_df):
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
        
        # 调整布局并保存，降低DPI
        plt.tight_layout()
        plt.savefig(f"{save_path}{date}_combined.png", format='png', dpi=120, 
                    bbox_inches='tight', pad_inches=0.1)
        plt.close()
        
        # 打印成功信息
        print(f"合并词云图已保存: {date}_combined.png")
        
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
