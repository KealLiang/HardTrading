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

        # 分析结果保存到images目录
        self.images_dir = "images"
        self.summary_dir = os.path.join(self.images_dir, "summary")

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
        
        # 竞价阶段分析
        auction_stocks = df[df['封板时间段'] == "竞价阶段(09:15-09:25)"]
        auction_count = len(auction_stocks)
        auction_fengdan_total = auction_stocks['封板资金'].sum() if not auction_stocks.empty else 0
        
        # 行业分布
        industry_distribution = df['所属行业'].value_counts().head(10).to_dict()
        
        # 封单额分布
        fengdan_ranges = {
            '1亿以上': len(df[df['封板资金'] >= 100000000]),
            '5000万-1亿': len(df[(df['封板资金'] >= 50000000) & (df['封板资金'] < 100000000)]),
            '1000万-5000万': len(df[(df['封板资金'] >= 10000000) & (df['封板资金'] < 50000000)]),
            '1000万以下': len(df[df['封板资金'] < 10000000])
        }
        
        analysis_result = {
            '日期': date_str,
            '分析时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '涨停板总数': total_stocks,
            '封单总额': total_fengdan,
            '平均封单额': avg_fengdan,
            '封单额中位数': median_fengdan,
            '竞价阶段封板数': auction_count,
            '竞价阶段封单总额': auction_fengdan_total,
            '竞价阶段占比': (auction_fengdan_total / total_fengdan * 100) if total_fengdan > 0 else 0,
            '时间段分布': time_distribution,
            '行业分布': industry_distribution,
            '封单额分布': fengdan_ranges
        }
        
        return analysis_result
    
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
    
    def plot_fengdan_distribution(self, date_str: str = None, save_plot: bool = True):
        """
        绘制封单额分布图（涨停+跌停综合）

        Args:
            date_str: 日期字符串，默认为当前交易日
            save_plot: 是否保存图片
        """
        if date_str is None:
            date_str = self.get_current_trading_day()

        # 尝试加载综合数据
        from fetch.auction_fengdan_data import AuctionFengdanCollector
        collector = AuctionFengdanCollector()
        df = collector.get_combined_fengdan_data(date_str)

        if df.empty:
            print(f"没有 {date_str} 的数据")
            return

        # 分离涨停和跌停数据
        zt_df = df[df['涨跌类型'] == '涨停'].copy() if '涨跌类型' in df.columns else df.copy()
        dt_df = df[df['涨跌类型'] == '跌停'].copy() if '涨跌类型' in df.columns else pd.DataFrame()

        # 创建图表
        fig, axes = plt.subplots(2, 2, figsize=(16, 12))

        # 格式化日期显示
        try:
            date_obj = datetime.strptime(date_str, '%Y%m%d')
            formatted_date = date_obj.strftime('%Y年%m月%d日')
        except:
            formatted_date = date_str

        fig.suptitle(f'{formatted_date} 涨跌停封单数据分析', fontsize=16, fontweight='bold')

        # 1. 涨跌停对比柱状图
        type_counts = df['涨跌类型'].value_counts() if '涨跌类型' in df.columns else {'涨停': len(df)}
        colors = ['red' if x == '涨停' else 'green' for x in type_counts.index]
        axes[0, 0].bar(type_counts.index, type_counts.values, color=colors, alpha=0.7)
        axes[0, 0].set_title('涨跌停数量对比')
        axes[0, 0].set_ylabel('股票数量')
        for i, v in enumerate(type_counts.values):
            axes[0, 0].text(i, v + 0.5, str(v), ha='center', va='bottom', fontweight='bold')

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
            axes[1, 0].barh(range(len(industry_dist)), industry_dist.values, color='lightcoral')
            axes[1, 0].set_yticks(range(len(industry_dist)))
            axes[1, 0].set_yticklabels(industry_dist.index, fontsize=9)
            axes[1, 0].set_title('涨停行业分布 (前10名)')
            axes[1, 0].set_xlabel('股票数量')
        else:
            axes[1, 0].text(0.5, 0.5, '无行业数据', ha='center', va='center', transform=axes[1, 0].transAxes)
            axes[1, 0].set_title('涨停行业分布')

        # 4. 封单额排名前20（涨停+跌停）
        # 涨停取前15，跌停取前5
        top_zt = zt_df.nlargest(15, '封板资金') if not zt_df.empty else pd.DataFrame()
        top_dt = dt_df.nsmallest(5, '封板资金') if not dt_df.empty else pd.DataFrame()  # 跌停用nsmallest因为是负数

        # 合并显示
        display_data = []
        colors_list = []

        # 添加涨停数据
        for _, row in top_zt.iterrows():
            code = str(row['代码']).zfill(6)  # 确保6位数字，补前导0
            name = row['名称']
            amount = abs(row['封板资金']) / 1e8
            display_data.append((f"{code}\n{name}", amount))
            colors_list.append('red')

        # 添加跌停数据
        for _, row in top_dt.iterrows():
            code = str(row['代码']).zfill(6)  # 确保6位数字，补前导0
            name = row['名称']
            amount = abs(row['封板资金']) / 1e8  # 取绝对值显示
            display_data.append((f"{code}\n{name}", amount))
            colors_list.append('green')

        if display_data:
            labels, amounts = zip(*display_data)
            y_pos = range(len(labels))
            axes[1, 1].barh(y_pos, amounts, color=colors_list, alpha=0.7)
            axes[1, 1].set_yticks(y_pos)
            axes[1, 1].set_yticklabels(labels, fontsize=7)
            axes[1, 1].set_title('封单额排名前20 (单位: 亿元)')
            axes[1, 1].set_xlabel('封单额 (亿元)')
            axes[1, 1].invert_yaxis()  # 倒序显示，最大的在上面
        else:
            axes[1, 1].text(0.5, 0.5, '无封单数据', ha='center', va='center', transform=axes[1, 1].transAxes)
            axes[1, 1].set_title('封单额排名')

        plt.tight_layout()

        if save_plot:
            output_file = os.path.join(self.images_dir, f"{date_str}_auction_fengdan_analysis.png")
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            print(f"图表已保存: {output_file}")

        plt.show()
    
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

## 竞价阶段分析
- 竞价阶段封板数: {analysis_result['竞价阶段封板数']} 只
- 竞价阶段封单总额: {analysis_result['竞价阶段封单总额']:,.0f} 元
- 竞价阶段占比: {analysis_result['竞价阶段占比']:.2f}%

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
        
        # 保存报告到images/summary目录
        report_file = os.path.join(self.summary_dir, f"{date_str}_auction_fengdan_report.md")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_content)

        print(f"分析报告已生成: {report_file}")
        return report_file


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
