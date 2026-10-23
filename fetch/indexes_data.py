import os

import akshare as ak
import pandas as pd


def fetch_and_save_index_data(symbol, save_path):
    """
    获取指定指数的历史行情数据并保存为CSV文件。
    如果文件已存在，则从最新的日期处追加更新，不存储表头。

    :param symbol: 指数代码，如 'sh000001' 表示上证指数
    :param save_path: 保存CSV文件的路径
    """
    # 确保保存路径存在
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # 检查文件是否存在
    if os.path.exists(save_path):
        # 如果文件存在，读取现有数据
        existing_data = pd.read_csv(save_path, header=None, names=['date', 'open', 'high', 'low', 'close', 'volume'])
        last_date = existing_data['date'].max()
        # 获取全部数据
        all_data = ak.stock_zh_index_daily(symbol=symbol)
        # 筛选出新的数据
        new_data = all_data[all_data['date'] > pd.to_datetime(last_date).date()]
        # 如果有新数据，则追加
        if not new_data.empty:
            updated_data = pd.concat([existing_data, new_data], ignore_index=True)
            # 保存更新后的数据，不包含表头
            updated_data.to_csv(save_path, index=False, header=False)
            print(f"Data for {symbol} updated to {save_path}")
        else:
            print(f"No new data for {symbol}.")
    else:
        # 如果文件不存在，获取全部数据
        index_data = ak.stock_zh_index_daily(symbol=symbol)
        # 保存数据到CSV文件，不包含表头
        index_data.to_csv(save_path, index=False, header=False)
        print(f"Data for {symbol} saved to {save_path}")


def fetch_and_save_index_amount(symbol, save_path):
    """
    获取指定指数的日成交额并保存为CSV文件（含表头：date,amount，单位：元）。
    如果文件已存在，则从最新的日期处增量追加。
    使用东方财富接口（自带成交额字段）。

    :param symbol: 指数代码，如 'sh000001' 表示上证指数
    :param save_path: 保存CSV文件的路径
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    all_data = ak.stock_zh_index_daily_em(symbol=symbol)
    if 'amount' not in all_data.columns:
        print(f"Amount field missing for {symbol}, skipped.")
        return
    amt = all_data[['date', 'amount']].copy()
    amt['date'] = amt['date'].astype(str)

    if os.path.exists(save_path):
        existing = pd.read_csv(save_path, dtype={'date': str})
        last_date = existing['date'].max()
        new_data = amt[amt['date'] > last_date]
        if not new_data.empty:
            pd.concat([existing, new_data], ignore_index=True).to_csv(save_path, index=False)
            print(f"Amount for {symbol} updated to {save_path}")
        else:
            print(f"No new amount for {symbol}.")
    else:
        amt.to_csv(save_path, index=False)
        print(f"Amount for {symbol} saved to {save_path}")


# 需要成交额的指数（用于市场强弱分布图右轴）
AMOUNT_INDICES = ("sh000001", "sz399001")


def fetch_indexes_data(save_dir):
    """
    主函数，用于获取上证、深证和创业板指数数据并保存。

    :param save_dir: 保存CSV文件的目录
    """
    # 指定各个指数的代码和保存路径
    indices = {
        "sh000001": os.path.join(save_dir, "sh000001_上证指数.csv"),
        "sz399001": os.path.join(save_dir, "sz399001_深证成指.csv"),
        "sz399006": os.path.join(save_dir, "sz399006_创业板指.csv"),
        "sh000688": os.path.join(save_dir, "sh000688_科创50.csv"),
        "bj899050": os.path.join(save_dir, "bj899050_北证50.csv"),
        "sh000905": os.path.join(save_dir, "sh000905_中证500.csv"),
        "sz399405": os.path.join(save_dir, "sz399405_大盘高贝.csv"),
        "sz399409": os.path.join(save_dir, "sz399409_小盘高贝.csv"),
        "sh000065": os.path.join(save_dir, "sh000065_上证龙头.csv"),
        "sz399653": os.path.join(save_dir, "sz399653_深证龙头.csv"),
    }

    # 获取并保存每个指数的数据
    for symbol, path in indices.items():
        fetch_and_save_index_data(symbol, path)

    # 成交额数据（含表头，独立文件，不影响原有6列CSV）
    for symbol in AMOUNT_INDICES:
        path = os.path.join(save_dir, f"{symbol}_amount.csv")
        try:
            fetch_and_save_index_amount(symbol, path)
        except Exception as e:
            print(f"获取 {symbol} 成交额失败: {e}")


if __name__ == "__main__":
    # 指定保存目录
    save_directory = "path/to/your/directory"
    fetch_indexes_data(save_directory)
