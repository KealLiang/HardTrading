#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
同义词分组管理工具
整合了生成和更新synonym_groups的功能
"""
import os
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from utils.synonyms_util import SynonymClassifier
import re


class SynonymManager:
    """同义词分组管理器，用于生成和更新synonym_groups"""
    
    def __init__(self, threshold=0.7, min_group_size=3, disable_progress_bar=True):
        """
        初始化同义词分组管理器
        
        Args:
            threshold: 相似度阈值，默认为0.7
            min_group_size: 最小分组大小，默认为2
            disable_progress_bar: 是否禁用进度条，默认为True
        """
        self.threshold = threshold
        self.min_group_size = min_group_size
        self.disable_progress_bar = disable_progress_bar
        
        # 设置环境变量以禁用tqdm进度条
        if self.disable_progress_bar:
            import os
            os.environ["TOKENIZERS_PARALLELISM"] = "false"
            os.environ["TQDM_DISABLE"] = "true"
            
        # 抑制jieba的警告
        import warnings
        warnings.filterwarnings("ignore", category=UserWarning, module="jieba._compat")
        
        self.classifier = SynonymClassifier()
        
        # 设置当前工作目录为项目根目录
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    def get_default_dates(self):
        """
        获取默认的日期范围：最近1个月
        
        Returns:
            tuple: (start_date, end_date) - 格式为'YYYYMMDD'
        """
        today = datetime.now()
        start_date = (today - timedelta(days=30)).strftime('%Y%m%d')
        end_date = today.strftime('%Y%m%d')
        return start_date, end_date
    
    def load_reasons_file(self, file_path):
        """
        加载保存的涨停原因JSON文件
        
        Args:
            file_path: JSON文件路径
            
        Returns:
            dict: 包含涨停原因的字典
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"加载涨停原因文件失败: {str(e)}")
            return None
    
    def load_current_synonym_groups(self):
        """
        从theme_color_util.py中加载当前的synonym_groups
        
        Returns:
            dict: 当前的synonym_groups字典
        """
        try:
            from utils.theme_color_util import synonym_groups
            return synonym_groups
        except ImportError:
            print("无法导入theme_color_util中的synonym_groups，将创建新的分组")
            return {}
    
    def generate_updated_groups(self, reasons_data, current_groups=None):
        """
        生成更新的synonym_groups
        
        Args:
            reasons_data: 包含涨停原因的字典
            current_groups: 当前的synonym_groups字典，如果为None则创建新的
            
        Returns:
            dict: 更新后的synonym_groups字典
        """
        if current_groups is None:
            current_groups = {}
        
        # 合并已分类和未分类的原因
        all_reasons = {}
        if "classified" in reasons_data:
            all_reasons.update(reasons_data["classified"])
        if "unclassified" in reasons_data:
            all_reasons.update(reasons_data["unclassified"])
        
        # 按出现次数排序
        sorted_reasons = sorted(all_reasons.items(), key=lambda x: x[1], reverse=True)
        reason_list = [r[0] for r in sorted_reasons]
        
        print(f"正在处理 {len(reason_list)} 个原因...")
        
        # 保留原有分组顺序
        updated_groups = {}
        # 记录原有分组顺序
        original_group_order = list(current_groups.keys())
        # 新增的分组
        new_groups = {}
        
        processed_reasons = set()
        
        # 存储每个原因与每个组的最大相似度
        reason_to_group_similarities = {}
        
        # 1. 首先计算所有原因与所有现有分组的相似度
        print("第一阶段: 计算所有原因与所有分组的相似度...")
        for group_name in original_group_order:
            synonyms = current_groups[group_name]
            print(f"处理分组: {group_name}，包含 {len(synonyms)} 个同义词")
            
            # 过滤掉已处理的原因
            unprocessed_reasons = [r for r in reason_list if r not in processed_reasons]
            if not unprocessed_reasons:
                continue
            
            # 对于每个未处理的原因，计算与分组中所有词的相似度
            for reason in unprocessed_reasons:
                # 检查是否能被组内现有的模糊匹配词组匹配上
                matched_by_wildcard = False
                for syn in synonyms:
                    if '%' in syn:
                        # 将SQL风格通配符转换为正则表达式
                        pattern = syn.replace('%', '(.*)')
                        regex = re.compile(f"^{pattern}$")
                        if regex.search(reason):
                            # 如果能被模糊匹配，设置一个最高相似度
                            if reason not in reason_to_group_similarities:
                                reason_to_group_similarities[reason] = {}
                            reason_to_group_similarities[reason][group_name] = 1.0  # 最高相似度
                            matched_by_wildcard = True
                            break
                
                if matched_by_wildcard:
                    continue
                
                # 计算与分组名的相似度
                similarity_with_name = self.classifier.calculate_similarity(reason, group_name)
                
                # 批量计算与分组内所有词的相似度
                similarities = self.classifier.calculate_similarities_batch(reason, synonyms)
                max_similarity = max([similarity_with_name] + similarities)
                
                # 如果相似度超过阈值，记录这个相似度
                if max_similarity >= self.threshold:
                    if reason not in reason_to_group_similarities:
                        reason_to_group_similarities[reason] = {}
                    reason_to_group_similarities[reason][group_name] = max_similarity
        
        # 2. 根据相似度将每个原因分配到最佳匹配的组
        print("第二阶段: 根据相似度将原因分配到最佳匹配的组...")
        group_to_new_reasons = {group_name: set() for group_name in original_group_order}
        
        for reason, group_similarities in reason_to_group_similarities.items():
            if not group_similarities:
                continue
            
            # 找出最佳匹配的组
            best_group = max(group_similarities.items(), key=lambda x: x[1])[0]
            group_to_new_reasons[best_group].add(reason)
            processed_reasons.add(reason)
        
        # 3. 更新每个组，保持原有顺序
        print("第三阶段: 更新每个组，保持原有顺序...")
        for group_name in original_group_order:
            synonyms = current_groups[group_name]
            new_reasons = group_to_new_reasons.get(group_name, set())
            
            if not new_reasons:
                # 如果没有新的原因，直接保留现有分组
                updated_groups[group_name] = list(synonyms)
                continue
            
            # 合并原有同义词和新原因，保持原有顺序
            ordered_synonyms = []
            # 先添加原有的同义词（保持顺序）
            for syn in synonyms:
                ordered_synonyms.append(syn)
            # 再添加新的同义词（按字母顺序）
            ordered_synonyms.extend(sorted(new_reasons))
            
            updated_groups[group_name] = ordered_synonyms
        
        # 4. 对剩余未处理的原因进行聚类
        remaining_reasons = [r for r in reason_list if r not in processed_reasons]
        if remaining_reasons:
            print(f"第四阶段: 对 {len(remaining_reasons)} 个未处理原因进行聚类...")
            # 使用分类器进行聚类
            clusters = self.classifier.classify_phrases(remaining_reasons, num_clusters=None)
            
            # 只保留大小大于等于min_group_size的簇
            valid_clusters = [c for c in clusters if len(c) >= self.min_group_size]
            print(f"生成了 {len(valid_clusters)} 个有效聚类")
            
            # 为每个有效簇创建新分组
            for i, cluster in enumerate(valid_clusters):
                # 选择簇中出现频率最高的原因作为组名
                best_group_name = max(cluster, key=lambda x: all_reasons.get(x, 0))
                
                # 避免组名冲突
                group_name = best_group_name
                counter = 1
                while group_name in updated_groups or group_name in new_groups:
                    group_name = f"{best_group_name}_{counter}"
                    counter += 1
                
                new_groups[group_name] = sorted(cluster)  # 按字母顺序排序
                for reason in cluster:
                    processed_reasons.add(reason)
        
        # 5. 对于单个未分组的高频原因，创建单独的分组
        high_freq_groups = {}
        for reason, count in sorted_reasons:
            if reason not in processed_reasons and count >= 10:  # 出现10次以上的高频原因
                high_freq_groups[reason] = [reason]
                processed_reasons.add(reason)
        
        # 将新分组按照组名字母顺序排序，然后添加到更新后的分组中
        # 先添加聚类生成的新分组
        for group_name in sorted(new_groups.keys()):
            updated_groups[group_name] = new_groups[group_name]
        
        # 再添加高频单词分组
        for group_name in sorted(high_freq_groups.keys()):
            updated_groups[group_name] = high_freq_groups[group_name]
        
        print(f"最终生成了 {len(updated_groups)} 个分组，覆盖了 {len(processed_reasons)} 个原因")
        print(f"其中保留了 {len(original_group_order)} 个原有分组，新增了 {len(updated_groups) - len(original_group_order)} 个分组")
        return updated_groups
    
    def format_synonym_groups_code(self, groups):
        """
        格式化synonym_groups代码
        
        Args:
            groups: 分组字典
            
        Returns:
            str: 格式化的代码字符串
        """
        code = "synonym_groups = {\n"
        
        # 使用原始顺序，不再按组内元素数量排序
        for group_name, synonyms in groups.items():
            # 检查并去除被通配符覆盖的完全匹配词
            cleaned_synonyms = []
            wildcard_patterns = []
            
            # 先收集所有通配符模式
            for syn in synonyms:
                if '%' in syn:
                    # 将SQL风格通配符转换为正则表达式
                    pattern = syn.replace('%', '(.*)')
                    wildcard_patterns.append((syn, re.compile(f"^{pattern}$")))
            
            # 检查每个同义词是否被通配符覆盖
            for syn in synonyms:
                if '%' in syn:
                    # 通配符总是保留
                    cleaned_synonyms.append(syn)
                else:
                    # 检查是否被任何通配符覆盖
                    covered = False
                    for wildcard, regex in wildcard_patterns:
                        if regex.search(syn) and wildcard != syn:
                            covered = True
                            break
                    
                    if not covered:
                        cleaned_synonyms.append(syn)
            
            # 对每个同义词添加引号
            quoted_synonyms = []
            for syn in cleaned_synonyms:
                quoted_synonyms.append(f'"{syn}"')
            
            # 格式化该组的代码
            code += f'    "{group_name}": [{", ".join(quoted_synonyms)}],\n'
        
        code += "}"
        return code
    
    def save_code_to_file(self, code, output_file):
        """
        将生成的代码保存到文件
        
        Args:
            code: 代码字符串
            output_file: 输出文件路径
            
        Returns:
            bool: 是否成功保存
        """
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(code)
            return True
        except Exception as e:
            print(f"保存代码文件失败: {str(e)}")
            return False
    
    def process_from_file(self, input_file, output_file=None):
        """
        从指定的JSON文件生成更新的synonym_groups
        
        Args:
            input_file: 涨停原因JSON文件路径
            output_file: 输出代码文件路径，默认为None（自动生成）
            
        Returns:
            bool: 是否成功
        """
        print(f"=== 从文件生成更新的synonym_groups ===")
        print(f"使用文件: {input_file}")
        print(f"相似度阈值: {self.threshold}")
        print(f"最小分组大小: {self.min_group_size}")
        
        # 加载涨停原因
        print("正在加载涨停原因数据...")
        reasons_data = self.load_reasons_file(input_file)
        if not reasons_data:
            return False
            
        # 统计原因数量
        total_classified = reasons_data.get("total_classified", 0)
        total_unclassified = reasons_data.get("total_unclassified", 0)
        print(f"已加载 {total_classified} 个已分类原因和 {total_unclassified} 个未分类原因")
        
        # 加载当前的synonym_groups
        print("正在加载现有同义词分组...")
        current_groups = self.load_current_synonym_groups()
        print(f"已加载 {len(current_groups)} 个现有分组")
        
        # 生成更新的分组
        print("正在生成更新的分组...")
        updated_groups = self.generate_updated_groups(reasons_data, current_groups)
        print(f"已生成 {len(updated_groups)} 个更新后的分组")
        
        # 格式化代码
        print("正在格式化代码...")
        code = self.format_synonym_groups_code(updated_groups)
        
        # 如果未指定输出文件，使用默认值
        if not output_file:
            # 从输入文件名提取日期范围
            file_name = os.path.basename(input_file)
            file_base = os.path.splitext(file_name)[0]
            output_file = f"./data/reasons/updated_synonym_groups_{file_base}.py"
        
        # 保存代码
        print(f"正在保存代码到 {output_file}...")
        if self.save_code_to_file(code, output_file):
            print(f"成功生成更新的synonym_groups代码，保存到: {output_file}")
            print(f"共生成{len(updated_groups)}个分组")
            
            # 打印使用说明
            print("\n=== 使用说明 ===")
            print("1. 检查生成的代码文件，确认分组是否合理")
            print("2. 如需调整，可以修改相似度阈值或最小分组大小后重新运行")
            print("3. 确认无误后，可以将生成的代码复制到utils/theme_color_util.py中替换现有的synonym_groups")
            return True
        else:
            print("生成代码失败")
            return False
    
    def find_latest_reasons_file(self):
        """
        查找最新的涨停原因JSON文件
        
        Returns:
            str: 文件路径，如果未找到则返回None
        """
        reasons_dir = Path("./data/reasons")
        if reasons_dir.exists():
            json_files = list(reasons_dir.glob("*.json"))
            if json_files:
                return str(max(json_files, key=os.path.getmtime))
        return None

    def update_from_latest_file(self):
        """
        从最新的涨停原因文件更新同义词分组
        
        Returns:
            bool: 是否成功
        """
        # 查找最新的涨停原因JSON文件
        reasons_dir = Path("./data/reasons")
        if not reasons_dir.exists():
            print(f"错误: 未找到涨停原因目录: {reasons_dir}")
            print("请先运行whimsical_fupan_analyze()生成涨停原因数据")
            return False
        
        json_files = list(reasons_dir.glob("unique_reasons_*.json"))
        if not json_files:
            print("错误: 未找到涨停原因JSON文件")
            print("请先运行whimsical_fupan_analyze()生成涨停原因数据")
            return False
        
        # 获取最新的JSON文件
        latest_file = str(max(json_files, key=os.path.getmtime))
        print(f"找到最新的涨停原因文件: {latest_file}")
        
        # 从文件生成更新的synonym_groups
        success = self.process_from_file(latest_file)
        
        if success:
            print("同义词分组更新成功，请检查生成的文件并手动更新theme_color_util.py")
        else:
            print("同义词分组更新失败，请检查日志")
        
        return success


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="同义词分组管理工具")
    parser.add_argument("--input", "-i", help="涨停原因JSON文件路径")
    parser.add_argument("--output", "-o", help="输出代码文件路径")
    parser.add_argument("--threshold", "-t", type=float, help="相似度阈值", default=0.7)
    parser.add_argument("--min-group", "-g", type=int, help="最小分组大小", default=2)
    args = parser.parse_args()
    
    # 创建同义词分组管理器
    manager = SynonymManager(threshold=args.threshold, min_group_size=args.min_group)
    
    # 从文件生成
    input_file = args.input
    if not input_file:
        # 如果未指定输入文件，使用最新的
        input_file = manager.find_latest_reasons_file()
    
    if not input_file:
        print("错误: 未指定输入文件，且未找到默认文件")
        return
    
    manager.process_from_file(input_file, args.output)


if __name__ == "__main__":
    main() 