"""
中文语义分析工具模块，用于支持涨停概念的分类和聚类分析
"""
import os
import sys

import jieba
import numpy as np

# 全局变量
WORD2VEC_MODEL_PATH = "./models/chinese_word2vec.bin"
# 强制使用字符相似度模式（无需gensim）
FORCE_CHAR_SIMILARITY = True

# 检查gensim是否可用（如果不强制使用字符相似度）
GENSIM_AVAILABLE = False
if not FORCE_CHAR_SIMILARITY:
    try:
        import gensim
        from gensim.models import KeyedVectors

        # 检查版本是否太旧
        if tuple(map(int, gensim.__version__.split('.')[:2])) < (4, 0):
            print(f"警告: gensim版本过旧 ({gensim.__version__})，需要4.0以上版本")
            print("由于兼容性问题，将使用字符相似度模式")
            GENSIM_AVAILABLE = False
        else:
            GENSIM_AVAILABLE = True
    except ImportError:
        print("未安装gensim，将使用字符相似度模式")
        GENSIM_AVAILABLE = False
    except Exception as e:
        print(f"gensim导入出错: {e}，将使用字符相似度模式")
        GENSIM_AVAILABLE = False


def check_nlp_ready():
    """
    检查NLP环境是否准备就绪，返回可用状态和词向量模型
    
    Returns:
        tuple: (is_ready, word_vectors, message)
    """
    # 如果强制使用字符相似度模式，直接返回不可用
    if FORCE_CHAR_SIMILARITY:
        return False, None, "已启用字符相似度模式，不使用gensim"

    # 打印详细的环境信息，帮助调试
    print(f"Python版本: {sys.version}")

    if 'gensim' in sys.modules:
        gensim_version = getattr(sys.modules['gensim'], '__version__', '未知')
        print(f"gensim版本: {gensim_version}")
    else:
        print("gensim未成功导入")

    print(f"numpy版本: {np.__version__}")
    print(f"jieba版本: {jieba.__version__}")

    if not GENSIM_AVAILABLE:
        message = "未安装兼容版本的gensim，将使用字符相似度分析"
        if 'gensim' in sys.modules:
            message += f"\n当前gensim版本({sys.modules['gensim'].__version__})不兼容"
        return False, None, message

    try:
        if os.path.exists(WORD2VEC_MODEL_PATH):
            try:
                # 加载词向量模型
                word_vectors = KeyedVectors.load_word2vec_format(WORD2VEC_MODEL_PATH, binary=True)
                print(f"成功加载词向量，词汇量: {len(word_vectors.index_to_key)}")
                return True, word_vectors, f"成功加载词向量模型: {WORD2VEC_MODEL_PATH}"
            except Exception as e:
                return False, None, f"加载词向量模型失败: {str(e)}"
        else:
            return False, None, f"词向量模型文件不存在: {WORD2VEC_MODEL_PATH}，请先调用download_word2vec_model()"
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        return False, None, f"加载词向量模型失败: {str(e)}\n{error_details}"


def text_to_vec(text, word_vectors, default_vector=None):
    """
    将文本转换为词向量的平均值
    
    Args:
        text: 文本内容
        word_vectors: 词向量模型
        default_vector: 默认向量（当无法提取有效向量时返回）
        
    Returns:
        numpy.ndarray: 文本的向量表示
    """
    if word_vectors is None:
        return None

    if default_vector is None:
        default_vector = np.zeros(word_vectors.vector_size)

    words = jieba.cut(text)
    vec = np.zeros(word_vectors.vector_size)
    count = 0

    for word in words:
        if word in word_vectors:
            vec += word_vectors[word]
            count += 1

    if count > 0:
        return vec / count
    return default_vector


def calc_similarity(text1, text2, word_vectors=None):
    """
    计算两段文本的语义相似度（余弦相似度）
    如果word_vectors不可用，则使用字符匹配相似度作为后备方案
    
    Args:
        text1: 第一段文本
        text2: 第二段文本
        word_vectors: 词向量模型，如果为None则使用字符匹配
        
    Returns:
        float: 相似度分数，范围[0,1]
    """
    # 如果没有词向量模型，使用字符匹配相似度
    if word_vectors is None:
        return char_similarity(text1, text2)

    vec1 = text_to_vec(text1, word_vectors)
    vec2 = text_to_vec(text2, word_vectors)

    if vec1 is None or vec2 is None:
        return char_similarity(text1, text2)

    # 计算余弦相似度
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return np.dot(vec1, vec2) / (norm1 * norm2)


def char_similarity(text1, text2):
    """
    计算两段文本的字符相似度（不需要gensim）
    
    Args:
        text1: 第一段文本
        text2: 第二段文本
        
    Returns:
        float: 相似度分数，范围[0,1]
    """
    # 计算公共字符数
    common_chars = sum(1 for c in text1 if c in text2)

    # 使用Dice系数: 2*common / (len1 + len2)
    if not text1 or not text2:
        return 0.0

    return (2 * common_chars) / (len(text1) + len(text2))


def find_semantic_clusters(items, word_vectors=None, threshold=0.7):
    """
    基于相似度对项目进行聚类
    
    Args:
        items: 待聚类的项目字典 {item: weight}
        word_vectors: 词向量模型，如果为None则使用字符相似度
        threshold: 聚类相似度阈值
        
    Returns:
        list: 聚类结果，每个簇是项目和权重的列表 [(item, weight), ...]
    """
    clustered = set()
    clusters = []

    items_list = list(items.keys())
    for i, item1 in enumerate(items_list):
        if item1 in clustered:
            continue

        cluster = [(item1, items[item1])]
        clustered.add(item1)

        for item2 in items_list[i + 1:]:
            if item2 in clustered:
                continue

            # 使用适当的相似度函数
            if word_vectors is not None:
                sim_score = calc_similarity(item1, item2, word_vectors)
            else:
                sim_score = char_similarity(item1, item2)
                # 字符相似度使用稍低的阈值
                threshold = 0.5

            if sim_score > threshold:
                cluster.append((item2, items[item2]))
                clustered.add(item2)

        if len(cluster) > 1:  # 至少形成了一个簇
            clusters.append(cluster)

    return clusters


def download_word2vec_model(model_url=None):
    """
    下载中文词向量模型
    
    Args:
        model_url: 词向量模型下载地址，默认使用腾讯AI Lab词向量
        
    Returns:
        bool: 下载是否成功
    """
    if not GENSIM_AVAILABLE:
        print("请先安装必要的库: pip install --only-binary=:all: gensim numpy jieba tqdm requests")
        return False

    try:
        import requests
        from tqdm import tqdm
        import tarfile

        # 创建models目录
        os.makedirs("./models", exist_ok=True)

        # 词向量模型下载链接
        if model_url is None:
            # 腾讯AI Lab中文词向量模型精简版 (约200MB)
            model_url = "https://ai.tencent.com/ailab/nlp/en/data/tencent-ailab-embedding-zh-d100-v0.2.0-s.tar.gz"

        print(f"开始下载中文词向量模型...")

        # 下载文件
        r = requests.get(model_url, stream=True)
        total_size = int(r.headers.get('content-length', 0))

        tar_path = "./models/chinese_word2vec.tar.gz"
        with open(tar_path, 'wb') as f:
            for data in tqdm(r.iter_content(chunk_size=1024), total=total_size // 1024, unit='KB'):
                f.write(data)

        print(f"下载完成！正在解压...")

        # 解压文件
        with tarfile.open(tar_path, 'r:gz') as tar:
            tar.extractall("./models")

        # 将解压后的文件转换为gensim可用的格式
        print("正在转换为gensim格式...")

        # 找到解压后的文件名
        txt_file = None
        for root, dirs, files in os.walk("./models"):
            for file in files:
                if file.endswith(".txt") and "embedding" in file:
                    txt_file = os.path.join(root, file)
                    break

        if txt_file:
            # 加载词向量
            word_vectors = KeyedVectors.load_word2vec_format(txt_file, binary=False)

            # 保存为二进制格式以加快加载速度
            word_vectors.save_word2vec_format(WORD2VEC_MODEL_PATH, binary=True)

            print(f"转换完成！模型已保存到 {WORD2VEC_MODEL_PATH}")
            os.remove(tar_path)  # 删除原始tar文件
            os.remove(txt_file)  # 删除txt文件
            return True
        else:
            print("无法找到词向量文件，请手动下载中文词向量模型")
            return False

    except Exception as e:
        import traceback
        print(f"下载或处理中文词向量模型时出错: {e}")
        print(traceback.format_exc())
        print("请手动下载中文词向量模型")
        return False


def get_smaller_word2vec_model():
    """
    获取一个体积更小的预训练词向量模型
    适合在难以安装gensim的环境使用
    
    Returns:
        str: 下载链接或使用说明
    """
    instructions = """
    由于安装问题，提供以下两种方案：
    
    方案1: 使用预编译的wheel包（适用于Windows）
    命令: pip install --only-binary=:all: gensim numpy
    
    方案2: 使用较小的词向量模型（约50MB）
    1. 从 https://github.com/Embedding/Chinese-Word-Vectors/blob/master/README.md 下载小型中文词向量
    2. 解压后将txt文件放到 ./models/ 目录下
    3. 运行以下代码转换模型:
       
       from gensim.models import KeyedVectors
       import os
       
       # 将txt文件转为二进制
       txt_file = "models/your_vectors.txt"  # 修改为你下载的文件名
       bin_file = "models/chinese_word2vec.bin"
       
       # 创建目录
       os.makedirs("./models", exist_ok=True)
       
       # 转换
       model = KeyedVectors.load_word2vec_format(txt_file, binary=False)
       model.save_word2vec_format(bin_file, binary=True)
       print("转换完成!")
    """
    print(instructions)
    return instructions


if __name__ == "__main__":
    # python -m utils.nlp_utils
    print("中文NLP工具模块 - 用于股票概念语义分析")
    print("=" * 60)

    if FORCE_CHAR_SIMILARITY:
        print("⚠️ 当前处于字符相似度模式，不使用gensim")
        print("若要启用gensim，请编辑utils/nlp_utils.py，设置FORCE_CHAR_SIMILARITY = False")

    print("1. 下载并安装中文词向量模型")
    print("2. 测试NLP环境")
    print("3. 测试简单字符相似度")
    print("4. 获取小型模型的下载说明")
    print("5. 切换分析模式")
    print("6. 退出")

    try:
        choice = input("请选择操作 [1-6]: ")

        if choice == '1':
            if FORCE_CHAR_SIMILARITY:
                print("当前处于字符相似度模式，无需下载词向量模型")
                print("如需使用词向量，请先修改代码设置FORCE_CHAR_SIMILARITY = False")
            else:
                download_word2vec_model()
            print("\n使用说明:")
            print("1. 在您的代码中导入: from utils.nlp_utils import check_nlp_ready, calc_similarity")
            print("2. 准备NLP环境: use_semantic, word_vectors, _ = check_nlp_ready()")
            print("3. 计算相似度: score = calc_similarity('概念1', '概念2', word_vectors)")

        elif choice == '2':
            ready, model, message = check_nlp_ready()
            print(f"NLP环境状态: {'就绪' if ready else '未准备好'}")
            print(f"详细信息: {message}")

            if ready:
                while True:
                    text1 = input("请输入第一个概念(或q退出): ")
                    if text1.lower() == 'q':
                        break

                    text2 = input("请输入第二个概念: ")
                    sim = calc_similarity(text1, text2, model)
                    print(f"'{text1}' 和 '{text2}' 的语义相似度: {sim:.4f}")

        elif choice == '3':
            print("使用字符相似度分析（不需要gensim）")
            while True:
                text1 = input("请输入第一个概念(或q退出): ")
                if text1.lower() == 'q':
                    break

                text2 = input("请输入第二个概念: ")
                sim = char_similarity(text1, text2)
                print(f"'{text1}' 和 '{text2}' 的字符相似度: {sim:.4f}")

        elif choice == '4':
            get_smaller_word2vec_model()

        elif choice == '5':
            print("请编辑utils/nlp_utils.py文件，")
            print("将FORCE_CHAR_SIMILARITY的值改为True或False")
            print("- True: 强制使用字符相似度模式(适用于无法安装gensim的环境)")
            print("- False: 尝试使用gensim进行语义分析(需要兼容版本的gensim)")

    except Exception as e:
        print(f"执行出错: {e}")
        print("如果您遇到安装问题，可以继续使用字符相似度功能")
