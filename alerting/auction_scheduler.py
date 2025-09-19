"""
A股集合竞价封单数据定时采集调度器

在交易日的9:15、9:20、9:25三个时间点自动采集封单数据，
用于横向对比分析竞价阶段的资金流向变化。

功能特点：
1. 精确时间点触发采集
2. 交易日判断
3. 数据对比分析
4. 异常处理和重试
5. 日志记录

使用方法：
conda activate trading
python alerting/auction_scheduler.py

作者：Trading System
创建时间：2025-01-14
"""

import os
import sys

sys.path.append('.')

import schedule
import time
import logging
import pandas as pd
from datetime import datetime
from typing import Dict
import threading

from fetch.auction_fengdan_data import AuctionFengdanCollector
from analysis.auction_fengdan_analysis import AuctionFengdanAnalyzer
from utils.date_util import is_trading_day

# 尝试导入mood_analyzer，如果失败则使用Mock版本
try:
    from alerting.mood_analyzer import MoodAnalyzer

    MOOD_ANALYZER_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ 无法导入MoodAnalyzer: {e}")
    print("将使用Mock版本进行情绪分析")
    try:
        from tests.test_mood_analyzer import MockMoodAnalyzer as MoodAnalyzer

        MOOD_ANALYZER_AVAILABLE = True
    except ImportError:
        print("❌ Mock版本也无法导入，情绪分析功能将被禁用")
        MOOD_ANALYZER_AVAILABLE = False


class AuctionScheduler:
    """集合竞价数据定时采集调度器"""

    def __init__(self):
        """初始化调度器"""
        self.collector = AuctionFengdanCollector()
        self.analyzer = AuctionFengdanAnalyzer()

        # 初始化情绪分析器
        if MOOD_ANALYZER_AVAILABLE:
            self.mood_analyzer = MoodAnalyzer()
            self.logger_info = "竞价数据调度器初始化完成（包含情绪分析）"
        else:
            self.mood_analyzer = None
            self.logger_info = "竞价数据调度器初始化完成（情绪分析功能禁用）"

        # 设置日志
        log_file = 'logs/auction_scheduler.log'
        os.makedirs('logs', exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # 采集时间点（竞价阶段）
        self.auction_times = ['09:25:00']

        # 盘中情绪分析时间点
        self.intraday_times = ['10:00:00', '11:00:00', '13:30:00', '14:30:00']

        # 兼容性：保持原有的target_times
        self.target_times = self.auction_times

        # 运行状态
        self.is_running = False
        self.collected_today = []

        self.logger.info(self.logger_info)

    def is_trading_time(self) -> bool:
        """判断是否为交易时间"""
        today = datetime.now().strftime('%Y%m%d')
        return is_trading_day(today)

    def collect_auction_data(self, time_point: str = None):
        """采集竞价数据"""
        if not self.is_trading_time():
            self.logger.info("今日非交易日，跳过数据采集")
            return

        current_time = datetime.now()
        time_str = time_point or current_time.strftime('%H:%M:%S')

        try:
            self.logger.info(f"开始采集 {time_str} 竞价封单数据...")

            # 获取综合数据
            data = self.collector.get_combined_fengdan_data()

            if data.empty:
                self.logger.warning(f"{time_str} 未获取到封单数据")
                return

            # 分析数据
            zt_count = len(data[data['涨跌类型'] == '涨停']) if '涨跌类型' in data.columns else len(data)
            dt_count = len(data[data['涨跌类型'] == '跌停']) if '涨跌类型' in data.columns else 0

            # 竞价阶段封板股票
            auction_stocks = data[data['首次封板时间'].astype(str).str.startswith(
                '092')] if '首次封板时间' in data.columns else pd.DataFrame()
            auction_count = len(auction_stocks)

            self.logger.info(f"{time_str} 数据采集完成 - 涨停: {zt_count}, 跌停: {dt_count}, 竞价封板: {auction_count}")

            # 保存时间点数据
            self.save_timepoint_data(data, time_str)

            # 记录采集状态
            today = current_time.strftime('%Y%m%d')
            if today not in [item['date'] for item in self.collected_today]:
                self.collected_today.append({
                    'date': today,
                    'time': time_str,
                    'zt_count': zt_count,
                    'dt_count': dt_count,
                    'auction_count': auction_count
                })

        except Exception as e:
            self.logger.error(f"采集 {time_str} 数据失败: {e}")
            import traceback
            traceback.print_exc()

    def analyze_auction_mood(self, time_point: str = None):
        """分析竞价阶段情绪"""
        if not self.is_trading_time():
            self.logger.info("今日非交易日，跳过竞价情绪分析")
            return

        if not self.mood_analyzer:
            self.logger.warning("情绪分析器不可用，跳过竞价情绪分析")
            return

        current_time = datetime.now()
        time_str = time_point or current_time.strftime('%H:%M:%S')
        time_tag = time_str.replace(':', '')[:4]  # 0915, 0920, 0925

        try:
            self.logger.info(f"开始 {time_str} 竞价情绪分析...")

            # 执行竞价情绪分析
            analysis = self.mood_analyzer.analyze_auction_mood(time_point=time_tag)

            if analysis:
                # 生成报告和图表
                report_path = self.mood_analyzer.generate_mood_report(analysis)
                chart_path = self.mood_analyzer.plot_mood_chart(analysis)

                self.logger.info(f"{time_str} 竞价情绪分析完成")
                self.logger.info(f"  情绪强度: {analysis['score']}分 - {analysis['level']}")
                self.logger.info(f"  分析报告: {report_path}")
                self.logger.info(f"  分析图表: {chart_path}")
            else:
                self.logger.warning(f"{time_str} 竞价情绪分析失败")

        except Exception as e:
            self.logger.error(f"竞价情绪分析失败: {e}")
            import traceback
            traceback.print_exc()

    def analyze_intraday_mood(self, time_point: str = None):
        """分析盘中情绪"""
        if not self.is_trading_time():
            self.logger.info("今日非交易日，跳过盘中情绪分析")
            return

        if not self.mood_analyzer:
            self.logger.warning("情绪分析器不可用，跳过盘中情绪分析")
            return

        current_time = datetime.now()
        time_str = time_point or current_time.strftime('%H:%M:%S')
        time_tag = time_str.replace(':', '')[:4]  # 1000, 1100, 1330, 1430

        try:
            self.logger.info(f"开始 {time_str} 盘中情绪分析...")

            # 执行盘中情绪分析
            analysis = self.mood_analyzer.analyze_intraday_mood(time_point=time_tag)

            if analysis:
                # 生成报告和图表
                report_path = self.mood_analyzer.generate_mood_report(analysis)
                chart_path = self.mood_analyzer.plot_mood_chart(analysis)

                self.logger.info(f"{time_str} 盘中情绪分析完成")
                self.logger.info(f"  情绪强度: {analysis['score']}分 - {analysis['level']}")
                self.logger.info(f"  涨停数量: {analysis['data']['涨停数量']}只")
                self.logger.info(f"  炸板率: {analysis['data']['炸板率']:.1%}")
                self.logger.info(f"  分析报告: {report_path}")
                self.logger.info(f"  分析图表: {chart_path}")
            else:
                self.logger.warning(f"{time_str} 盘中情绪分析失败")

        except Exception as e:
            self.logger.error(f"盘中情绪分析失败: {e}")
            import traceback
            traceback.print_exc()

    def save_timepoint_data(self, data, time_str: str):
        """保存时间点数据"""
        try:
            today = datetime.now().strftime('%Y%m%d')
            time_tag = time_str.replace(':', '')[:4]  # 0915, 0920, 0925

            # 保存到data目录
            filename = f"{today}_{time_tag}_fengdan.csv"
            filepath = os.path.join(self.collector.data_dir, "daily", filename)

            data.to_csv(filepath, index=False, encoding='utf-8-sig')
            self.logger.info(f"时间点数据已保存: {filepath}")

        except Exception as e:
            self.logger.error(f"保存时间点数据失败: {e}")

    def schedule_daily_collection(self):
        """设置每日采集计划"""
        # 清除之前的任务
        schedule.clear()

        # 设置竞价阶段采集时间点
        for target_time in self.auction_times:
            schedule.every().day.at(target_time).do(self.collect_auction_data, target_time)
            self.logger.info(f"已设置定时采集: {target_time}")

            # 如果有情绪分析器，设置竞价情绪分析
            if self.mood_analyzer:
                schedule.every().day.at(target_time).do(self.analyze_auction_mood, target_time)
                self.logger.info(f"已设置竞价情绪分析: {target_time}")

        # 设置盘中情绪分析时间点
        if self.mood_analyzer:
            for intraday_time in self.intraday_times:
                schedule.every().day.at(intraday_time).do(self.analyze_intraday_mood, intraday_time)
                self.logger.info(f"已设置盘中情绪分析: {intraday_time}")

        # 设置收盘后分析
        schedule.every().day.at("15:30:00").do(self.generate_daily_analysis)
        self.logger.info("已设置收盘后分析: 15:30:00")

    def generate_daily_analysis(self):
        """生成每日分析"""
        if not self.is_trading_time():
            self.logger.info("今日非交易日，跳过分析生成")
            return

        try:
            today = datetime.now().strftime('%Y%m%d')
            self.logger.info(f"开始生成 {today} 每日分析...")

            # 生成分析报告
            self.analyzer.generate_daily_report(today)

            # 生成图表
            self.analyzer.plot_fengdan_distribution(today)

            self.logger.info(f"{today} 每日分析生成完成")

        except Exception as e:
            self.logger.error(f"生成每日分析失败: {e}")

    def start_scheduler(self):
        """启动调度器"""
        self.logger.info("🚀 启动集合竞价数据定时采集调度器...")

        # 设置定时任务
        self.schedule_daily_collection()

        self.is_running = True

        def run_scheduler():
            while self.is_running:
                schedule.run_pending()
                time.sleep(1)

        # 在后台线程中运行
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()

        self.logger.info("调度器已启动，将在以下时间点自动采集数据:")
        for target_time in self.auction_times:
            self.logger.info(f"  📅 {target_time} (竞价数据采集)")
            if self.mood_analyzer:
                self.logger.info(f"  🎯 {target_time} (竞价情绪分析)")

        if self.mood_analyzer:
            self.logger.info("盘中情绪分析时间点:")
            for intraday_time in self.intraday_times:
                self.logger.info(f"  🎯 {intraday_time} (盘中情绪分析)")

        self.logger.info("  📊 15:30:00 (收盘后分析)")

        return scheduler_thread

    def stop_scheduler(self):
        """停止调度器"""
        self.is_running = False
        schedule.clear()
        self.logger.info("调度器已停止")

    def manual_collect_now(self):
        """手动采集当前数据"""
        self.logger.info("🔍 手动采集当前竞价数据...")
        self.collect_auction_data()

    def get_schedule_status(self) -> Dict:
        """获取调度器状态"""
        return {
            'is_running': self.is_running,
            'target_times': self.target_times,
            'collected_today': self.collected_today,
            'next_run': schedule.next_run() if schedule.jobs else None
        }


def main():
    """主函数"""
    print("📅 A股集合竞价封单数据定时采集调度器")
    print("=" * 50)

    scheduler = AuctionScheduler()

    if len(sys.argv) > 1:
        command = sys.argv[1].lower()

        if command == 'start':
            # 启动调度器
            scheduler.start_scheduler()
            print("调度器已启动，按 Ctrl+C 停止...")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                scheduler.stop_scheduler()
                print("调度器已停止")

        elif command == 'collect':
            # 手动采集一次
            scheduler.manual_collect_now()

        elif command == 'status':
            # 查看状态
            status = scheduler.get_schedule_status()
            print("调度器状态:")
            print(f"  运行状态: {'运行中' if status['is_running'] else '已停止'}")
            print(f"  采集时间: {', '.join(status['target_times'])}")
            print(f"  今日采集: {len(status['collected_today'])} 次")

        else:
            print(f"未知命令: {command}")
            print("可用命令: start, collect, status")

    else:
        # 默认启动调度器
        scheduler.start_scheduler()
        print("调度器已启动，按 Ctrl+C 停止...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            scheduler.stop_scheduler()
            print("调度器已停止")


if __name__ == "__main__":
    main()
