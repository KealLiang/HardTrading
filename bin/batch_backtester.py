"""
大批量股票回测模块

功能特点：
1. 支持从文件读取股票列表（CSV/TXT）
2. 多进程并行回测，大幅提升性能
3. 简化输出，只保留关键统计指标
4. 生成汇总Excel报告
5. 实时进度显示
6. 支持断点续传
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from multiprocessing import Pool, cpu_count, Manager
import pandas as pd
from typing import List, Dict, Optional, Tuple
from contextlib import redirect_stdout
import io

from bin import simulator


class BatchBacktester:
    """大批量回测器"""
    
    def __init__(self, 
                 stock_list_file: str = None,
                 stock_codes: List[str] = None,
                 output_dir: str = 'bin/batch_backtest_results',
                 max_workers: int = None):
        """
        初始化批量回测器
        
        Args:
            stock_list_file: 股票列表文件路径（CSV或TXT，优先级高于stock_codes）
            stock_codes: 股票代码列表（当stock_list_file为None时使用）
            output_dir: 输出目录
            max_workers: 最大并行进程数，默认为CPU核心数-1
        """
        self.stock_list_file = stock_list_file
        self.stock_codes = stock_codes or []
        self.output_dir = output_dir
        self.max_workers = max_workers or max(1, cpu_count() - 1)
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 加载股票列表
        if self.stock_list_file:
            self.stock_codes = self._load_stock_list(self.stock_list_file)
        
        if not self.stock_codes:
            raise ValueError("未提供有效的股票列表！请指定stock_list_file或stock_codes")
        
        logging.info(f"批量回测器初始化完成：共{len(self.stock_codes)}只股票，{self.max_workers}个并行进程")
    
    def _load_stock_list(self, filepath: str) -> List[str]:
        """
        从文件加载股票列表
        
        支持格式：
        - CSV: 第一列为股票代码（可有表头）
        - TXT: 每行一个股票代码
        
        Args:
            filepath: 文件路径
            
        Returns:
            股票代码列表
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"股票列表文件不存在: {filepath}")
        
        stock_codes = []
        
        try:
            if filepath.suffix.lower() == '.csv':
                # CSV格式
                df = pd.read_csv(filepath)
                # 取第一列，去除空值
                stock_codes = df.iloc[:, 0].dropna().astype(str).str.strip().tolist()
            elif filepath.suffix.lower() == '.txt':
                # TXT格式，每行一个代码
                with open(filepath, 'r', encoding='utf-8') as f:
                    stock_codes = [line.strip() for line in f if line.strip()]
            else:
                # 尝试按TXT格式读取
                with open(filepath, 'r', encoding='utf-8') as f:
                    stock_codes = [line.strip() for line in f if line.strip()]
            
            # 过滤掉表头（如果有"代码"、"code"等关键字）
            stock_codes = [code for code in stock_codes 
                          if code and not any(keyword in code.lower() 
                                            for keyword in ['code', '代码', '股票'])]
            
            logging.info(f"从文件 {filepath} 加载了 {len(stock_codes)} 只股票")
            
        except Exception as e:
            logging.error(f"加载股票列表失败: {e}")
            raise
        
        return stock_codes
    
    def run_batch_backtest(self,
                          strategy_class,
                          strategy_params: dict = None,
                          startdate: datetime = None,
                          enddate: datetime = None,
                          amount: int = 100000,
                          data_dir: str = './data/astocks',
                          resume: bool = False) -> str:
        """
        执行批量回测
        
        Args:
            strategy_class: 策略类
            strategy_params: 策略参数字典
            startdate: 回测开始日期
            enddate: 回测结束日期
            amount: 初始资金
            data_dir: 股票数据目录
            resume: 是否从上次中断处继续（跳过已完成的股票）
            
        Returns:
            汇总报告文件路径
        """
        # 默认参数
        if startdate is None:
            startdate = datetime(2022, 1, 1)
        if enddate is None:
            enddate = datetime.now()
        if strategy_params is None:
            strategy_params = {'debug': False}
        
        # 生成输出文件路径
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        strategy_name = strategy_class.__name__
        summary_file = os.path.join(self.output_dir, 
                                    f'batch_summary_{strategy_name}_{timestamp}.xlsx')
        log_file = os.path.join(self.output_dir, 
                               f'batch_log_{strategy_name}_{timestamp}.txt')
        
        # 如果resume，检查是否有临时结果
        completed_stocks = set()
        if resume:
            temp_file = summary_file.replace('.xlsx', '_temp.csv')
            if os.path.exists(temp_file):
                temp_df = pd.read_csv(temp_file)
                completed_stocks = set(temp_df['股票代码'].tolist())
                logging.info(f"断点续传：已完成 {len(completed_stocks)} 只股票")
        
        # 过滤出待处理股票
        pending_stocks = [code for code in self.stock_codes if code not in completed_stocks]
        
        print(f"\n{'='*60}")
        print(f"开始大批量回测")
        print(f"{'='*60}")
        print(f"策略: {strategy_name}")
        print(f"参数: {strategy_params}")
        print(f"时间范围: {startdate.date()} 至 {enddate.date()}")
        print(f"初始资金: {amount:,}")
        print(f"股票总数: {len(self.stock_codes)}")
        print(f"待处理: {len(pending_stocks)} 只")
        print(f"并行进程: {self.max_workers}")
        print(f"输出目录: {self.output_dir}")
        print(f"{'='*60}\n")
        
        # 准备任务参数
        tasks = []
        for code in pending_stocks:
            tasks.append({
                'code': code,
                'strategy_class': strategy_class,
                'strategy_params': strategy_params,
                'startdate': startdate,
                'enddate': enddate,
                'amount': amount,
                'data_dir': data_dir
            })
        
        # 使用Manager创建共享的计数器和结果列表
        with Manager() as manager:
            counter = manager.Value('i', 0)
            lock = manager.Lock()  # 创建独立的锁对象
            results_list = manager.list()
            
            # 多进程并行回测
            with Pool(processes=self.max_workers) as pool:
                # 包装任务以便传递共享变量
                wrapped_tasks = [(task, counter, lock, len(tasks), results_list) for task in tasks]
                pool.starmap(_run_single_backtest_worker, wrapped_tasks)
            
            # 转换为普通列表
            results = list(results_list)
        
        # 合并已完成的结果（如果有）
        if completed_stocks:
            temp_file = summary_file.replace('.xlsx', '_temp.csv')
            temp_df = pd.read_csv(temp_file)
            temp_results = temp_df.to_dict('records')
            results.extend(temp_results)
        
        # 生成汇总报告
        report_path = self._generate_summary_report(
            results, 
            summary_file,
            strategy_name,
            strategy_params,
            startdate,
            enddate,
            amount
        )
        
        print(f"\n{'='*60}")
        print(f"批量回测完成！")
        print(f"成功: {len([r for r in results if r['status'] == 'success'])} 只")
        print(f"失败: {len([r for r in results if r['status'] == 'failed'])} 只")
        print(f"汇总报告: {report_path}")
        print(f"{'='*60}\n")
        
        return report_path
    
    def _generate_summary_report(self, 
                                results: List[Dict],
                                output_file: str,
                                strategy_name: str,
                                strategy_params: dict,
                                startdate: datetime,
                                enddate: datetime,
                                amount: int) -> str:
        """
        生成汇总Excel报告
        
        Args:
            results: 回测结果列表
            output_file: 输出文件路径
            strategy_name: 策略名称
            strategy_params: 策略参数
            startdate: 开始日期
            enddate: 结束日期
            amount: 初始资金
            
        Returns:
            报告文件路径
        """
        # 创建DataFrame
        df = pd.DataFrame(results)
        
        # 按总收益率排序
        if '策略总收益率(%)' in df.columns:
            df = df.sort_values('策略总收益率(%)', ascending=False)
        
        # 生成Excel
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            # 主表：所有结果
            df.to_excel(writer, sheet_name='回测结果', index=False)
            
            # 统计表
            stats_data = []
            success_results = [r for r in results if r['status'] == 'success']
            
            if success_results:
                success_df = pd.DataFrame(success_results)
                
                stats_data.append(['统计项', '数值'])
                stats_data.append(['回测策略', strategy_name])
                stats_data.append(['策略参数', str(strategy_params)])
                stats_data.append(['回测时间范围', f"{startdate.date()} 至 {enddate.date()}"])
                stats_data.append(['初始资金', f"{amount:,}"])
                stats_data.append(['股票总数', len(results)])
                stats_data.append(['成功数', len(success_results)])
                stats_data.append(['失败数', len(results) - len(success_results)])
                stats_data.append(['', ''])
                
                # 关键指标统计
                for col in ['策略总收益率(%)', '年化收益率(%)', '最大回撤(%)', '夏普比率', '超额收益(%)']:
                    if col in success_df.columns:
                        values = pd.to_numeric(success_df[col], errors='coerce').dropna()
                        if len(values) > 0:
                            stats_data.append([f'{col}_平均', f"{values.mean():.2f}"])
                            stats_data.append([f'{col}_中位数', f"{values.median():.2f}"])
                            stats_data.append([f'{col}_最大', f"{values.max():.2f}"])
                            stats_data.append([f'{col}_最小', f"{values.min():.2f}"])
                            stats_data.append(['', ''])
                
                # 胜率统计
                if '策略总收益率(%)' in success_df.columns:
                    positive_count = len(success_df[success_df['策略总收益率(%)'] > 0])
                    win_rate = positive_count / len(success_df) * 100
                    stats_data.append(['盈利股票数', positive_count])
                    stats_data.append(['亏损股票数', len(success_df) - positive_count])
                    stats_data.append(['胜率(%)', f"{win_rate:.2f}"])
            
            stats_df = pd.DataFrame(stats_data)
            stats_df.to_excel(writer, sheet_name='统计汇总', index=False, header=False)
            
            # TOP10 盈利股票
            if success_results and '策略总收益率(%)' in df.columns:
                top10 = df.nlargest(10, '策略总收益率(%)')
                top10.to_excel(writer, sheet_name='TOP10盈利', index=False)
            
            # TOP10 亏损股票
            if success_results and '策略总收益率(%)' in df.columns:
                bottom10 = df.nsmallest(10, '策略总收益率(%)')
                bottom10.to_excel(writer, sheet_name='TOP10亏损', index=False)
        
        logging.info(f"汇总报告已生成: {output_file}")
        return output_file


def _run_single_backtest_worker(task: dict, counter, lock, total: int, results_list) -> Dict:
    """
    单个股票回测的工作函数（用于多进程）
    
    Args:
        task: 任务参数字典
        counter: 共享计数器
        lock: 用于保护counter的锁对象
        total: 总任务数
        results_list: 共享结果列表
        
    Returns:
        回测结果字典
    """
    code = task['code']
    
    try:
        # 捕获simulator.go_trade的所有输出
        output_buffer = io.StringIO()
        
        with redirect_stdout(output_buffer):
            # 执行回测（关闭可视化和交互）
            simulator.go_trade(
                code=code,
                amount=task['amount'],
                startdate=task['startdate'],
                enddate=task['enddate'],
                filepath=task['data_dir'],
                strategy=task['strategy_class'],
                strategy_params=task['strategy_params'],
                log_trades=False,  # 不记录详细交易日志
                visualize=False,   # 不生成可视化
                interactive_plot=False  # 不弹出交互图
            )
        
        # 解析输出
        output = output_buffer.getvalue()
        result = _parse_backtest_output(code, output)
        result['status'] = 'success'
        
    except Exception as e:
        result = {
            '股票代码': code,
            'status': 'failed',
            '错误信息': str(e)
        }
        logging.error(f"回测失败 {code}: {e}")
    
    # 更新进度
    with lock:
        counter.value += 1
        current = counter.value
        print(f"进度: {current}/{total} ({current/total*100:.1f}%) - 完成: {code}")
    
    # 添加到结果列表
    results_list.append(result)
    
    return result


def _parse_backtest_output(code: str, output: str) -> Dict:
    """
    解析回测输出，提取关键指标
    
    Args:
        code: 股票代码
        output: 回测输出文本
        
    Returns:
        指标字典
    """
    import re
    
    result = {'股票代码': code}
    
    # 定义要提取的指标及其正则表达式
    patterns = {
        '初始资金': r'初始资金:\s*([\d\.,]+)',
        '最终资金': r'回测结束后资金:\s*([\d\.,]+)',
        '最大回撤(%)': r'最大回撤:\s*([\d\.]+)%',
        '年化收益率(%)': r'年化收益率:\s*([\-\d\.]+)%',
        '夏普比率': r'夏普比率:\s*([\-\d\.]+)',
        '基准收益率(%)': r'基准收益率:\s*([\-\d\.]+)%',
        '策略总收益率(%)': r'策略总收益率:\s*([\-\d\.]+)%',
        '超额收益(%)': r'超额收益:\s*([\-\d\.]+)%',
        '总交易次数': r'总交易次数:\s*(\d+)',
        '盈利交易数': r'盈利交易数:\s*(\d+)',
        '胜率(%)': r'胜率:\s*([\d\.]+)%',
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            try:
                value = match.group(1).replace(',', '')
                # 尝试转换为数值
                result[key] = float(value) if '.' in value else int(value)
            except (ValueError, AttributeError):
                result[key] = match.group(1)
        else:
            result[key] = None
    
    return result


# --- 便捷函数 ---

def batch_backtest_from_file(
    stock_list_file: str,
    strategy_class,
    strategy_params: dict = None,
    startdate: datetime = None,
    enddate: datetime = None,
    amount: int = 100000,
    data_dir: str = './data/astocks',
    output_dir: str = 'bin/batch_backtest_results',
    max_workers: int = None,
    resume: bool = False
) -> str:
    """
    从文件批量回测的便捷函数
    
    Args:
        stock_list_file: 股票列表文件路径（CSV或TXT）
        strategy_class: 策略类
        strategy_params: 策略参数
        startdate: 回测开始日期，默认2022-01-01
        enddate: 回测结束日期，默认今天
        amount: 初始资金，默认100000
        data_dir: 股票数据目录
        output_dir: 输出目录
        max_workers: 最大并行进程数
        resume: 是否断点续传
        
    Returns:
        汇总报告文件路径
    """
    backtester = BatchBacktester(
        stock_list_file=stock_list_file,
        output_dir=output_dir,
        max_workers=max_workers
    )
    
    return backtester.run_batch_backtest(
        strategy_class=strategy_class,
        strategy_params=strategy_params,
        startdate=startdate,
        enddate=enddate,
        amount=amount,
        data_dir=data_dir,
        resume=resume
    )


def batch_backtest_from_list(
    stock_codes: List[str],
    strategy_class,
    strategy_params: dict = None,
    startdate: datetime = None,
    enddate: datetime = None,
    amount: int = 100000,
    data_dir: str = './data/astocks',
    output_dir: str = 'bin/batch_backtest_results',
    max_workers: int = None
) -> str:
    """
    从代码列表批量回测的便捷函数
    
    Args:
        stock_codes: 股票代码列表
        strategy_class: 策略类
        strategy_params: 策略参数
        startdate: 回测开始日期
        enddate: 回测结束日期
        amount: 初始资金
        data_dir: 股票数据目录
        output_dir: 输出目录
        max_workers: 最大并行进程数
        
    Returns:
        汇总报告文件路径
    """
    backtester = BatchBacktester(
        stock_codes=stock_codes,
        output_dir=output_dir,
        max_workers=max_workers
    )
    
    return backtester.run_batch_backtest(
        strategy_class=strategy_class,
        strategy_params=strategy_params,
        startdate=startdate,
        enddate=enddate,
        amount=amount,
        data_dir=data_dir
    ) 