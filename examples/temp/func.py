# !/usr/bin/env python
"""
Date: 2025/3/10 18:00
Desc: 通用帮助函数

【修改源码】留存说明（相对 func.origin.py / 官方 akshare）：
- 用途：对抗东财分页接口限流/断连；升级 akshare 后请按本文件重新打补丁到
  site-packages/akshare/utils/func.py
- 对照基线：examples/temp/func.origin.py
- 当前生效路径：conda env trading 的 site-packages/akshare/utils/func.py
"""

# 【修改源码】新增 import：断点续传缓存需要 hashlib/os/pickle/tempfile
import hashlib
import math
import os
import pickle
import tempfile
from typing import List, Dict

import pandas as pd
import requests

from akshare.utils.tqdm import get_tqdm


# 【修改源码】签名扩展：
# - timeout 默认 15 -> 30：分页请求更稳
# - cache_pages：每 N 页落盘断点缓存，失败可续传
# - max_retries / retry_sleep：单页遇到 503/空响应时退避重试（2026-08 新增）
def fetch_paginated_data(url: str, base_params: Dict, timeout: int = 30, cache_pages: int = 5,
                         max_retries: int = 5, retry_sleep: float = 0.8):
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
    :param max_retries: 单页请求失败时的最大重试次数（应对 push2delay 偶发 503）
    :type max_retries: int
    :param retry_sleep: 重试基础等待秒数，实际等待 = retry_sleep * attempt
    :type retry_sleep: float
    :return: 合并后的数据
    :rtype: pandas.DataFrame
    """
    import time

    # 【修改源码】禁用系统/环境代理，避免 VPN 把东财请求导向异常出口
    # 注意：当前请求未显式传 proxies=（注释掉的写法是历史方案）；若升级后需强制禁用代理，
    # 可恢复 proxies 并在 requests.get(..., proxies=proxies) 中传入。
    # proxies = {"http": None, "https": None}

    # 【修改源码】补齐浏览器级 headers（含 Cookie/Referer/UA），降低东财反爬拦截概率
    # Cookie 会过期，若再次大面积失败，请从浏览器 DevTools 复制最新 Cookie 替换
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6',
        'Connection': 'keep-alive',
        'Cookie': 'qgqp_b_id=f5255962e432b7a08bfa2b8125f3eed2; st_nvi=fFeboQ8UuNn3GvFw7mPYHf7a2; nid18=07c25f4e85e4277b7a7577d257520a80; nid18_create_time=1764328644966; gviem=X32Wb0nlo0pCX_abRgH1Q4c4e; gviem_create_time=1764328644966; fullscreengg=1; fullscreengg2=1; st_si=22912003234146; st_asi=delete; st_pvi=61272509655859; st_sp=2025-03-03%2020%3A59%3A29; st_inirUrl=https%3A%2F%2Fquote.eastmoney.com%2Fconcept%2Fsh600056.html; st_sn=3; st_psi=20251202191621488-113200301321-3483112992',
        'Referer': 'https://quote.eastmoney.com/center/gridlist.html',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
    }

    # 【修改源码】单页请求封装：先校验 HTTP/正文再 json()，失败则退避重试
    # 背景：push2delay 偶发返回 503 纯文本（upstream connect error），直接 r.json()
    # 会抛 Expecting value: line 1 column 1 (char 0)，导致整次全市场拉取中断。
    def _request_json(params: Dict) -> Dict:
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=timeout)
                if r.status_code != 200 or not (r.text or "").lstrip().startswith(("{", "[")):
                    raise ValueError(
                        f"bad response status={r.status_code} preview={repr((r.text or '')[:120])}"
                    )
                data_json = r.json()
                if not data_json.get("data") or data_json["data"].get("diff") is None:
                    raise ValueError(f"empty data payload: {data_json}")
                return data_json
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(retry_sleep * attempt)
        raise RuntimeError(f"request failed after {max_retries} retries: {last_err}") from last_err

    # 【修改源码】断点续传：按 url+params 生成临时目录下的 em_cache_*.pkl
    cache_file = None
    if cache_pages > 0:
        cache_key = f"{url}_{str(sorted(base_params.items()))}"
        cache_hash = hashlib.md5(cache_key.encode()).hexdigest()[:16]
        cache_file = os.path.join(tempfile.gettempdir(), f"em_cache_{cache_hash}.pkl")

    # 【修改源码】若存在缓存则从下一页继续，避免失败后从头拉
    temp_list, start_page, total_page = [], 1, None
    if cache_file and os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
                temp_list, start_page, total_page = cache_data['data'], cache_data['page'] + 1, cache_data['total']
                # 【修改源码】不用 emoji 日志，避免 Windows GBK 控制台 UnicodeEncodeError
                print(f"[cache] resume from page {start_page}/{total_page}")
        except Exception:
            temp_list, start_page, total_page = [], 1, None

    # 获取第一页（如果需要）
    params = base_params.copy()
    if start_page == 1:
        params["pn"] = 1
        # 【修改源码】走 _request_json，不再裸调 r.json()
        data_json = _request_json(params)
        per_page_num = len(data_json["data"]["diff"])
        total_page = math.ceil(data_json["data"]["total"] / per_page_num)
        temp_list.append(pd.DataFrame(data_json["data"]["diff"]))
        print(f"[fetch] total_pages={total_page}, per_page={per_page_num}")
        start_page = 2
        if cache_file:
            with open(cache_file, 'wb') as f:
                pickle.dump({'data': temp_list, 'page': 1, 'total': total_page}, f)

    # 获取剩余页面
    tqdm = get_tqdm()
    try:
        # 【修改源码】支持从 start_page 续跑，并给 tqdm 正确的 initial/total
        for page in tqdm(range(start_page, total_page + 1), leave=False, initial=start_page - 1, total=total_page):
            params = base_params.copy()
            params["pn"] = page
            # 【修改源码】走 _request_json（含重试）
            data_json = _request_json(params)
            temp_list.append(pd.DataFrame(data_json["data"]["diff"]))

            # 【修改源码】定期保存断点缓存
            if cache_file and page % cache_pages == 0:
                with open(cache_file, 'wb') as f:
                    pickle.dump({'data': temp_list, 'page': page, 'total': total_page}, f)
                print(f"[cache] saved at page {page}")

        # 【修改源码】成功完成后删除缓存，避免下次误续传旧数据
        if cache_file and os.path.exists(cache_file):
            os.remove(cache_file)
            print("[cache] done, cache cleared")
    except Exception as e:
        # 【修改源码】失败时保存缓存，便于下次从中断页继续
        if cache_file and temp_list:
            with open(cache_file, 'wb') as f:
                pickle.dump({'data': temp_list, 'page': len(temp_list), 'total': total_page}, f)
            print(f"[cache] interrupted at page {len(temp_list)}, cache saved")
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
