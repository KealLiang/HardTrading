"""
同义词清理工具 - 删除未使用的旧概念词

删除条件：
- 在指定回溯期内（默认30天），复盘数据中没有出现过的同义词会被删除
- 精确匹配词：检查是否有概念词包含该同义词
- 模糊匹配词（%xxx%）：检查是否有概念词能被该模式匹配

数据来源：
- excel/fupan_stocks.xlsx 的【连板数据】和【首板数据】sheet
- 从每日股票的涨停原因类别中提取概念词（用+分隔）
"""

import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
import pandas as pd

from data.reasons.origin_synonym_groups import synonym_groups


class SynonymCleaner:
    
    def __init__(self, lookback_days=30):
        self.lookback_days = lookback_days
        self.fupan_file = "./excel/fupan_stocks.xlsx"
        
    def get_recent_concepts(self, start_date=None):
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=self.lookback_days)).strftime('%Y%m%d')
        
        print(f"\n从复盘数据提取近期概念词（自 {start_date} 起）...")
        
        if not os.path.exists(self.fupan_file):
            print(f"错误：复盘数据文件不存在: {self.fupan_file}")
            return set()
        
        recent_concepts = set()
        
        # 读取连板数据和首板数据
        sheets_to_process = ['连板数据', '首板数据']
        
        for sheet_name in sheets_to_process:
            try:
                df = pd.read_excel(self.fupan_file, sheet_name=sheet_name, index_col=0)
                
                # 获取所有日期列
                for col in df.columns:
                    # 解析日期
                    try:
                        if '年' in str(col):
                            date_obj = datetime.strptime(str(col), '%Y年%m月%d日')
                        else:
                            date_obj = pd.to_datetime(col)
                        
                        date_str = date_obj.strftime('%Y%m%d')
                        
                        # 只处理指定日期范围内的数据
                        if date_str < start_date:
                            continue
                        
                    except Exception:
                        continue
                    
                    column_data = df[col].dropna()
                    
                    for data_str in column_data:
                        items = str(data_str).split('; ')
                        
                        for item in items:
                            if '+' in item and len(item.split('+')) > 1:
                                concepts = [c.strip() for c in item.split('+') if c.strip()]
                                recent_concepts.update(concepts)
                
                print(f"  从 {sheet_name} 提取了 {len(recent_concepts)} 个概念词")
                
            except Exception as e:
                print(f"  读取 {sheet_name} 失败: {e}")
                continue
        
        print(f"\n✓ 共提取 {len(recent_concepts)} 个不重复的原始概念词")
        return recent_concepts
    
    def find_unused_synonyms(self, recent_concepts):
        print(f"\n分析未使用的同义词...")
        
        unused_by_group = defaultdict(list)
        used_count = 0
        unused_count = 0
        
        for group_name, synonyms in synonym_groups.items():
            for synonym in synonyms:
                is_used = False
                
                if '%' in synonym:
                    pattern = synonym.replace('%', '(.*)')
                    regex = re.compile(f"^{pattern}$")
                    
                    for concept in recent_concepts:
                        concept_clean = re.sub(r'\s+', '', concept)
                        if regex.search(concept_clean):
                            is_used = True
                            break
                else:
                    for concept in recent_concepts:
                        concept_clean = re.sub(r'\s+', '', concept)
                        if synonym in concept_clean:
                            is_used = True
                            break
                
                if is_used:
                    used_count += 1
                else:
                    unused_by_group[group_name].append(synonym)
                    unused_count += 1
        
        print(f"  已使用的同义词: {used_count} 个")
        print(f"  未使用的同义词: {unused_count} 个")
        
        return dict(unused_by_group)
    
    def generate_cleaned_file(self, unused_by_group, output_file=None):
        if output_file is None:
            output_file = "./data/reasons/origin_synonym_groups_cleaned.py"
        
        print(f"\n生成清理后的文件...")
        
        cleaned_groups = {}
        removed_groups = []
        
        for group_name, synonyms in synonym_groups.items():
            unused_synonyms = set(unused_by_group.get(group_name, []))
            cleaned_synonyms = [s for s in synonyms if s not in unused_synonyms]
            
            if cleaned_synonyms:
                cleaned_groups[group_name] = cleaned_synonyms
            else:
                removed_groups.append(group_name)
        
        lines = []
        lines.append("# 同义词组定义（已清理未使用的词）")
        lines.append(f"# 清理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"# 清理规则: 保留近{self.lookback_days}天内使用过的概念词")
        lines.append("synonym_groups = {")
        
        for group_name in synonym_groups.keys():
            if group_name in cleaned_groups:
                synonyms = cleaned_groups[group_name]
                synonyms_str = ', '.join([f'"{s}"' for s in synonyms])
                lines.append(f'    "{group_name}": [{synonyms_str}],')
        
        lines.append("}")
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"✓ 已生成清理后的文件: {output_file}")
        self._generate_report(unused_by_group, removed_groups, output_file)
        
        return output_file
    
    def _generate_report(self, unused_by_group, removed_groups, cleaned_file):
        report_file = cleaned_file.replace('.py', '_report.txt')
        
        lines = []
        lines.append("=" * 80)
        lines.append("同义词清理报告")
        lines.append("=" * 80)
        lines.append(f"清理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"清理规则: 保留近{self.lookback_days}天内使用过的概念词")
        lines.append(f"原始分组数: {len(synonym_groups)}")
        lines.append(f"清理后分组数: {len(synonym_groups) - len(removed_groups)}")
        lines.append(f"删除的分组数: {len(removed_groups)}")
        lines.append("")
        
        total_removed = sum(len(syns) for syns in unused_by_group.values())
        total_original = sum(len(syns) for syns in synonym_groups.values())
        
        lines.append(f"原始同义词总数: {total_original}")
        lines.append(f"删除的同义词数: {total_removed}")
        lines.append(f"保留的同义词数: {total_original - total_removed}")
        lines.append(f"删除比例: {total_removed / total_original * 100:.1f}%")
        lines.append("")
        lines.append("=" * 80)
        
        if removed_groups:
            lines.append("\n【完全删除的分组】\n")
            for group in removed_groups:
                lines.append(f"  • {group}")
        
        lines.append("\n【部分清理的分组】\n")
        for group_name in synonym_groups.keys():
            if group_name not in removed_groups:
                unused = unused_by_group.get(group_name, [])
                if unused:
                    lines.append(f"\n{group_name}:")
                    lines.append(f"  原有: {len(synonym_groups[group_name])} 个同义词")
                    lines.append(f"  删除: {len(unused)} 个同义词")
                    lines.append(f"  删除的词: {', '.join(unused)}")
        
        lines.append("\n" + "=" * 80)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        
        print(f"✓ 已生成清理报告: {report_file}")
    
    def clean(self, start_date=None, output_file=None, dry_run=False):
        print("=" * 80)
        print("开始清理未使用的同义词")
        print("=" * 80)
        
        recent_concepts = self.get_recent_concepts(start_date)
        
        if not recent_concepts:
            print("❌ 未能获取近期概念词，清理终止")
            return None
        
        unused_by_group = self.find_unused_synonyms(recent_concepts)
        
        if dry_run:
            print("\n[DRY RUN] 只生成报告，不创建清理后的文件")
            self._generate_report(unused_by_group, [], "./data/reasons/dry_run_report.txt")
            return None
        else:
            return self.generate_cleaned_file(unused_by_group, output_file) 