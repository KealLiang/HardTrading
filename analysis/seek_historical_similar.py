import logging
import os
from datetime import datetime

import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
from dtaidistance import dtw
from matplotlib import font_manager
from tqdm import tqdm

from utils.file_util import read_stock_data
from utils.stock_util import get_stock_market

font_path = 'fonts/微软雅黑.ttf'
font_prop = font_manager.FontProperties(fname=font_path)


def build_file_mapping(data_dir):
    """
    预先构建股票代码到文件路径的映射表
    
    这个函数只在程序启动时调用一次，避免每次读取都扫描整个目录
    性能优化：从O(N*M)降低到O(M)，其中N是股票数量，M是文件数量
    
    参数:
    data_dir: str - 数据文件目录
    
    返回:
    dict - {股票代码: 完整文件路径}
    """
    file_mapping = {}
    
    try:
        files = os.listdir(data_dir)
        for file in files:
            if file.endswith('.csv'):
                # 提取股票代码（文件名格式：代码_名称.csv）
                stock_code = file.split('_')[0]
                file_mapping[stock_code] = os.path.join(data_dir, file)
        
        logging.info(f"文件映射表构建完成：共 {len(file_mapping)} 只股票")
    except Exception as e:
        logging.error(f"构建文件映射表失败: {e}")
    
    return file_mapping

# 定义列名对应的英文名称
col_mapping = {
    '日期': 'date',
    '开盘': 'open',
    '最高': 'high',
    '最低': 'low',
    '收盘': 'close',
    '成交量': 'volume'
}


def load_stock_data(file_path):
    """
    加载单只股票数据
    """
    try:
        data = pd.read_csv(file_path, header=None, names=[
            '日期', '股票代码', '开盘', '收盘', '最高', '最低', '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率'
        ])
        data['日期'] = pd.to_datetime(data['日期'])
        return data
    except Exception as e:
        logging.error(f"加载文件 {file_path} 时出错: {e}")
        return None


def load_stock_data_fast(stock_code, file_mapping):
    """
    使用预构建的文件映射表快速加载股票数据
    
    性能优化版本：避免重复扫描目录
    
    参数:
    stock_code: str - 股票代码
    file_mapping: dict - 预构建的文件映射表
    
    返回:
    DataFrame - 股票数据，加载失败返回None
    """
    file_path = file_mapping.get(stock_code)
    if not file_path:
        logging.debug(f"文件映射表中未找到股票 {stock_code}")
        return None
    
    return load_stock_data(file_path)


def load_index_data(file_path):
    """
    加载指数数据
    """
    try:
        data = pd.read_csv(file_path, header=None, names=[
            '日期', '开盘', '最高', '最低', '收盘', '成交量'
        ])
        data['日期'] = pd.to_datetime(data['日期'])
        return data
    except Exception as e:
        logging.error(f"加载文件 {file_path} 时出错: {e}")
        return None


def compute_correlation(target_data, stock_data):
    """
    计算目标股票与候选股票的收盘价相关系数

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_data: DataFrame - 候选股票的数据

    返回:
    float - 相关系数
    """
    return np.corrcoef(target_data['收盘'].values, stock_data['收盘'].values)[0, 1]


def compute_weighted_correlation(target_data, stock_data):
    """
    计算目标股票与候选股票的加权相关系数（开盘价与收盘价，权重1:3）

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_data: DataFrame - 候选股票的数据

    返回:
    float - 加权相关系数
    """
    weights = {
        'open': 0.2,
        'close': 0.3,
        'high': 0.1,
        'low': 0.1,
        'vol': 0.3
    }

    open_corr = np.corrcoef(target_data['开盘'].values, stock_data['开盘'].values)[0, 1]
    close_corr = np.corrcoef(target_data['收盘'].values, stock_data['收盘'].values)[0, 1]
    high_corr = np.corrcoef(target_data['最高'].values, stock_data['最高'].values)[0, 1]
    low_corr = np.corrcoef(target_data['最低'].values, stock_data['最低'].values)[0, 1]
    vol_corr = np.corrcoef(target_data['成交量'].values, stock_data['成交量'].values)[0, 1]

    final_corr = (
            open_corr * weights['open'] +
            close_corr * weights['close'] +
            high_corr * weights['high'] +
            low_corr * weights['low'] +
            vol_corr * weights['vol']
    )
    return round(final_corr, 4)


def compute_enhanced_weighted_correlation(target_data, stock_data):
    """
    增强版加权相关度计算：考虑量价配合、阶段性特征和绝对量级
    
    改进点：
    1. 分段计算相似度（前、中、后三段）
    2. 增加量价配合特征（涨跌幅 vs 成交量变化）
    3. 考虑绝对量级（成交量放大倍数、涨幅绝对值）
    4. 加入动量和趋势一致性
    
    参数:
    target_data: DataFrame - 目标股票的数据
    stock_data: DataFrame - 候选股票的数据
    
    返回:
    float - 增强版相似度得分（0-1之间）
    """
    def extract_features(df):
        """提取增强特征"""
        df = df.copy()
        
        # 基础特征标准化（相对首日）
        base_close = df['收盘'].iloc[0]
        df['norm_close'] = df['收盘'] / base_close
        
        # 涨跌幅
        df['pct_change'] = df['收盘'].pct_change().fillna(0)
        
        # 成交量变化率（相对前一日）
        df['vol_change'] = df['成交量'].pct_change().fillna(0)
        
        # 量价配合度：涨跌幅 * 成交量变化率（同向为正，反向为负）
        df['volume_price_sync'] = df['pct_change'] * df['vol_change']
        
        # 成交量相对平均值的倍数
        df['vol_ratio'] = df['成交量'] / df['成交量'].rolling(window=min(5, len(df)), min_periods=1).mean()
        
        # 累计涨幅
        df['cumulative_return'] = (df['收盘'] / df['收盘'].iloc[0] - 1) * 100
        
        # 振幅
        df['amplitude'] = (df['最高'] - df['最低']) / df['最低'].shift(1).fillna(df['最低'].iloc[0])
        
        return df
    
    def segment_correlation(target_features, stock_features, segment_name):
        """计算单个分段的综合相似度"""
        scores = []
        
        # 1. 价格走势相关性（权重30%）
        price_corr = np.corrcoef(
            target_features['norm_close'].values,
            stock_features['norm_close'].values
        )[0, 1]
        scores.append(('price', price_corr, 0.30))
        
        # 2. 量价配合相关性（权重25%）
        vp_corr = np.corrcoef(
            target_features['volume_price_sync'].values,
            stock_features['volume_price_sync'].values
        )[0, 1]
        scores.append(('vp_sync', vp_corr, 0.25))
        
        # 3. 成交量放大倍数相关性（权重20%）
        vol_ratio_corr = np.corrcoef(
            target_features['vol_ratio'].values,
            stock_features['vol_ratio'].values
        )[0, 1]
        scores.append(('vol_ratio', vol_ratio_corr, 0.20))
        
        # 4. 累计涨幅相似度（权重15%）- 考虑绝对量级
        target_cum_return = target_features['cumulative_return'].iloc[-1]
        stock_cum_return = stock_features['cumulative_return'].iloc[-1]
        # 使用高斯相似度：差异越小越接近1
        return_similarity = np.exp(-((target_cum_return - stock_cum_return) ** 2) / (2 * 50 ** 2))
        scores.append(('cumulative_return', return_similarity, 0.15))
        
        # 5. 振幅相关性（权重10%）
        amp_corr = np.corrcoef(
            target_features['amplitude'].fillna(0).values,
            stock_features['amplitude'].fillna(0).values
        )[0, 1]
        scores.append(('amplitude', amp_corr, 0.10))
        
        # 计算加权得分（处理NaN）
        weighted_score = sum(
            max(0, score if not np.isnan(score) else 0) * weight
            for _, score, weight in scores
        )
        
        return weighted_score, {name: score for name, score, _ in scores}
    
    try:
        # 提取特征
        target_features = extract_features(target_data)
        stock_features = extract_features(stock_data)
        
        # 确保长度一致
        min_len = min(len(target_features), len(stock_features))
        target_features = target_features.iloc[:min_len]
        stock_features = stock_features.iloc[:min_len]
        
        if min_len < 5:
            logging.debug("数据长度不足，跳过计算")
            return 0.0
        
        # 分段计算（前1/3、中1/3、后1/3）
        segment_size = max(3, min_len // 3)
        segments = {
            '前段': (0, segment_size),
            '中段': (segment_size, segment_size * 2),
            '后段': (segment_size * 2, min_len)
        }
        
        segment_scores = {}
        segment_weights = {'前段': 0.35, '中段': 0.30, '后段': 0.35}  # 前后段权重更高
        
        for seg_name, (start, end) in segments.items():
            if end - start < 3:  # 分段太小则跳过
                continue
            seg_score, seg_details = segment_correlation(
                target_features.iloc[start:end],
                stock_features.iloc[start:end],
                seg_name
            )
            segment_scores[seg_name] = (seg_score, seg_details)
        
        # 计算最终加权得分
        final_score = sum(
            score * segment_weights.get(seg_name, 0)
            for seg_name, (score, _) in segment_scores.items()
        )
        
        # 归一化到0-1区间
        final_score = max(0, min(1, final_score))
        
        return round(final_score, 4)
        
    except Exception as e:
        logging.error(f"增强相似度计算失败: {str(e)}")
        return 0.0


def compute_shape_dtw(target_data, stock_data):
    """
    增强版形态DTW相似度计算
    """

    def validate_features(features):
        """验证特征矩阵有效性"""
        # 确保是二维数组
        if features.ndim != 2:
            raise ValueError(f"特征矩阵维度错误: {features.shape}")
        # 确保没有非数值类型
        if not np.issubdtype(features.dtype, np.number):
            raise ValueError(f"包含非数值类型: {features.dtype}")
        # 确保没有异常值
        if np.isnan(features).any() or np.isinf(features).any():
            raise ValueError("存在NaN或无穷值")

    def extract_features(df):
        """鲁棒的特征工程"""
        # 强制深拷贝防止污染原始数据
        df = df.copy(deep=True)

        # 关键字段存在性检查
        required_cols = ['收盘', '最高', '最低', '换手率']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"缺失字段: {missing_cols}")

        # 数值清洗 -------------------------------------------------
        # 换手率强制转换
        df['换手率'] = pd.to_numeric(df['换手率'], errors='coerce')

        # 填充所有NaN（先做前向填充，再做0填充）
        df = df.ffill().fillna(0)

        # 特征计算 -------------------------------------------------
        features = pd.DataFrame()

        # 1. 标准化收盘价（相对首日）
        base_close = df['收盘'].iloc[0] or 1e-6  # 处理零值
        features['norm_close'] = df['收盘'] / base_close

        # 2. 振幅计算（百分比变化）
        with np.errstate(divide='ignore', invalid='ignore'):
            low_shift = df['最低'].shift(1).replace(0, 1e-6)
            features['amplitude'] = (df['最高'] - df['最低']) / low_shift
        features['amplitude'] = features['amplitude'].replace([np.inf, -np.inf], 0).fillna(0)

        # 3. 平滑换手率（3日EMA）
        features['turnover'] = df['换手率'].ewm(span=3, adjust=False).mean()

        # 后处理 -------------------------------------------------
        # 强制转换为数值型二维数组
        features = features.astype(np.float64)

        # 最后检查
        validate_features(features.values)
        return features.values

    try:
        # 提取特征（带防御性编程）
        target_features = extract_features(target_data)
        stock_features = extract_features(stock_data)

        # 动态对齐长度（确保完全一致）
        min_len = min(len(target_features), len(stock_features))
        target_features = target_features[:min_len]
        stock_features = stock_features[:min_len]

        # 核心校验
        if min_len < 5:
            logging.debug("数据长度不足，跳过计算")
            return 0.0
        if target_features.shape != stock_features.shape:
            logging.warning(f"形状不匹配: Target{target_features.shape} vs Stock{stock_features.shape}")
            return 0.0

        # 计算每个特征的DTW距离并取平均
        distances = []
        for i in range(target_features.shape[1]):  # 对每个特征列进行DTW计算
            distance = dtw.distance(target_features[:, i], stock_features[:, i])
            distances.append(distance)

        # 取平均距离作为最终相似度
        avg_distance = np.mean(distances)
        return 1 / (1 + avg_distance)

    except ValueError as ve:
        logging.info(f"特征验证失败: {str(ve)}")
        return 0.0
    except Exception as e:
        logging.error(f"DTW致命错误: {str(e)}", exc_info=True)
        return 0.0


def compute_similarity_by_method(target_data, aligned_stock, method):
    """
    根据指定的方法计算相似度。
    :param target_data: 目标数据
    :param aligned_stock: 对齐后的股票数据
    :param method: 计算方法
    :return: 相关性值或 None（如果方法不支持）
    """
    if method == "close_price":
        return compute_correlation(target_data, aligned_stock)
    elif method == "weighted":
        return compute_weighted_correlation(target_data, aligned_stock)
    elif method == "enhanced_weighted":
        return compute_enhanced_weighted_correlation(target_data, aligned_stock)
    elif method == "dtw":
        return compute_shape_dtw(target_data, aligned_stock)
    else:
        logging.error(f"不支持的相似度计算方法: {method}")
        return None


def calculate_similarity(target_data, stock_codes, data_dir, method="close_price", file_mapping=None):
    """
    计算同时段相似股票趋势（性能优化版）

    参数:
    target_data: DataFrame - 目标股票的数据
    stock_codes: list - 候选股票代码列表
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法
    file_mapping: dict - 预构建的文件映射表（可选，强烈推荐）

    返回:
    list - 包含股票代码和相似度的元组列表
    """
    similarity_results = []
    
    for stock_code in tqdm(stock_codes, desc="寻找相似走势"):
        # 使用文件映射表快速读取（如果提供）
        if file_mapping:
            stock_data = load_stock_data_fast(stock_code, file_mapping)
        else:
            stock_data = read_stock_data(stock_code, data_dir)

        if stock_data is None:
            logging.debug(f"未找到股票 {stock_code} 的数据文件，跳过。")
            continue

        # 直接对齐到目标日期范围
        aligned_stock = align_dataframes(target_data, stock_data)
        if aligned_stock is None:
            logging.debug(f"股票 {stock_code} 数据缺口过大，无法对齐，已跳过")
            continue

        # 验证对齐后的数据完整性
        if len(aligned_stock) != len(target_data):
            logging.debug(f"股票 {stock_code} 对齐后数据长度不一致，跳过。")
            continue

        if aligned_stock[['开盘', '收盘', '最高', '最低']].isna().any().any():
            logging.debug(f"股票 {stock_code} 存在无效填充值，跳过。")
            continue

        # 计算相似度
        correlation = compute_similarity_by_method(target_data, aligned_stock, method)
        if correlation is None:
            return []

        similarity_results.append((stock_code, correlation, aligned_stock))

    return similarity_results


def calculate_similarity_v2(data_dir, method, stock_codes, target_data, trend_end_date,
                            window_size, file_mapping=None):
    """
    计算不同时段的相似股票趋势（性能优化版）
    
    性能优化：
    1. 使用预构建的文件映射表，避免重复扫描目录
    2. 去掉了双重os.listdir调用
    """
    similarity_results = []
    for stock_code in tqdm(stock_codes, desc="寻找相似走势v2"):
        try:
            # 优化：使用文件映射表快速加载（避免双重扫描）
            if file_mapping:
                stock_data = load_stock_data_fast(stock_code, file_mapping)
            else:
                stock_data = read_stock_data(stock_code, data_dir)
            
            if stock_data is None:
                logging.debug(f"未找到股票 {stock_code} 的数据文件，跳过。")
                continue

            # 预处理：按日期排序并重置索引
            stock_data = stock_data.sort_values('日期').reset_index(drop=True)

            # 获取候选股票可用的最大日期
            mask = (stock_data['日期'] <= trend_end_date)
            if not mask.any():
                logging.debug(f"股票 {stock_code} 在 {trend_end_date} 前无数据，跳过")
                continue

            # 确定调整后的结束日期
            adjusted_end_date = stock_data[mask]['日期'].max()

            # 找到结束日期的位置
            end_idx = stock_data.index[stock_data['日期'] == adjusted_end_date].tolist()
            if not end_idx:
                continue
            end_idx = end_idx[0]

            # 计算起始位置
            start_idx = end_idx - (window_size - 1)
            if start_idx < 0:
                logging.debug(f"股票 {stock_code} 在 {adjusted_end_date} 前交易日不足，跳过")
                continue

            # 截取时间窗口
            candidate_window = stock_data.iloc[start_idx:end_idx + 1].copy()

            # 验证窗口长度
            if len(candidate_window) != window_size:
                logging.debug(f"股票 {stock_code} 有效窗口长度不足，跳过")
                continue

            # 计算相似度
            correlation = compute_similarity_by_method(target_data, candidate_window, method)
            if correlation is None:
                return []

            similarity_results.append((stock_code, correlation, candidate_window))

        except Exception as e:
            logging.error(f"处理股票 {stock_code} 时发生异常: {str(e)}")
            continue

    return similarity_results


def align_dataframes(target_data, stock_data, max_edge_fill=2):
    """
    对齐日期并智能填充缺失值
    :param max_edge_fill: 允许填充边缘缺失的最大天数
    """
    try:
        # 获取目标日期范围
        target_dates = pd.to_datetime(target_data['日期'].unique())

        # 设置索引并重新采样对齐
        stock_data = stock_data.set_index('日期').sort_index()
        aligned_stock = stock_data.reindex(target_dates)

        # 定义关键数值列
        numeric_cols = ['开盘', '收盘', '最高', '最低', '成交量']
        numeric_cols = [col for col in numeric_cols if col in aligned_stock.columns]

        # 第一阶段：填充内部缺口（时间序列插值）
        aligned_stock[numeric_cols] = aligned_stock[numeric_cols].interpolate(
            method='time',
            limit_area='inside'
        )

        # 第二阶段：有限边缘填充
        aligned_stock[numeric_cols] = aligned_stock[numeric_cols].ffill(
            limit=max_edge_fill  # 前向填充
        ).bfill(
            limit=max_edge_fill  # 后向填充
        )

        # 第三阶段：最终检查
        if aligned_stock[numeric_cols].isna().sum().sum() > 0:
            logging.debug(f"数据缺口超过允许范围")
            return None

        return aligned_stock.reset_index().rename(columns={'index': '日期'})

    except Exception as e:
        logging.debug(f"对齐失败: {str(e)}")
        return None


def plot_kline(dataframes, stock_labels, split_dates=None, output_dir="kline_charts"):
    """
    绘制K线图并保存到本地

    参数:
    dataframes: list - 包含每只股票数据的DataFrame列表
    stock_labels: list - 每只股票的标签列表
    split_dates: list - 用于绘制分隔标记的日期列表（与dataframes长度相同）
    output_dir: str - 图表保存路径
    """
    # 设置中文字体防止乱码
    plt.rcParams['font.family'] = font_prop.get_name()
    plt.rcParams['axes.unicode_minus'] = False

    # 创建保存目录
    os.makedirs(output_dir, exist_ok=True)

    for df, label, split_date in zip(dataframes, stock_labels, split_dates or [None] * len(dataframes)):
        # 转换为适合 mplfinance 的格式
        df_mpf = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']].rename(columns=col_mapping).copy()
        df_mpf.set_index('date', inplace=True)

        # 配置样式
        custom_colors = mpf.make_marketcolors(
            up='red',
            down='green',
            edge='black',
            wick='black',
            volume='orange'
        )
        mpf_style = mpf.make_mpf_style(base_mpf_style="charles",
                                       rc={"font.sans-serif": font_prop.get_name() if font_prop else "SimHei"},
                                       marketcolors=custom_colors)

        # 保存图表
        output_file = os.path.join(output_dir, f"{label}_kline.png")

        # 根据 alines 是否为 None 来决定是否传递该参数
        plot_params = {
            'type': "candle",
            'title': f"{label} K线图",
            'style': mpf_style,
            'volume': True,
            'savefig': dict(fname=output_file, dpi=300, bbox_inches="tight"),
            'datetime_format': '%Y-%m-%d'
        }

        # 添加竖线标记
        if split_date:
            plot_params['alines'] = [(split_date, df_mpf['low'].min()), (split_date, df_mpf['high'].max())]

        mpf.plot(df_mpf, **plot_params)

        logging.info(f"K线图已保存到 {output_file}")


def get_stock_info_dict(data_dir):
    # 获取代码名称字典
    stock_info_dict = {}
    for f in os.listdir(data_dir):
        if f.endswith('.csv'):
            parts = f.split('_')
            stock_code = parts[0]
            stock_name = '_'.join(parts[1:]).split('.')[0]  # 提取名称部分并去掉.csv后缀
            stock_info_dict[stock_code] = stock_name
    return stock_info_dict


def cal_window_size(start_date, end_date):
    excluded_dates = ['2025-02-04']  # 排除不对的日期

    nyse = mcal.get_calendar('SSE')  # A股使用 'SSE' 日历
    schedule = nyse.schedule(start_date=start_date, end_date=end_date)
    schedule = schedule.drop(excluded_dates, errors='ignore')
    target_window_size = len(schedule)
    return target_window_size


def find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes=None, data_dir=".",
                              method="close_price", trend_end_date=None, same_market=False):
    """
    主函数：寻找历史相似走势（性能优化版）

    参数:
    target_stock_code: str - 目标股票代码
    start_date: str或datetime - 起始日期（格式：'YYYYMMDD' 或 datetime对象）
    end_date: str或datetime - 结束日期（格式：'YYYYMMDD' 或 datetime对象）
    stock_codes: list - 候选股票代码列表（可选）
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法（支持："close_price", "weighted", "enhanced_weighted", "dtw"）
    trend_end_date: str或datetime - 趋势结束日期（用于寻找其他时间段，格式：'YYYYMMDD' 或 datetime对象）
    same_market: bool - 是否只查找同一市场的股票
    
    性能优化：
    1. 预先构建文件映射表，避免重复扫描目录（提速50-100倍）
    2. 去掉了预筛选机制（反而增加IO负担）
    3. 优化了V2版本的双重扫描问题
    """
    # 日期参数处理：支持字符串和datetime对象
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y%m%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y%m%d')
    if trend_end_date is not None and isinstance(trend_end_date, str):
        trend_end_date = datetime.strptime(trend_end_date, '%Y%m%d')
    
    # ===== 性能优化：预先构建文件映射表 =====
    logging.info("正在构建文件映射表...")
    file_mapping = build_file_mapping(data_dir)
    
    logging.info("开始加载目标股票数据...")
    target_data = load_stock_data_fast(target_stock_code, file_mapping)
    if target_data is None:
        logging.error(f"未找到目标股票 {target_stock_code} 的数据文件！")
        return

    target_data = target_data[(target_data['日期'] >= start_date) & (target_data['日期'] <= end_date)].copy()
    if target_data.empty:
        logging.error("目标股票在指定区间内无数据！")
        return

    logging.info(f"目标股票 {target_stock_code} 的数据加载完成，开始寻找相似走势...")

    # 计算目标时间段长度（交易日数）
    window_size = cal_window_size(start_date, end_date)

    if stock_codes is None:
        stock_codes = [f.split('_')[0] for f in os.listdir(data_dir) if
                       f.endswith('.csv') and not f.startswith(f"{target_stock_code}_")]

    # 如果需要在同一市场中查找，过滤掉不同市场的股票
    if same_market:
        try:
            target_market = get_stock_market(target_stock_code)
            filtered_stock_codes = []

            for code in stock_codes:
                try:
                    if get_stock_market(code) == target_market:
                        filtered_stock_codes.append(code)
                except ValueError:
                    # 跳过无法识别市场的股票代码
                    logging.warning(f"跳过无法识别市场的股票代码: {code}")
                    continue

            stock_codes = filtered_stock_codes
            logging.info(f"过滤后在{target_market}市场内共有{len(stock_codes)}只候选股票")
        except ValueError as e:
            logging.error(f"确定目标股票市场时出错: {str(e)}")
            # 如果无法确定目标股票的市场，则不进行过滤

    # 分两种模式处理
    if trend_end_date is None:
        # 原逻辑：同时段相似
        similarity_results = calculate_similarity(
            target_data, stock_codes, data_dir, method, file_mapping=file_mapping
        )
    else:
        # 新逻辑：其他时间段相似（优化：传递文件映射表）
        similarity_results = calculate_similarity_v2(
            data_dir, method, stock_codes, target_data, trend_end_date, window_size, file_mapping=file_mapping
        )

    # 按相似度排序
    similarity_results.sort(key=lambda x: x[1], reverse=True)

    logging.info("相似走势计算完成，结果如下：")
    top_similar = similarity_results[:10]
    for stock_code, correlation, _ in top_similar:
        logging.info(f"股票代码: {stock_code}, 相似度: {correlation:.4f}")

    # 绘制并保存K线图
    if top_similar:
        stock_info_dict = get_stock_info_dict(data_dir)
        dataframes = [target_data] + [result[2] for result in top_similar]
        labels = [f"A目标股票_{target_stock_code}"] + [
            f"{stock_info_dict.get(result[0], '未知')}_{result[0]}_{result[1]:.4f}"
            for result in top_similar]
        plot_kline(dataframes, labels, output_dir="./kline_charts/other_similar")


def find_self_similar_windows(target_stock_code, start_date, end_date, data_dir=".", method="close_price",
                              future_days=10):
    """
    找出某只个股与自身不同时期的相似度，并画图包括"未来天数"的K线。

    参数:
    target_stock_code: str - 目标股票代码
    start_date: str或datetime - 起始日期（格式：'YYYYMMDD' 或 datetime对象）
    end_date: str或datetime - 结束日期（格式：'YYYYMMDD' 或 datetime对象）
    data_dir: str - 数据文件路径
    method: str - 使用的相似度计算方法（"close_price" 或 "weighted"）
    future_days: int - 未来天数，用于绘制相似区间后的预测数据
    """
    # 日期参数处理：支持字符串和datetime对象
    if isinstance(start_date, str):
        start_date = datetime.strptime(start_date, '%Y%m%d')
    if isinstance(end_date, str):
        end_date = datetime.strptime(end_date, '%Y%m%d')
    
    # 加载目标股票数据
    target_file = next(
        (os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith(f"{target_stock_code}_")), None)
    if not target_file:
        logging.error(f"未找到目标股票 {target_stock_code} 的数据文件！")
        return

    # 加载个股或指数
    if target_stock_code[0].isdigit():
        stock_data = load_stock_data(target_file)
    else:
        stock_data = load_index_data(target_file)

    # 确定目标时间段
    target_data = stock_data[(stock_data['日期'] >= start_date) & (stock_data['日期'] <= end_date)]
    if target_data.empty:
        logging.error("目标股票在指定区间内无数据！")
        return

    # 确定交易日窗口大小
    target_window_size = cal_window_size(start_date, end_date)

    if target_window_size < 5:  # 防止窗口过小
        logging.error("指定时间范围内交易日不足以计算窗口！")
        return

    # 滑动窗口寻找相似时段
    similarity_results = []
    for i in range(len(stock_data) - target_window_size + 1):
        window_start = stock_data.iloc[i]['日期']
        window_end = stock_data.iloc[i + target_window_size - 1]['日期']

        # 跳过目标区间本身
        if window_start >= start_date and window_end <= end_date:
            continue

        window_data = stock_data.iloc[i:i + target_window_size]

        # 计算相似度
        correlation = compute_similarity_by_method(target_data, window_data, method)
        if correlation is None:
            return []

        # 提取未来天数数据
        future_data = stock_data.iloc[i + target_window_size:i + target_window_size + future_days]
        merged_data = pd.concat([window_data, future_data], ignore_index=True)
        similarity_results.append((window_start, window_end, correlation, merged_data))

    # 按相似度排序并获取前5个窗口
    similarity_results.sort(key=lambda x: x[2], reverse=True)
    top_windows = similarity_results[:5]

    logging.info("最相似的时间窗口:")
    for start, end, corr, _ in top_windows:
        logging.info(f"时间段: {start.date()} 至 {end.date()}, 相似度: {corr:.4f}")

    # 绘制并保存K线图
    dataframes = [target_data] + [result[3] for result in top_windows]
    labels = [f"目标区间_{start_date.date()}_{end_date.date()}"] + \
             [f"相似区间_{start.date()}_{end.date()}_{corr:.4f}" for start, end, corr, _ in top_windows]
    split_dates = [None] + [end for _, end, _, _ in top_windows]  # 分隔标记日期，目标区间无标记

    plot_kline(dataframes, labels, split_dates=split_dates, output_dir="./kline_charts/self_similar")


# 示例调用
if __name__ == "__main__":
    target_stock_code = "000001"  # 目标股票代码
    start_date = "20241101"  # 直接使用字符串格式 YYYYMMDD
    end_date = "20241212"

    # 可选股票代码列表
    stock_codes = [
        "600928",
        "601319",
        "001227"
    ]
    # stock_codes = None

    data_dir = "./data/astocks"  # 数据文件所在目录

    # 1.寻找自身相似时期
    find_self_similar_windows(target_stock_code, start_date, end_date, data_dir, method="weighted")

    # 2.寻找同时期相似个股（不限制市场）
    # find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes, data_dir, method="weighted")

    # 3.寻找同市场内的相似个股
    # find_other_similar_trends(target_stock_code, start_date, end_date, stock_codes, data_dir, 
    #                          method="weighted", same_market=True)
