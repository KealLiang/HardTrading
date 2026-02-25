"""
股票 ↔ 概念板块 双向映射表

功能：
  - 通过东方财富（EM）接口全量构建"股票→概念"和"概念→股票"双向映射
  - 支持断点续传：遇到限流立即停止并保存进度，下次从中断处继续
  - 概念板块名称列表缓存到文件，避免多次重复拉取
  - 提供按股票代码查询所属概念，以及按概念查询成分股的接口

缓存文件：
  data/concepts_data/stock_concept_map.json       （最终成果）
  data/concepts_data/stock_concept_map.tmp.json   （构建中途的进度，完成后删除）
  data/concepts_data/concept_name_list.json       （概念名称列表缓存）

典型用法：
  from fetch.stock_concept_map import update_concept_map, get_stock_concepts

  update_concept_map()                     # 全量更新（首次约 15~30 分钟，支持多次断点续传）
  concepts = get_stock_concepts("000001")  # 查询平安银行所属概念
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

import requests as _requests
import akshare as ak

logger = logging.getLogger(__name__)

# ── 路径常量 ─────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "concepts_data")
_MAP_FILE  = os.path.join(_DATA_DIR, "stock_concept_map.json")
_TMP_FILE  = os.path.join(_DATA_DIR, "stock_concept_map.tmp.json")
_LIST_FILE = os.path.join(_DATA_DIR, "concept_name_list.json")   # 概念名称列表缓存

# ── 请求参数 ─────────────────────────────────────────────
_SLEEP_BETWEEN = 1.2   # 每次成功请求后等待秒数，缓解 EM 限流


# ─────────────────────────────────────────────────────────
# 内部工具
# ─────────────────────────────────────────────────────────

def _ensure_dir():
    os.makedirs(_DATA_DIR, exist_ok=True)


def _load_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取 {path} 失败: {e}")
        return None


def _save_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# VPN 开启时，Clash 等代理对 79.push2.eastmoney.com 等数字前缀子域名处理异常，
# 会触发 ProxyError。此处 patch requests.get，让 EM 域名始终走直连，绕过代理。
_orig_requests_get = _requests.get

def _em_direct_get(url, **kwargs):
    if "eastmoney.com" in url:
        kwargs["proxies"] = {"http": None, "https": None}
    return _orig_requests_get(url, **kwargs)

_requests.get = _em_direct_get


# ─────────────────────────────────────────────────────────
# 核心：构建/更新映射表
# ─────────────────────────────────────────────────────────

def _get_all_concepts(force_refresh: bool = False) -> list[str]:
    """
    获取全部概念板块名称列表。
    优先读取本地缓存（concept_name_list.json），缓存不存在时才调用 EM 接口并保存。

    Args:
        force_refresh: True 时忽略缓存，强制重新从 EM 拉取
    """
    if not force_refresh:
        cached = _load_json(_LIST_FILE)
        if cached:
            concepts = cached.get("concepts", [])
            logger.info(f"从缓存读取概念列表：{len(concepts)} 个（{cached.get('fetched_at', '')}）")
            return concepts

    logger.info("正在从 EM 获取概念板块列表...")
    concept_df = ak.stock_board_concept_name_em()
    concepts = concept_df["板块名称"].tolist()
    _save_json(_LIST_FILE, {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "concepts": concepts,
    })
    logger.info(f"概念列表已缓存：{len(concepts)} 个")
    return concepts


def update_concept_map(force: bool = False) -> dict:
    """
    全量构建（或续传）股票 ↔ 概念双向映射表，并保存到本地缓存。

    流程：
      1. 读取概念板块名称列表（优先本地缓存，避免重复调用 EM）
      2. 恢复上次中断的临时进度（若有）
      3. 逐一获取每个概念的成分股；一旦失败立即停止并保存当前进度
      4. 全部完成后写入最终文件，删除临时进度文件

    Args:
        force: True = 忽略所有缓存，强制从零重建（同时刷新概念名称列表）；
               False = 若最终文件存在且是今天的则跳过（幂等），否则从上次断点继续

    Returns:
        包含映射数据的 dict（完成时），或已积累的部分数据（被限流中断时）
    """
    _ensure_dir()

    # 幂等检查：今天已全量完成则直接返回
    if not force:
        existing = _load_json(_MAP_FILE)
        if existing:
            updated_at = existing.get("_meta", {}).get("updated_at", "")
            if updated_at.startswith(datetime.now().strftime("%Y-%m-%d")):
                logger.info(f"概念映射表今日已完成（{updated_at}），跳过。如需强制重建请传 force=True")
                return existing

    # ── Step 1：获取概念名称列表（本地缓存优先）────────────
    all_concepts = _get_all_concepts(force_refresh=force)
    total = len(all_concepts)

    # ── Step 2：恢复中断进度 ──────────────────────────────
    tmp = _load_json(_TMP_FILE)
    if tmp and not force:
        stock_to_concepts: dict = tmp.get("stock_to_concepts", {})
        concept_to_stocks: dict = tmp.get("concept_to_stocks", {})
        done_concepts: set = set(tmp.get("done_concepts", []))
        logger.info(f"发现中断进度：已完成 {len(done_concepts)}/{total} 个概念，从断点继续...")
    else:
        stock_to_concepts = {}
        concept_to_stocks = {}
        done_concepts = set()

    logger.info(f"开始拉取成分股，剩余 {total - len(done_concepts)} 个概念...")

    # ── Step 3：逐概念拉成分股，失败立即停止 ─────────────
    for idx, concept in enumerate(all_concepts, 1):
        if concept in done_concepts:
            continue

        try:
            cons_df = ak.stock_board_concept_cons_em(symbol=concept)
            code_col = "代码" if "代码" in cons_df.columns else cons_df.columns[0]
            codes = cons_df[code_col].astype(str).str.zfill(6).tolist()

            concept_to_stocks[concept] = codes
            for code in codes:
                stock_to_concepts.setdefault(code, [])
                if concept not in stock_to_concepts[code]:
                    stock_to_concepts[code].append(concept)

            done_concepts.add(concept)
            logger.info(f"[{idx}/{total}] {concept}: {len(codes)} 只")

        except Exception as e:
            # 失败 = 被限流，立即保存进度并终止，等下次继续
            logger.warning(
                f"[{idx}/{total}] {concept} 拉取失败（{type(e).__name__}），"
                f"判断为限流，终止本次运行并保存进度"
            )
            _save_json(_TMP_FILE, {
                "stock_to_concepts": stock_to_concepts,
                "concept_to_stocks": concept_to_stocks,
                "done_concepts": list(done_concepts),
            })
            logger.info(f"进度已保存，下次运行将从第 {idx} 个概念『{concept}』继续")
            return {
                "_meta": {
                    "status": "incomplete",
                    "stopped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "done": len(done_concepts),
                    "total": total,
                },
                "stock_to_concepts": stock_to_concepts,
                "concept_to_stocks": concept_to_stocks,
            }

        time.sleep(_SLEEP_BETWEEN)

    # ── Step 4：全部完成，写入最终文件 ───────────────────
    result = {
        "_meta": {
            "status": "complete",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_concepts": len(concept_to_stocks),
            "total_stocks": len(stock_to_concepts),
        },
        "stock_to_concepts": stock_to_concepts,
        "concept_to_stocks": concept_to_stocks,
    }
    _save_json(_MAP_FILE, result)

    if os.path.exists(_TMP_FILE):
        os.remove(_TMP_FILE)

    logger.info(
        f"概念映射表构建完成：{len(concept_to_stocks)} 个概念，{len(stock_to_concepts)} 只股票"
    )
    return result


# ─────────────────────────────────────────────────────────
# 查询接口
# ─────────────────────────────────────────────────────────

def _get_map() -> dict:
    """加载本地缓存，不存在则返回空结构（不自动触发更新）"""
    data = _load_json(_MAP_FILE)
    if data is None:
        logger.warning(f"概念映射表文件不存在，请先执行 update_concept_map()。路径: {_MAP_FILE}")
        return {"stock_to_concepts": {}, "concept_to_stocks": {}, "_meta": {}}
    return data


def get_stock_concepts(stock_code: str) -> list[str]:
    """
    查询某只股票所属的全部概念板块。

    Args:
        stock_code: 6位股票代码，如 "000001"

    Returns:
        概念板块名称列表，如 ['银行', '深圳本地股', 'MSCI概念']；
        若不在任何概念中或映射表未初始化则返回空列表
    """
    code = str(stock_code).zfill(6)
    return _get_map()["stock_to_concepts"].get(code, [])


def get_concept_stocks(concept_name: str) -> list[str]:
    """
    查询某概念板块的全部成分股代码。

    Args:
        concept_name: 概念板块名称，如 "人工智能"

    Returns:
        股票代码列表；若概念不存在或映射表未初始化则返回空列表
    """
    return _get_map()["concept_to_stocks"].get(concept_name, [])


def get_map_meta() -> dict:
    """返回映射表的元信息（更新时间、统计数量等）"""
    return _get_map().get("_meta", {})


def is_map_available() -> bool:
    """判断本地缓存是否存在"""
    return os.path.exists(_MAP_FILE)
