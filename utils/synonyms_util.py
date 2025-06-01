"""
中文词组分类和近义词处理工具
主要用于处理同花顺个股涨停原因中的近义词，以便更好地进行分析
基于sentence-transformers的免费开源解决方案
"""
import os
import re
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity

# 尝试导入sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    print("未安装sentence-transformers库，请使用 pip install sentence-transformers 安装")

# 默认使用的模型名称
DEFAULT_MODEL = 'paraphrase-multilingual-MiniLM-L12-v2'


class SynonymClassifier:
    """同义词分类器，基于sentence-transformers实现"""
    
    def __init__(self, model_name=DEFAULT_MODEL):
        """
        初始化同义词分类器
        
        Args:
            model_name: 使用的sentence-transformers模型名称
        """
        self.model_name = model_name
        self.model = None
        
        # 初始化模型
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.model = SentenceTransformer(model_name)
                print(f"成功加载语义模型: {model_name}")
            except Exception as e:
                print(f"加载语义模型失败: {str(e)}")
                print("可能是网络问题或模型不存在，请检查网络连接或更换模型")
    
    def preprocess(self, text):
        """
        预处理文本
        
        Args:
            text: 输入文本
            
        Returns:
            str: 预处理后的文本
        """
        if not text:
            return ""
        
        # 去除特殊字符和多余空格
        text = re.sub(r'[^\w\s\u4e00-\u9fff]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def encode_texts(self, texts):
        """
        将文本列表转换为向量表示
        
        Args:
            texts: 文本列表
            
        Returns:
            numpy.ndarray: 文本向量矩阵
        """
        if not self.model:
            raise ValueError("模型未成功加载，无法编码文本")
        
        # 预处理文本
        processed_texts = [self.preprocess(text) for text in texts]
        
        # 编码文本
        return self.model.encode(processed_texts, convert_to_tensor=False)
    
    def calculate_similarity(self, text1, text2):
        """
        计算两个文本的语义相似度
        
        Args:
            text1: 第一个文本
            text2: 第二个文本
            
        Returns:
            float: 相似度分数，范围[0,1]
        """
        if not self.model:
            return self._char_similarity(text1, text2)
        
        # 预处理文本
        text1 = self.preprocess(text1)
        text2 = self.preprocess(text2)
        
        if not text1 or not text2:
            return 0.0
        
        # 编码文本
        embedding1 = self.model.encode(text1, convert_to_tensor=False).reshape(1, -1)
        embedding2 = self.model.encode(text2, convert_to_tensor=False).reshape(1, -1)
        
        # 计算余弦相似度
        return float(cosine_similarity(embedding1, embedding2)[0][0])
    
    def _char_similarity(self, text1, text2):
        """字符相似度计算（Dice系数），作为后备方案"""
        text1 = self.preprocess(text1)
        text2 = self.preprocess(text2)
        
        if not text1 or not text2:
            return 0.0
        
        # 计算公共字符数
        common_chars = sum(1 for c in text1 if c in text2)
        # Dice系数: 2*common / (len1 + len2)
        return (2 * common_chars) / (len(text1) + len(text2))
    
    def classify_phrases(self, phrases, num_clusters=None):
        """
        对词组列表进行分类
        
        Args:
            phrases: 词组列表
            num_clusters: 聚类数量，如果为None则自动估计
            
        Returns:
            list: 分类结果，每个类别是一个词组列表
        """
        if not phrases:
            return []
        
        if not self.model:
            print("模型未成功加载，无法进行分类")
            return []
        
        # 预处理
        processed_phrases = [self.preprocess(p) for p in phrases]
        
        # 生成语义向量
        try:
            embeddings = self.model.encode(processed_phrases, convert_to_tensor=False)
        except Exception as e:
            print(f"生成语义向量失败: {str(e)}")
            return []
        
        # 估计聚类数量（如果未指定）
        if num_clusters is None:
            num_clusters = min(max(2, len(phrases) // 3), len(phrases) - 1)
        
        # 确保聚类数量合理
        num_clusters = min(max(1, num_clusters), len(phrases))
        
        # K-Means聚类
        try:
            kmeans = KMeans(n_clusters=num_clusters, random_state=0, n_init=10)
            clusters = kmeans.fit_predict(embeddings)
        except Exception as e:
            print(f"聚类失败: {str(e)}")
            return []
        
        # 整理聚类结果
        result = [[] for _ in range(num_clusters)]
        for i, label in enumerate(clusters):
            result[label].append(phrases[i])
        
        # 过滤空类别
        result = [cluster for cluster in result if cluster]
        
        return result
    
    def find_synonyms(self, word, word_list, top_n=5):
        """
        查找近义词
        
        Args:
            word: 目标词
            word_list: 候选词列表
            top_n: 返回的近义词数量
            
        Returns:
            list: (word, similarity) 元组列表
        """
        if not word or not word_list:
            return []
        
        if not self.model:
            # 使用字符相似度作为后备方案
            similarities = [(w, self._char_similarity(word, w)) for w in word_list]
        else:
            # 生成语义向量
            word_embedding = self.model.encode(self.preprocess(word), convert_to_tensor=False).reshape(1, -1)
            word_list_embeddings = self.model.encode([self.preprocess(w) for w in word_list], convert_to_tensor=False)
            
            # 计算相似度
            similarities = []
            for i, w in enumerate(word_list):
                sim = cosine_similarity(word_embedding, word_list_embeddings[i].reshape(1, -1))[0][0]
                similarities.append((w, float(sim)))
        
        # 排序并返回top_n个结果
        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_n]


def get_reason_categories(reasons, num_clusters=None):
    """
    对同花顺涨停原因进行分类
    
    Args:
        reasons: 涨停原因列表
        num_clusters: 聚类数量，如果为None则自动估计
        
    Returns:
        list: 分类后的涨停原因
    """
    classifier = SynonymClassifier()
    categories = classifier.classify_phrases(reasons, num_clusters=num_clusters)
    
    # 按类别大小排序
    categories.sort(key=len, reverse=True)
    return categories


def build_custom_synonym_dict(phrases, output_path='./data/custom_synonyms.txt'):
    """
    构建自定义近义词词典
    
    Args:
        phrases: 词组列表
        output_path: 输出文件路径
        
    Returns:
        bool: 是否成功
    """
    categories = get_reason_categories(phrases)
    
    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            for category in categories:
                if len(category) > 1:
                    f.write(' '.join(category) + '\n')
        return True
    except Exception as e:
        print(f"构建自定义近义词词典失败: {str(e)}")
        return False


# 示例用法
if __name__ == "__main__":
    # 示例涨停原因
    phrases = [
        "锂电池需求增长", "锂电材料涨价", "新能源汽车销量大增",
        "光伏政策利好", "太阳能装机量超预期", "国家补贴光伏",
        "新冠疫苗获批", "疫情检测需求激增", "抗疫药物上市"
    ]
    
    # 初始化分类器
    classifier = SynonymClassifier()
    
    # 分类
    categories = classifier.classify_phrases(phrases, num_clusters=3)
    print("\n涨停原因分类结果:")
    for i, category in enumerate(categories):
        print(f"类别{i+1}: {category}")
    
    # 查找近义词
    synonyms = classifier.find_synonyms("锂电池", phrases, top_n=3)
    print("\n'锂电池'的近义词:")
    for word, score in synonyms:
        print(f"{word}: {score:.4f}")