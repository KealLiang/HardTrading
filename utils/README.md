# 中文词组分类和近义词处理工具

`synonyms_util.py` 是一个用于处理中文词组分类和近义词聚类的工具，特别适用于同花顺个股涨停原因中的近义词分析。该工具基于sentence-transformers实现，提供强大的语义相似度计算和词组分类功能。

## 功能特点

- 基于预训练的多语言语义模型，无需付费许可
- 使用K-Means聚类算法进行自动分类
- 支持语义相似度计算和近义词查找
- 可构建自定义近义词词典
- 完全开源免费，不依赖付费API

## 安装依赖

基本依赖：
```bash
pip install numpy scikit-learn sentence-transformers torch
```

## 使用方法

### 基本用法

```python
from utils.synonyms_util import SynonymClassifier, get_reason_categories

# 示例涨停原因
reasons = [
    "锂电池需求增长", "锂电材料涨价", "新能源汽车销量大增",
    "光伏政策利好", "太阳能装机量超预期", "国家补贴光伏",
    "新冠疫苗获批", "疫情检测需求激增", "抗疫药物上市"
]

# 对涨停原因进行分类（自动估计聚类数量）
categories = get_reason_categories(reasons)
for i, category in enumerate(categories):
    print(f"类别{i+1}: {category}")

# 对涨停原因进行分类（指定聚类数量）
categories = get_reason_categories(reasons, num_clusters=3)
for i, category in enumerate(categories):
    print(f"类别{i+1}: {category}")

# 查找近义词
classifier = SynonymClassifier()
synonyms = classifier.find_synonyms("锂电池", reasons, top_n=3)
for word, score in synonyms:
    print(f"{word}: {score:.4f}")
```

### 高级用法

#### 自定义相似度计算

```python
classifier = SynonymClassifier()

# 计算两个词组的语义相似度
similarity = classifier.calculate_similarity("锂电池需求增长", "锂电材料涨价")
print(f"相似度: {similarity:.4f}")
```

#### 使用不同的语义模型

```python
# 使用不同的预训练模型
classifier = SynonymClassifier(model_name='distiluse-base-multilingual-cased-v2')
```

#### 构建自定义近义词词典

```python
from utils.synonyms_util import build_custom_synonym_dict

# 构建自定义近义词词典
success = build_custom_synonym_dict(reasons, output_path='./data/custom_synonyms.txt')
```

## 支持的模型

sentence-transformers库提供了多种预训练的多语言模型，默认使用的是：
- `paraphrase-multilingual-MiniLM-L12-v2`：一个轻量级但性能良好的多语言模型

其他可选模型：
- `distiluse-base-multilingual-cased-v2`：更大的模型，可能有更好的性能
- `paraphrase-multilingual-mpnet-base-v2`：性能更好但需要更多资源

## 示例

完整的使用示例可以参考 `test_synonyms.py` 文件。

## 注意事项

- 首次使用时会自动下载预训练模型（约100MB），需要网络连接
- 模型加载需要一定时间，但加载后的推理速度较快
- 如果遇到内存不足问题，可以尝试使用更小的模型
- 该工具完全免费开源，不依赖任何付费API或许可 