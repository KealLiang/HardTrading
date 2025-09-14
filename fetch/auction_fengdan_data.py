"""
A股集合竞价封单数据获取模块

基于akshare接口获取涨停板股票的封单数据，支持定时采集和横向对比分析。
主要功能：
1. 获取实时涨停板封单数据
2. 按封单额排序
3. 区分竞价阶段封板股票
4. 支持历史数据对比
5. 数据可视化和分析

作者：Trading System
创建时间：2025-01-14
"""

import os
import logging
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import json
import time
from utils.date_util import get_prev_trading_day, get_current_or_prev_trading_day, is_trading_day


class AuctionFengdanCollector:
    """集合竞价封单数据采集器"""
    
    def __init__(self, data_dir: str = "data/auction_fengdan"):
        """
        初始化采集器
        
        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = data_dir
        self.ensure_data_dir()
        
        # 配置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def ensure_data_dir(self):
        """确保数据目录存在"""
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "daily"), exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "analysis"), exist_ok=True)

    def get_current_trading_day(self) -> str:
        """获取最近的交易日"""
        today = datetime.now().strftime('%Y%m%d')

        # 检查今天是否是交易日
        if is_trading_day(today):
            return today

        # 如果不是，往前找最近的交易日
        for i in range(1, 8):  # 最多往前找7天
            check_date = (datetime.now() - timedelta(days=i)).strftime('%Y%m%d')
            if is_trading_day(check_date):
                return check_date

        # 如果都找不到，使用原来的方法
        return get_current_or_prev_trading_day(today)
    
    def get_zt_fengdan_data(self, date_str: str = None) -> pd.DataFrame:
        """
        获取涨停板封单数据
        
        Args:
            date_str: 日期字符串，格式YYYYMMDD，默认为今天
            
        Returns:
            包含封单数据的DataFrame
        """
        if date_str is None:
            date_str = self.get_current_trading_day()
        
        try:
            self.logger.info(f"获取 {date_str} 的涨停板封单数据...")
            
            # 获取涨停板数据
            zt_data = ak.stock_zt_pool_em(date=date_str)
            
            if zt_data.empty:
                self.logger.warning(f"{date_str} 没有涨停板数据")
                return pd.DataFrame()
            
            # 按封板资金排序
            zt_sorted = zt_data.sort_values('封板资金', ascending=False).reset_index(drop=True)
            
            # 添加排名
            zt_sorted['封单排名'] = range(1, len(zt_sorted) + 1)
            
            # 添加时间段分类
            zt_sorted['封板时间段'] = zt_sorted['首次封板时间'].apply(self._classify_time_period)
            
            # 添加采集时间
            zt_sorted['采集时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            zt_sorted['交易日期'] = date_str

            # 标记为涨停
            zt_sorted['涨跌类型'] = '涨停'

            self.logger.info(f"成功获取 {len(zt_sorted)} 只涨停板股票的封单数据")
            
            return zt_sorted
            
        except Exception as e:
            self.logger.error(f"获取涨停封单数据失败: {e}")
            return pd.DataFrame()

    def get_dt_fengdan_data(self, date_str: str = None) -> pd.DataFrame:
        """
        获取跌停板封单数据

        Args:
            date_str: 日期字符串，格式YYYYMMDD，默认为当前交易日

        Returns:
            包含跌停封单数据的DataFrame
        """
        if date_str is None:
            date_str = self.get_current_trading_day()

        try:
            self.logger.info(f"获取 {date_str} 的跌停板封单数据...")

            # 获取跌停板数据
            dt_data = ak.stock_zt_pool_dtgc_em(date=date_str)

            if dt_data.empty:
                self.logger.warning(f"{date_str} 没有跌停板数据")
                return pd.DataFrame()

            # 按封单资金排序（跌停板用封单资金字段）
            dt_sorted = dt_data.sort_values('封单资金', ascending=False).reset_index(drop=True)

            # 添加排名
            dt_sorted['封单排名'] = range(1, len(dt_sorted) + 1)

            # 添加时间段分类
            dt_sorted['封板时间段'] = dt_sorted['最后封板时间'].apply(self._classify_time_period)

            # 添加采集时间
            dt_sorted['采集时间'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            dt_sorted['交易日期'] = date_str

            # 标记为跌停
            dt_sorted['涨跌类型'] = '跌停'

            self.logger.info(f"成功获取 {len(dt_sorted)} 只跌停板股票的封单数据")

            return dt_sorted

        except Exception as e:
            self.logger.error(f"获取跌停封单数据失败: {e}")
            return pd.DataFrame()

    def get_combined_fengdan_data(self, date_str: str = None) -> pd.DataFrame:
        """
        获取综合封单数据（涨停+跌停）

        Args:
            date_str: 日期字符串，格式YYYYMMDD，默认为当前交易日

        Returns:
            包含涨停和跌停封单数据的DataFrame
        """
        if date_str is None:
            date_str = self.get_current_trading_day()

        # 获取涨停数据
        zt_data = self.get_zt_fengdan_data(date_str)

        # 获取跌停数据
        dt_data = self.get_dt_fengdan_data(date_str)

        # 合并数据
        combined_data = []

        if not zt_data.empty:
            combined_data.append(zt_data)

        if not dt_data.empty:
            # 跌停数据需要统一字段名
            dt_data_unified = dt_data.copy()
            # 将跌停的封单资金转为负数以便区分
            dt_data_unified['封板资金'] = -dt_data_unified['封单资金']
            # 统一时间字段名
            if '最后封板时间' in dt_data_unified.columns:
                dt_data_unified['首次封板时间'] = dt_data_unified['最后封板时间']
            combined_data.append(dt_data_unified)

        if not combined_data:
            self.logger.warning(f"{date_str} 没有涨停或跌停数据")
            return pd.DataFrame()

        # 合并所有数据
        result = pd.concat(combined_data, ignore_index=True, sort=False)

        # 重新排序：涨停按封板资金降序，跌停按封单资金降序
        zt_mask = result['涨跌类型'] == '涨停'
        dt_mask = result['涨跌类型'] == '跌停'

        zt_sorted = result[zt_mask].sort_values('封板资金', ascending=False) if zt_mask.any() else pd.DataFrame()
        dt_sorted = result[dt_mask].sort_values('封板资金', ascending=True) if dt_mask.any() else pd.DataFrame()  # 跌停用升序（因为是负数）

        # 重新合并
        final_result = pd.concat([zt_sorted, dt_sorted], ignore_index=True)

        # 重新编号
        final_result['综合排名'] = range(1, len(final_result) + 1)

        self.logger.info(f"成功获取 {date_str} 的综合封单数据：涨停 {len(zt_sorted)} 只，跌停 {len(dt_sorted)} 只")

        return final_result
    
    def _classify_time_period(self, time_str: str) -> str:
        """
        分类封板时间段
        
        Args:
            time_str: 时间字符串，格式HHMMSS
            
        Returns:
            时间段分类
        """
        if not time_str or len(time_str) < 4:
            return "未知时间"
        
        hour_min = time_str[:4]
        
        if hour_min.startswith('092'):
            return "竞价阶段(09:15-09:25)"
        elif hour_min.startswith('093') or hour_min.startswith('100'):
            return "开盘初期(09:30-10:00)"
        elif hour_min.startswith('10') or hour_min.startswith('11'):
            return "上午盘(10:00-11:30)"
        elif hour_min.startswith('13') or hour_min.startswith('14'):
            return "下午盘(13:00-15:00)"
        else:
            return "其他时间"
    
    def get_auction_period_stocks(self, date_str: str = None) -> pd.DataFrame:
        """
        获取竞价阶段封板的股票（包含涨停和跌停）

        Args:
            date_str: 日期字符串

        Returns:
            竞价阶段封板的股票数据
        """
        # 获取综合数据（涨停+跌停）
        combined_data = self.get_combined_fengdan_data(date_str)

        if combined_data.empty:
            return pd.DataFrame()

        # 筛选竞价阶段封板的股票
        # 方法1：使用封板时间段字段（如果存在）
        if '封板时间段' in combined_data.columns:
            auction_stocks = combined_data[combined_data['封板时间段'] == "竞价阶段(09:15-09:25)"]
        else:
            # 方法2：使用首次封板时间或最后封板时间
            auction_stocks = pd.DataFrame()

            # 处理涨停数据（使用首次封板时间）
            zt_data = combined_data[combined_data.get('涨跌类型', '') == '涨停'] if '涨跌类型' in combined_data.columns else combined_data
            if not zt_data.empty and '首次封板时间' in zt_data.columns:
                zt_auction = zt_data[zt_data['首次封板时间'].astype(str).str.startswith('092')]
                auction_stocks = pd.concat([auction_stocks, zt_auction], ignore_index=True)

            # 处理跌停数据（使用最后封板时间）
            dt_data = combined_data[combined_data.get('涨跌类型', '') == '跌停'] if '涨跌类型' in combined_data.columns else pd.DataFrame()
            if not dt_data.empty and '最后封板时间' in dt_data.columns:
                dt_auction = dt_data[dt_data['最后封板时间'].astype(str).str.startswith('092')]
                auction_stocks = pd.concat([auction_stocks, dt_auction], ignore_index=True)

        self.logger.info(f"竞价阶段封板股票数量: {len(auction_stocks)}")

        return auction_stocks
    
    def save_daily_data(self, date_str: str = None) -> str:
        """
        保存每日封单数据
        
        Args:
            date_str: 日期字符串
            
        Returns:
            保存的文件路径
        """
        if date_str is None:
            date_str = self.get_current_trading_day()
        
        # 获取数据
        zt_data = self.get_zt_fengdan_data(date_str)
        
        if zt_data.empty:
            self.logger.warning(f"{date_str} 没有数据可保存")
            return ""
        
        # 保存完整数据
        file_path = os.path.join(self.data_dir, "daily", f"{date_str}_fengdan_full.csv")
        zt_data.to_csv(file_path, index=False, encoding='utf-8-sig')
        
        # 保存竞价阶段数据
        auction_data = self.get_auction_period_stocks(date_str)
        if not auction_data.empty:
            auction_file = os.path.join(self.data_dir, "daily", f"{date_str}_auction_fengdan.csv")
            auction_data.to_csv(auction_file, index=False, encoding='utf-8-sig')
        
        # 保存汇总信息
        summary = self._generate_daily_summary(zt_data, date_str)
        summary_file = os.path.join(self.data_dir, "daily", f"{date_str}_summary.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"数据已保存到: {file_path}")
        return file_path
    
    def _generate_daily_summary(self, zt_data: pd.DataFrame, date_str: str) -> Dict:
        """
        生成每日汇总信息
        
        Args:
            zt_data: 涨停板数据
            date_str: 日期字符串
            
        Returns:
            汇总信息字典
        """
        if zt_data.empty:
            return {}
        
        summary = {
            "日期": date_str,
            "采集时间": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "涨停板总数": len(zt_data),
            "竞价阶段封板数": len(zt_data[zt_data['封板时间段'] == "竞价阶段(09:15-09:25)"]),
            "最大封单额": float(zt_data['封板资金'].max()),
            "最大封单股票": f"{zt_data.iloc[0]['代码']}-{zt_data.iloc[0]['名称']}",
            "平均封单额": float(zt_data['封板资金'].mean()),
            "封单额中位数": float(zt_data['封板资金'].median()),
            "时间段分布": zt_data['封板时间段'].value_counts().to_dict(),
            "前10大封单": zt_data.head(10)[['代码', '名称', '封板资金', '首次封板时间']].to_dict('records')
        }
        
        return summary
    
    def collect_multiple_timepoints(self, target_times: List[str] = None) -> Dict[str, pd.DataFrame]:
        """
        在多个时间点采集数据（模拟9:15, 9:20, 9:25的效果）
        
        Args:
            target_times: 目标时间列表，格式['09:15', '09:20', '09:25']
            
        Returns:
            各时间点的数据字典
        """
        if target_times is None:
            target_times = ['09:15', '09:20', '09:25']
        
        results = {}
        current_time = datetime.now().strftime('%H:%M')
        
        for target_time in target_times:
            self.logger.info(f"采集 {target_time} 时间点数据...")
            
            # 获取当前数据（实际应用中可以在指定时间触发）
            data = self.get_zt_fengdan_data()
            
            if not data.empty:
                # 添加时间点标记
                data['采集时间点'] = target_time
                results[target_time] = data
                
                # 保存时间点数据
                date_str = self.get_current_trading_day()
                file_path = os.path.join(
                    self.data_dir, "daily",
                    f"{date_str}_{target_time.replace(':', '')}_fengdan.csv"
                )
                data.to_csv(file_path, index=False, encoding='utf-8-sig')
                
                self.logger.info(f"{target_time} 数据已保存: {len(data)} 只股票")
            else:
                self.logger.warning(f"{target_time} 时间点无数据")
        
        return results
    
    def compare_timepoints(self, date_str: str = None) -> pd.DataFrame:
        """
        对比不同时间点的封单数据
        
        Args:
            date_str: 日期字符串
            
        Returns:
            对比分析结果
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y%m%d')
        
        # 读取不同时间点的数据文件
        timepoints = ['0915', '0920', '0925']
        comparison_data = []
        
        for tp in timepoints:
            file_path = os.path.join(self.data_dir, "daily", f"{date_str}_{tp}_fengdan.csv")
            if os.path.exists(file_path):
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                df['时间点'] = f"{tp[:2]}:{tp[2:]}"
                comparison_data.append(df)
        
        if not comparison_data:
            self.logger.warning(f"没有找到 {date_str} 的时间点数据文件")
            return pd.DataFrame()
        
        # 合并数据
        combined_df = pd.concat(comparison_data, ignore_index=True)
        
        # 生成对比分析
        comparison_result = self._analyze_timepoint_changes(combined_df)
        
        # 保存对比结果
        result_file = os.path.join(self.data_dir, "analysis", f"{date_str}_timepoint_comparison.csv")
        comparison_result.to_csv(result_file, index=False, encoding='utf-8-sig')
        
        self.logger.info(f"时间点对比分析已保存: {result_file}")
        
        return comparison_result
    
    def _analyze_timepoint_changes(self, combined_df: pd.DataFrame) -> pd.DataFrame:
        """
        分析时间点变化
        
        Args:
            combined_df: 合并的时间点数据
            
        Returns:
            变化分析结果
        """
        # 按股票代码分组，分析封单变化
        stock_changes = []
        
        for code in combined_df['代码'].unique():
            stock_data = combined_df[combined_df['代码'] == code].sort_values('时间点')
            
            if len(stock_data) > 1:
                first_record = stock_data.iloc[0]
                last_record = stock_data.iloc[-1]
                
                fengdan_change = last_record['封板资金'] - first_record['封板资金']
                fengdan_change_pct = (fengdan_change / first_record['封板资金']) * 100 if first_record['封板资金'] > 0 else 0
                
                stock_changes.append({
                    '代码': code,
                    '名称': first_record['名称'],
                    '首次出现时间': first_record['时间点'],
                    '最后出现时间': last_record['时间点'],
                    '初始封单额': first_record['封板资金'],
                    '最终封单额': last_record['封板资金'],
                    '封单变化额': fengdan_change,
                    '封单变化率(%)': round(fengdan_change_pct, 2),
                    '出现次数': len(stock_data)
                })
        
        return pd.DataFrame(stock_changes)


def main():
    """主函数 - 演示使用"""
    collector = AuctionFengdanCollector()
    
    # 1. 获取当前封单数据
    print("=== 获取当前涨停板封单数据 ===")
    current_data = collector.get_zt_fengdan_data()
    if not current_data.empty:
        print(f"当前涨停板数量: {len(current_data)}")
        print("\n封单额前10名:")
        print(current_data[['代码', '名称', '封板资金', '首次封板时间', '封板时间段']].head(10))
    
    # 2. 获取竞价阶段封板股票
    print("\n=== 竞价阶段封板股票 ===")
    auction_stocks = collector.get_auction_period_stocks()
    if not auction_stocks.empty:
        print(auction_stocks[['代码', '名称', '封板资金', '首次封板时间']])
    else:
        print("当前没有竞价阶段封板的股票")
    
    # 3. 保存每日数据
    print("\n=== 保存每日数据 ===")
    saved_file = collector.save_daily_data()
    if saved_file:
        print(f"数据已保存: {saved_file}")


if __name__ == "__main__":
    main()
