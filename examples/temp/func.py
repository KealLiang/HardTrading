# !/usr/bin/env python
"""
Date: 2025/3/10 18:00
Desc: 通用帮助函数
"""

import hashlib
import math
import os
import pickle
import tempfile
from typing import List, Dict

import pandas as pd
import requests

from akshare.utils.tqdm import get_tqdm


def fetch_paginated_data(url: str, base_params: Dict, timeout: int = 30, cache_pages: int = 5):
    """
    东方财富-分页获取数据并合并结果（支持断点续传）
    :param url: 接口URL
    :type url: str
    :param base_params: 基础请求参数
    :type base_params: dict
    :param timeout: 请求超时时间
    :type timeout: int
    :param cache_pages: 每N页保存一次缓存，0表示不启用缓存
    :type cache_pages: int
    :return: 合并后的数据
    :rtype: pandas.DataFrame
    """
    # 禁用代理，避免VPN干扰
    proxies = {"http": None, "https": None}
    headers = {
        # 粘贴自己的headers
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
    }
    
    # 生成缓存文件路径（使用系统临时目录）
    cache_file = None
    if cache_pages > 0:
        cache_key = f"{url}_{str(sorted(base_params.items()))}"
        cache_hash = hashlib.md5(cache_key.encode()).hexdigest()[:16]
        cache_file = os.path.join(tempfile.gettempdir(), f"em_cache_{cache_hash}.pkl")
    
    # 尝试加载缓存
    temp_list, start_page, total_page = [], 1, None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
                temp_list, start_page, total_page = cache_data['data'], cache_data['page'] + 1, cache_data['total']
                print(f"📦 从第{start_page}页继续（共{total_page}页）")
        except:
            temp_list, start_page, total_page = [], 1, None
    
    # 获取第一页（如果需要）
    params = base_params.copy()
    if start_page == 1:
        params["pn"] = 1
        r = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=timeout)
        data_json = r.json()
        per_page_num = len(data_json["data"]["diff"])
        total_page = math.ceil(data_json["data"]["total"] / per_page_num)
        temp_list.append(pd.DataFrame(data_json["data"]["diff"]))
        print(f"📊 共{total_page}页，每页{per_page_num}条")
        start_page = 2
        if cache_file:
            with open(cache_file, 'wb') as f:
                pickle.dump({'data': temp_list, 'page': 1, 'total': total_page}, f)
    
    # 获取剩余页面
    tqdm = get_tqdm()
    try:
        for page in tqdm(range(start_page, total_page + 1), leave=False, initial=start_page-1, total=total_page):
            params = base_params.copy()
            params["pn"] = page
            r = requests.get(url, params=params, headers=headers, proxies=proxies, timeout=timeout)
            data_json = r.json()
            temp_list.append(pd.DataFrame(data_json["data"]["diff"]))
            
            # 定期保存缓存
            if cache_file and page % cache_pages == 0:
                with open(cache_file, 'wb') as f:
                    pickle.dump({'data': temp_list, 'page': page, 'total': total_page}, f)
                print(f"💾 已缓存至第{page}页")
        
        # 成功完成，删除缓存
        if cache_file and os.path.exists(cache_file):
            os.remove(cache_file)
            print(f"✅ 完成，已清理缓存")
    except Exception as e:
        # 失败时保存缓存
        if cache_file and temp_list:
            with open(cache_file, 'wb') as f:
                pickle.dump({'data': temp_list, 'page': len(temp_list), 'total': total_page}, f)
            print(f"❌ 中断于第{len(temp_list)}页，缓存已保存")
        raise e
    
    # 合并数据
    temp_df = pd.concat(temp_list, ignore_index=True)
    temp_df["f3"] = pd.to_numeric(temp_df["f3"], errors="coerce")
    temp_df.sort_values(by=["f3"], ascending=False, inplace=True, ignore_index=True)
    temp_df.reset_index(inplace=True)
    temp_df["index"] = temp_df["index"].astype(int) + 1
    return temp_df


def set_df_columns(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    """
    设置 pandas.DataFrame 为空的情况
    :param df: 需要设置命名的数据框
    :type df: pandas.DataFrame
    :param cols: 字段的列表
    :type cols: list
    :return: 重新设置后的数据
    :rtype: pandas.DataFrame
    """
    if df.shape == (0, 0):
        return pd.DataFrame(data=[], columns=cols)
    else:
        df.columns = cols
        return df
