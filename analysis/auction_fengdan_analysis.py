"""
集合竞价封单数据分析模块

提供竞价封单数据的分析和可视化功能，包括：
1. 时间点对比分析
2. 封单变化趋势分析
3. 竞价阶段热点识别
4. 数据可视化图表

作者：Trading System
创建时间：2025-01-14
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import numpy as np
from utils.date_util import get_prev_trading_day, is_trading_day

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False


class AuctionFengdanAnalyzer:
    """集合竞价封单数据分析器"""
    
    def __init__(self, data_dir: str = "data/auction_fengdan"):
        """
        初始化分析器

        Args:
            data_dir: 数据目录
        """
        self.data_dir = data_dir
        self.daily_dir = os.path.join(data_dir, "daily")

        # 分析结果保存到images/auction目录
        self.images_dir = os.path.join("images", "auction")
        self.summary_dir = os.path.join("images", "auction", "summary")

        # 确保目录存在
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.summary_dir, exist_ok=True)

    def get_current_trading_day(self) -> str:
        """获取当前交易日"""
        today = datetime.now().strftime('%Y%m%d')
        if is_trading_day(today):
            return today
        else:
            return get_prev_trading_day(today)
    
    def load_daily_data(self, date_str: str) -> pd.DataFrame:
        """
        加载指定日期的完整封单数据
        
        Args:
            date_str: 日期字符串，格式YYYYMMDD
            
        Returns:
            封单数据DataFrame
        """
        file_path = os.path.join(self.daily_dir, f"{date_str}_fengdan_full.csv")
        
        if not os.path.exists(file_path):
            print(f"数据文件不存在: {file_path}")
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            return df
        except Exception as e:
            print(f"读取数据文件失败: {e}")
            return pd.DataFrame()
    
    def load_timepoint_data(self, date_str: str, timepoint: str) -> pd.DataFrame:
        """
        加载指定日期和时间点的封单数据
        
        Args:
            date_str: 日期字符串
            timepoint: 时间点，如'0915', '0920', '0925'
            
        Returns:
            时间点封单数据
        """
        file_path = os.path.join(self.daily_dir, f"{date_str}_{timepoint}_fengdan.csv")
        
        if not os.path.exists(file_path):
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            return df
        except Exception as e:
            print(f"读取时间点数据失败: {e}")
            return pd.DataFrame()
    
    def analyze_daily_summary(self, date_str: str) -> Dict:
        """
        分析每日封单汇总数据
        
        Args:
            date_str: 日期字符串
            
        Returns:
            分析结果字典
        """
        df = self.load_daily_data(date_str)
        
        if df.empty:
            return {}
        
        # 基础统计
        total_stocks = len(df)
        total_fengdan = df['封板资金'].sum()
        avg_fengdan = df['封板资金'].mean()
        median_fengdan = df['封板资金'].median()
        
        # 时间段分布
        time_distribution = df['封板时间段'].value_counts().to_dict()
        
        # 竞价阶段分析（使用新的识别方法）
        from fetch.auction_fengdan_data import AuctionFengdanCollector
        temp_collector = AuctionFengdanCollector()
        auction_stocks = temp_collector.get_auction_period_stocks(date_str)

        auction_count = len(auction_stocks)
        auction_fengdan_total = 0
        auction_zt_count = 0
        auction_dt_count = 0
        auction_zt_amount = 0
        auction_dt_amount = 0

        if not auction_stocks.empty:
            # 分离涨停和跌停
            auction_zt = auction_stocks[auction_stocks.get('涨跌类型', '') == '涨停'] if '涨跌类型' in auction_stocks.columns else auction_stocks
            auction_dt = auction_stocks[auction_stocks.get('涨跌类型', '') == '跌停'] if '涨跌类型' in auction_stocks.columns else pd.DataFrame()

            auction_zt_count = len(auction_zt)
            auction_dt_count = len(auction_dt)

            # 计算金额
            if not auction_zt.empty and '封板资金' in auction_zt.columns:
                auction_zt_amount = auction_zt['封板资金'].sum()
            if not auction_dt.empty and '封单资金' in auction_dt.columns:
                auction_dt_amount = auction_dt['封单资金'].sum()

            auction_fengdan_total = auction_zt_amount + auction_dt_amount
        
        # 行业分布
        industry_distribution = df['所属行业'].value_counts().head(10).to_dict()
        
        # 封单额分布
        fengdan_ranges = {
            '1亿以上': len(df[df['封板资金'] >= 100000000]),
            '5000万-1亿': len(df[(df['封板资金'] >= 50000000) & (df['封板资金'] < 100000000)]),
            '1000万-5000万': len(df[(df['封板资金'] >= 10000000) & (df['封板资金'] < 50000000)]),
            '1000万以下': len(df[df['封板资金'] < 10000000])
        }

        # 市场情绪分析
        market_sentiment = self._analyze_market_sentiment(df)
        
        analysis_result = {
            '日期': date_str,
            '分析时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '涨停板总数': total_stocks,
            '封单总额': total_fengdan,
            '平均封单额': avg_fengdan,
            '封单额中位数': median_fengdan,
            '竞价阶段封板数': auction_count,
            '竞价阶段涨停数': auction_zt_count,
            '竞价阶段跌停数': auction_dt_count,
            '竞价阶段封单总额': auction_fengdan_total,
            '竞价阶段涨停金额': auction_zt_amount,
            '竞价阶段跌停金额': auction_dt_amount,
            '竞价阶段占比': (auction_fengdan_total / total_fengdan * 100) if total_fengdan > 0 else 0,
            '时间段分布': time_distribution,
            '行业分布': industry_distribution,
            '封单额分布': fengdan_ranges,
            '市场情绪': market_sentiment
        }
        
        return analysis_result

    def _analyze_market_sentiment(self, df: pd.DataFrame) -> dict:
        """
        分析市场情绪

        Args:
            df: 涨跌停数据

        Returns:
            市场情绪分析结果
        """
        if df.empty:
            return {}

        sentiment = {}

        # 1. 市值分布分析
        if '流通市值' in df.columns:
            # 转换为亿元
            df_copy = df.copy()
            df_copy['流通市值_亿'] = df_copy['流通市值'] / 1e8

            sentiment['小盘股'] = len(df_copy[df_copy['流通市值_亿'] < 100])  # <100亿
            sentiment['中盘股'] = len(df_copy[(df_copy['流通市值_亿'] >= 100) & (df_copy['流通市值_亿'] < 500)])  # 100-500亿
            sentiment['大盘股'] = len(df_copy[df_copy['流通市值_亿'] >= 500])  # >500亿

            # 平均流通市值
            sentiment['平均流通市值'] = df_copy['流通市值_亿'].mean()

        # 2. 换手率分析
        if '换手率' in df.columns:
            sentiment['高换手率'] = len(df[df['换手率'] > 5])  # >5%
            sentiment['低换手率'] = len(df[df['换手率'] <= 5])  # <=5%
            sentiment['平均换手率'] = df['换手率'].mean()

        # 3. 封板强度分析
        if '封板资金' in df.columns and '流通市值' in df.columns:
            df_copy = df.copy()
            df_copy['封板强度'] = df_copy['封板资金'] / df_copy['流通市值'] * 100  # 封板资金占流通市值比例
            sentiment['平均封板强度'] = df_copy['封板强度'].mean()
            sentiment['强封板'] = len(df_copy[df_copy['封板强度'] > 1])  # >1%
            sentiment['弱封板'] = len(df_copy[df_copy['封板强度'] <= 1])  # <=1%

        return sentiment

    def compare_timepoints(self, date_str: str) -> pd.DataFrame:
        """
        对比同一天不同时间点的封单数据
        
        Args:
            date_str: 日期字符串
            
        Returns:
            时间点对比结果
        """
        timepoints = ['0915', '0920', '0925']
        comparison_data = []
        
        for tp in timepoints:
            df = self.load_timepoint_data(date_str, tp)
            if not df.empty:
                summary = {
                    '时间点': f"{tp[:2]}:{tp[2:]}",
                    '涨停板数量': len(df),
                    '封单总额': df['封板资金'].sum(),
                    '平均封单额': df['封板资金'].mean(),
                    '最大封单额': df['封板资金'].max(),
                    '竞价阶段封板数': len(df[df['封板时间段'] == "竞价阶段(09:15-09:25)"])
                }
                comparison_data.append(summary)
        
        if not comparison_data:
            return pd.DataFrame()
        
        comparison_df = pd.DataFrame(comparison_data)
        
        # 保存对比结果
        output_file = os.path.join(self.analysis_dir, f"{date_str}_timepoint_comparison.csv")
        comparison_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        return comparison_df
    
    def plot_fengdan_distribution(self, date_str: str = None, save_plot: bool = True, show_plot: bool = False):
        """
        绘制封单额分布图（涨停+跌停综合）

        Args:
            date_str: 日期字符串，默认为当前交易日
            save_plot: 是否保存图片
            show_plot: 是否显示图片（默认不显示，避免阻塞）

        Returns:
            str: 保存的图片文件路径，如果没有保存则返回None
        """
        if date_str is None:
            date_str = self.get_current_trading_day()

        # 尝试加载综合数据
        from fetch.auction_fengdan_data import AuctionFengdanCollector
        collector = AuctionFengdanCollector()
        df = collector.get_combined_fengdan_data(date_str)

        if df.empty:
            print(f"没有 {date_str} 的数据")
            return None

        # 分离涨停和跌停数据
        zt_df = df[df['涨跌类型'] == '涨停'].copy() if '涨跌类型' in df.columns else df.copy()
        dt_df = df[df['涨跌类型'] == '跌停'].copy() if '涨跌类型' in df.columns else pd.DataFrame()

        # 创建图表 (2x3布局)
        fig, axes = plt.subplots(2, 3, figsize=(20, 12))

        # 格式化日期显示
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            formatted_date = date_obj.strftime('%Y年%m月%d日')
        except:
            formatted_date = date_str

        fig.suptitle(f'{formatted_date} 涨跌停封单数据分析', fontsize=16, fontweight='bold')

        # 1. 竞价涨跌停分析
        # 获取竞价阶段数据
        from fetch.auction_fengdan_data import AuctionFengdanCollector
        temp_collector = AuctionFengdanCollector()
        auction_data = temp_collector.get_auction_period_stocks(date_str)

        if not auction_data.empty:
            # 分离竞价阶段的涨停和跌停
            auction_zt = auction_data[auction_data.get('涨跌类型', '') == '涨停'] if '涨跌类型' in auction_data.columns else auction_data
            auction_dt = auction_data[auction_data.get('涨跌类型', '') == '跌停'] if '涨跌类型' in auction_data.columns else pd.DataFrame()

            # 计算金额
            zt_amount = 0
            dt_amount = 0

            if not auction_zt.empty:
                zt_amount = auction_zt['封板资金'].sum() / 1e8 if '封板资金' in auction_zt.columns else 0
            if not auction_dt.empty:
                dt_amount = auction_dt['封单资金'].sum() / 1e8 if '封单资金' in auction_dt.columns else 0

            categories = ['竞价涨停', '竞价跌停']
            amounts = [zt_amount, dt_amount]
            colors = ['red', 'green']

            axes[0, 0].bar(categories, amounts, color=colors, alpha=0.7)
            axes[0, 0].set_title('竞价涨跌停分析')
            axes[0, 0].set_ylabel('封单金额 (亿元)')

            # 在柱子上显示数值和股票数量
            max_amount = max(amounts) if amounts else 1
            axes[0, 0].text(0, zt_amount + max_amount * 0.02, f'{zt_amount:.1f}亿\n({len(auction_zt)}只)',
                           ha='center', va='bottom', fontweight='bold')
            axes[0, 0].text(1, dt_amount + max_amount * 0.02, f'{dt_amount:.1f}亿\n({len(auction_dt)}只)',
                           ha='center', va='bottom', fontweight='bold')
        else:
            axes[0, 0].text(0.5, 0.5, '无竞价阶段封板数据', ha='center', va='center', transform=axes[0, 0].transAxes)
            axes[0, 0].set_title('竞价涨跌停分析')

        # 2. 时间段分布饼图
        if not zt_df.empty and '封板时间段' in zt_df.columns:
            time_dist = zt_df['封板时间段'].value_counts()
            axes[0, 1].pie(time_dist.values, labels=time_dist.index, autopct='%1.1f%%', startangle=90)
            axes[0, 1].set_title('涨停封板时间段分布')
        else:
            axes[0, 1].text(0.5, 0.5, '无时间段数据', ha='center', va='center', transform=axes[0, 1].transAxes)
            axes[0, 1].set_title('涨停封板时间段分布')

        # 3. 行业分布条形图
        if not zt_df.empty and '所属行业' in zt_df.columns:
            industry_dist = zt_df['所属行业'].value_counts().head(10)
            axes[1, 0].barh(range(len(industry_dist)), industry_dist.values, color='skyblue')
            axes[1, 0].set_yticks(range(len(industry_dist)))
            axes[1, 0].set_yticklabels(industry_dist.index, fontsize=9)
            axes[1, 0].set_title('涨停行业分布 (前10名)')
            axes[1, 0].set_xlabel('股票数量')
        else:
            axes[1, 0].text(0.5, 0.5, '无行业数据', ha='center', va='center', transform=axes[1, 0].transAxes)
            axes[1, 0].set_title('涨停行业分布')

        # 3. 市值分布分析
        if not zt_df.empty and '流通市值' in zt_df.columns:
            zt_df_copy = zt_df.copy()
            zt_df_copy['流通市值_亿'] = zt_df_copy['流通市值'] / 1e8

            small_cap = len(zt_df_copy[zt_df_copy['流通市值_亿'] < 100])
            mid_cap = len(zt_df_copy[(zt_df_copy['流通市值_亿'] >= 100) & (zt_df_copy['流通市值_亿'] < 500)])
            large_cap = len(zt_df_copy[zt_df_copy['流通市值_亿'] >= 500])

            categories = ['小盘股\n(<100亿)', '中盘股\n(100-500亿)', '大盘股\n(>500亿)']
            counts = [small_cap, mid_cap, large_cap]
            colors = ['lightcoral', 'gold', 'lightblue']

            axes[0, 2].bar(categories, counts, color=colors, alpha=0.7)
            axes[0, 2].set_title('市值分布分析')
            axes[0, 2].set_ylabel('股票数量')

            # 显示数值
            for i, count in enumerate(counts):
                axes[0, 2].text(i, count + 0.5, str(count), ha='center', va='bottom', fontweight='bold')
        else:
            axes[0, 2].text(0.5, 0.5, '无市值数据', ha='center', va='center', transform=axes[0, 2].transAxes)
            axes[0, 2].set_title('市值分布分析')

        # 4. 封单额排名前15（涨停+跌停）
        top_zt = zt_df.nlargest(12, '封板资金') if not zt_df.empty else pd.DataFrame()
        top_dt = dt_df.nsmallest(3, '封板资金') if not dt_df.empty else pd.DataFrame()

        # 合并显示
        display_data = []
        colors_list = []

        # 添加涨停数据
        for _, row in top_zt.iterrows():
            code = str(row['代码']).zfill(6)
            name = row['名称']
            amount = abs(row['封板资金']) / 1e8
            display_data.append((f"{code}\n{name}", amount))
            colors_list.append('red')

        # 添加跌停数据
        for _, row in top_dt.iterrows():
            code = str(row['代码']).zfill(6)
            name = row['名称']
            amount = abs(row['封板资金']) / 1e8
            display_data.append((f"{code}\n{name}", amount))
            colors_list.append('green')

        if display_data:
            labels, amounts = zip(*display_data)
            y_pos = range(len(labels))
            axes[1, 1].barh(y_pos, amounts, color=colors_list, alpha=0.7)
            axes[1, 1].set_yticks(y_pos)
            axes[1, 1].set_yticklabels(labels, fontsize=7)
            axes[1, 1].set_title('封单额排名前15 (单位: 亿元)')
            axes[1, 1].set_xlabel('封单额 (亿元)')
            axes[1, 1].invert_yaxis()
        else:
            axes[1, 1].text(0.5, 0.5, '无封单数据', ha='center', va='center', transform=axes[1, 1].transAxes)
            axes[1, 1].set_title('封单额排名')

        # 5. 换手率与封板强度分析
        if not zt_df.empty and '换手率' in zt_df.columns and '流通市值' in zt_df.columns:
            zt_df_copy = zt_df.copy()
            zt_df_copy['封板强度'] = zt_df_copy['封板资金'] / zt_df_copy['流通市值'] * 100

            # 创建散点图
            scatter = axes[1, 2].scatter(zt_df_copy['换手率'], zt_df_copy['封板强度'],
                                       c=zt_df_copy['封板资金']/1e8, cmap='Reds', alpha=0.6, s=50)
            axes[1, 2].set_xlabel('换手率 (%)')
            axes[1, 2].set_ylabel('封板强度 (%)')
            axes[1, 2].set_title('换手率 vs 封板强度')
            axes[1, 2].grid(True, alpha=0.3)

            # 添加颜色条
            cbar = plt.colorbar(scatter, ax=axes[1, 2])
            cbar.set_label('封单额 (亿元)', rotation=270, labelpad=15)
        else:
            axes[1, 2].text(0.5, 0.5, '无换手率数据', ha='center', va='center', transform=axes[1, 2].transAxes)
            axes[1, 2].set_title('换手率 vs 封板强度')

        plt.tight_layout()

        output_file = None
        if save_plot:
            output_file = os.path.join(self.images_dir, f"{date_str}_auction_fengdan_analysis.png")
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            print(f"图表已保存: {output_file}")

        if show_plot:
            plt.show()
        else:
            plt.close()  # 关闭图表，避免阻塞

        return output_file
    
    def plot_timepoint_comparison(self, date_str: str, save_plot: bool = True):
        """
        绘制时间点对比图
        
        Args:
            date_str: 日期字符串
            save_plot: 是否保存图片
        """
        comparison_df = self.compare_timepoints(date_str)
        
        if comparison_df.empty:
            print(f"没有 {date_str} 的时间点对比数据")
            return
        
        # 创建图表
        fig, axes = plt.subplots(2, 2, figsize=(15, 10))
        fig.suptitle(f'{date_str} 竞价时间点对比分析', fontsize=16, fontweight='bold')
        
        # 1. 涨停板数量变化
        axes[0, 0].plot(comparison_df['时间点'], comparison_df['涨停板数量'], marker='o', linewidth=2, markersize=8)
        axes[0, 0].set_title('涨停板数量变化')
        axes[0, 0].set_ylabel('数量')
        axes[0, 0].grid(True, alpha=0.3)
        
        # 2. 封单总额变化
        axes[0, 1].plot(comparison_df['时间点'], comparison_df['封单总额'] / 1e8, marker='s', linewidth=2, markersize=8, color='red')
        axes[0, 1].set_title('封单总额变化 (单位: 亿元)')
        axes[0, 1].set_ylabel('封单总额 (亿元)')
        axes[0, 1].grid(True, alpha=0.3)
        
        # 3. 平均封单额变化
        axes[1, 0].plot(comparison_df['时间点'], comparison_df['平均封单额'] / 1e8, marker='^', linewidth=2, markersize=8, color='green')
        axes[1, 0].set_title('平均封单额变化 (单位: 亿元)')
        axes[1, 0].set_ylabel('平均封单额 (亿元)')
        axes[1, 0].grid(True, alpha=0.3)
        
        # 4. 竞价阶段封板数变化
        axes[1, 1].bar(comparison_df['时间点'], comparison_df['竞价阶段封板数'], color='orange', alpha=0.7)
        axes[1, 1].set_title('竞价阶段封板数')
        axes[1, 1].set_ylabel('数量')
        axes[1, 1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_plot:
            output_file = os.path.join(self.analysis_dir, f"{date_str}_timepoint_comparison.png")
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            print(f"时间点对比图已保存: {output_file}")
        
        plt.show()
    
    def generate_daily_report(self, date_str: str) -> str:
        """
        生成每日分析报告
        
        Args:
            date_str: 日期字符串
            
        Returns:
            报告文件路径
        """
        # 分析数据
        analysis_result = self.analyze_daily_summary(date_str)
        
        if not analysis_result:
            print(f"没有 {date_str} 的数据可分析")
            return ""
        
        # 生成报告
        report_content = f"""
# {date_str} 集合竞价封单数据分析报告

## 基础数据概览
- 涨停板总数: {analysis_result['涨停板总数']} 只
- 封单总额: {analysis_result['封单总额']:,.0f} 元 ({analysis_result['封单总额']/1e8:.2f} 亿元)
- 平均封单额: {analysis_result['平均封单额']:,.0f} 元
- 封单额中位数: {analysis_result['封单额中位数']:,.0f} 元

## 竞价阶段分析 (重点关注)
- **竞价阶段封板总数**: {analysis_result['竞价阶段封板数']} 只
  - 竞价涨停: {analysis_result['竞价阶段涨停数']} 只
  - 竞价跌停: {analysis_result['竞价阶段跌停数']} 只
- **竞价阶段封单总额**: {analysis_result['竞价阶段封单总额']:,.0f} 元 ({analysis_result['竞价阶段封单总额']/1e8:.2f} 亿元)
  - 涨停封单金额: {analysis_result['竞价阶段涨停金额']:,.0f} 元 ({analysis_result['竞价阶段涨停金额']/1e8:.2f} 亿元)
  - 跌停封单金额: {analysis_result['竞价阶段跌停金额']:,.0f} 元 ({analysis_result['竞价阶段跌停金额']/1e8:.2f} 亿元)
- **竞价阶段占比**: {analysis_result['竞价阶段占比']:.2f}% (占全日封单总额)

## 时间段分布
"""
        
        for time_period, count in analysis_result['时间段分布'].items():
            report_content += f"- {time_period}: {count} 只\n"
        
        report_content += "\n## 行业分布 (前10名)\n"
        for industry, count in analysis_result['行业分布'].items():
            report_content += f"- {industry}: {count} 只\n"
        
        report_content += "\n## 封单额分布\n"
        for range_name, count in analysis_result['封单额分布'].items():
            report_content += f"- {range_name}: {count} 只\n"

        # 市场情绪分析
        if '市场情绪' in analysis_result and analysis_result['市场情绪']:
            sentiment = analysis_result['市场情绪']
            report_content += "\n## 市场情绪分析\n"

            # 市值分布
            if '小盘股' in sentiment:
                report_content += f"### 市值分布\n"
                report_content += f"- 小盘股(<100亿): {sentiment['小盘股']} 只\n"
                report_content += f"- 中盘股(100-500亿): {sentiment['中盘股']} 只\n"
                report_content += f"- 大盘股(>500亿): {sentiment['大盘股']} 只\n"
                report_content += f"- 平均流通市值: {sentiment['平均流通市值']:.1f} 亿元\n\n"

            # 换手率分析
            if '高换手率' in sentiment:
                report_content += f"### 换手率分析\n"
                report_content += f"- 高换手率(>5%): {sentiment['高换手率']} 只\n"
                report_content += f"- 低换手率(≤5%): {sentiment['低换手率']} 只\n"
                report_content += f"- 平均换手率: {sentiment['平均换手率']:.2f}%\n\n"

            # 封板强度分析
            if '强封板' in sentiment:
                report_content += f"### 封板强度分析\n"
                report_content += f"- 强封板(>1%): {sentiment['强封板']} 只\n"
                report_content += f"- 弱封板(≤1%): {sentiment['弱封板']} 只\n"
                report_content += f"- 平均封板强度: {sentiment['平均封板强度']:.2f}%\n\n"

                # 市场情绪总结
                total_stocks = sentiment.get('小盘股', 0) + sentiment.get('中盘股', 0) + sentiment.get('大盘股', 0)
                if total_stocks > 0:
                    small_ratio = sentiment.get('小盘股', 0) / total_stocks * 100
                    high_turnover_ratio = sentiment.get('高换手率', 0) / total_stocks * 100
                    strong_seal_ratio = sentiment.get('强封板', 0) / total_stocks * 100

                    report_content += f"### 市场情绪总结\n"
                    if small_ratio > 60:
                        report_content += f"- 小盘股占比{small_ratio:.1f}%，市场偏好小盘题材\n"
                    elif sentiment.get('大盘股', 0) / total_stocks * 100 > 30:
                        report_content += f"- 大盘股表现活跃，市场情绪相对理性\n"

                    if high_turnover_ratio > 50:
                        report_content += f"- 高换手率股票占比{high_turnover_ratio:.1f}%，市场交投活跃\n"
                    else:
                        report_content += f"- 低换手率股票较多，市场相对谨慎\n"

                    if strong_seal_ratio > 40:
                        report_content += f"- 强封板股票占比{strong_seal_ratio:.1f}%，封板意愿强烈\n"
                    else:
                        report_content += f"- 封板强度一般，资金参与相对理性\n"
        
        # 保存报告到images/summary目录
        report_file = os.path.join(self.summary_dir, f"{date_str}_auction_fengdan_report.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)

        print(f"分析报告已生成: {report_file}")
        return report_file

    def run_comprehensive_analysis(self, date_str: str = None, show_plot: bool = False) -> Dict:
        """
        运行综合分析（复盘分析的主要逻辑）

        Args:
            date_str: 指定日期，格式YYYYMMDD，默认为最近交易日
            show_plot: 是否显示图表（默认不显示，避免阻塞）

        Returns:
            分析结果字典
        """
        from fetch.auction_fengdan_data import AuctionFengdanCollector
        import pandas as pd

        collector = AuctionFengdanCollector()

        # 确定分析日期
        if date_str is None:
            date_str = collector.get_current_trading_day()

        print(f"=== A股集合竞价封单数据复盘分析 ({date_str}) ===")

        # 获取综合数据（涨停+跌停）
        print("1. 获取综合封单数据...")
        current_data = collector.get_combined_fengdan_data(date_str)

        if current_data.empty:
            print("❌ 当前没有涨停或跌停数据")
            return {}

        # 分离涨停和跌停数据
        zt_data = current_data[current_data['涨跌类型'] == '涨停'] if '涨跌类型' in current_data.columns else current_data
        dt_data = current_data[current_data['涨跌类型'] == '跌停'] if '涨跌类型' in current_data.columns else pd.DataFrame()

        print(f"涨停板数量: {len(zt_data)}")
        print(f"跌停板数量: {len(dt_data)}")

        # 显示涨停封单额前10名
        if not zt_data.empty:
            print("\n📈 涨停封单额前10名:")
            top_10_zt = zt_data[['代码', '名称', '封板资金', '首次封板时间', '封板时间段']].head(10)
            for _, row in top_10_zt.iterrows():
                code = str(row['代码']).zfill(6)
                print(f"  {code} {row['名称']}: {row['封板资金']/1e8:.2f}亿 ({row['首次封板时间']})")

        # 显示跌停封单额前5名
        if not dt_data.empty:
            print("\n📉 跌停封单额前5名:")
            top_5_dt = dt_data.nsmallest(5, '封板资金')  # 跌停是负数，用nsmallest
            for _, row in top_5_dt.iterrows():
                code = str(row['代码']).zfill(6)
                amount = abs(row['封板资金']) / 1e8
                print(f"  {code} {row['名称']}: {amount:.2f}亿")

        # 竞价阶段封板股票
        auction_stocks = collector.get_auction_period_stocks(date_str)
        if not auction_stocks.empty:
            print(f"\n🎯 竞价阶段封板股票 ({len(auction_stocks)} 只):")
            for _, row in auction_stocks.iterrows():
                code = str(row['代码']).zfill(6)
                # 根据涨跌类型选择合适的封单金额字段
                if '封板资金' in row:
                    amount = abs(row['封板资金']) / 1e8
                elif '封单资金' in row:
                    amount = abs(row['封单资金']) / 1e8
                else:
                    amount = 0
                type_str = row.get('涨跌类型', '涨停')
                print(f"  {code} {row['名称']}: {amount:.2f}亿 ({type_str})")
        else:
            print("\n🎯 当前没有竞价阶段封板的股票")

        # 保存数据
        saved_file = collector.save_daily_data(date_str)
        if saved_file:
            print(f"\n💾 数据已保存到: {saved_file}")

        # 生成分析报告和图表
        print("\n📊 生成分析报告和图表...")
        report_file = self.generate_daily_report(date_str)
        if report_file:
            print(f"📄 分析报告: {report_file}")

        chart_file = self.plot_fengdan_distribution(date_str, save_plot=True, show_plot=show_plot)
        if chart_file:
            print(f"📊 分析图表: {chart_file}")

        # 返回分析结果
        return {
            'date': date_str,
            'zt_count': len(zt_data),
            'dt_count': len(dt_data),
            'auction_count': len(auction_stocks),
            'total_zt_amount': zt_data['封板资金'].sum() if not zt_data.empty else 0,
            'total_dt_amount': abs(dt_data['封板资金'].sum()) if not dt_data.empty else 0,
            'report_file': report_file,
            'chart_file': chart_file,
            'data_file': saved_file
        }


def main():
    """主函数 - 演示使用"""
    analyzer = AuctionFengdanAnalyzer()
    
    # 使用今天的日期
    today = datetime.now().strftime('%Y%m%d')
    
    print(f"=== {today} 集合竞价封单数据分析 ===")
    
    # 1. 生成每日分析报告
    print("1. 生成每日分析报告...")
    report_file = analyzer.generate_daily_report(today)
    
    # 2. 绘制封单分布图
    print("2. 绘制封单分布图...")
    analyzer.plot_fengdan_distribution(today)
    
    # 3. 时间点对比分析
    print("3. 时间点对比分析...")
    comparison_df = analyzer.compare_timepoints(today)
    if not comparison_df.empty:
        print("时间点对比结果:")
        print(comparison_df.to_string(index=False))
        analyzer.plot_timepoint_comparison(today)
    else:
        print("没有时间点对比数据")


if __name__ == "__main__":
    main()
