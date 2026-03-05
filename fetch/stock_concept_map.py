"""
股票 ↔ 概念板块 双向映射表

功能：
  - 通过同花顺（THS）接口全量构建"股票→概念"和"概念→股票"双向映射
  - 支持断点续传：遇到异常立即停止并保存进度，下次从中断处继续
  - 概念板块名称及代码列表缓存到文件，避免多次重复拉取
  - 提供按股票代码查询所属概念，以及按概念查询成分股的接口

数据源：
  - 概念列表：同花顺 stock_board_concept_name_ths()，接口稳定
  - 成分股列表：同花顺概念详情页翻页抓取（http://q.10jqka.com.cn/gn/detail/code/{code}/page/{n}/）

缓存文件：
  data/concepts_data/stock_concept_map.json       （最终成果）
  data/concepts_data/stock_concept_map.tmp.json   （构建中途的进度，完成后删除）
  data/concepts_data/concept_name_list.json       （概念名称及代码缓存）

典型用法：
  from fetch.stock_concept_map import update_concept_map, get_stock_concepts

  update_concept_map()                     # 全量更新（首次约 5~15 分钟，支持断点续传）
  concepts = get_stock_concepts("000001")  # 查询平安银行所属概念
"""

import json
import logging
import os
import time
from datetime import datetime
from io import StringIO
from typing import Optional

import pandas as pd
import requests
import akshare as ak

logger = logging.getLogger(__name__)

# ── 路径常量 ─────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "concepts_data")
_MAP_FILE  = os.path.join(_DATA_DIR, "stock_concept_map.json")
_TMP_FILE  = os.path.join(_DATA_DIR, "stock_concept_map.tmp.json")
_LIST_FILE = os.path.join(_DATA_DIR, "concept_name_list.json")   # 概念名称及代码缓存

# ── 请求参数 ─────────────────────────────────────────────
_SLEEP_BETWEEN_PAGES    = 0.4   # 同一概念翻页间隔（秒）
_SLEEP_BETWEEN_CONCEPTS = 1.0   # 每个概念拉取完后的等待（秒）
_THS_DETAIL_BASE_URL    = "http://q.10jqka.com.cn/gn/detail/code/{code}/"
_THS_PAGE_URL           = "http://q.10jqka.com.cn/gn/detail/code/{code}/page/{page}/"


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


def _get_ths_v_code() -> str:
    """获取同花顺接口所需的 v_code 认证 Cookie 值"""
    import py_mini_racer
    from akshare.datasets import get_ths_js
    with open(get_ths_js("ths.js"), encoding="utf-8") as f:
        js_content = f.read()
    js_code = py_mini_racer.MiniRacer()
    js_code.eval(js_content)
    return js_code.call("v")


def _make_ths_headers(v_code: str, referer: str = "") -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Cookie": f"v={v_code}",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if referer:
        headers["Referer"] = referer
    return headers


# ─────────────────────────────────────────────────────────
# THS 成分股抓取
# ─────────────────────────────────────────────────────────

def _get_concept_stocks_ths(concept_code: str, v_code: str) -> list[str]:
    """
    抓取同花顺某概念板块的全部成分股代码。

    通过翻页访问概念详情页（非 AJAX），每页约 10 条，直到末页或异常为止。

    Args:
        concept_code: THS 概念代码，如 "301270"
        v_code: 同花顺认证 Cookie 值

    Returns:
        股票代码列表（6 位字符串）；失败时返回已抓取部分
    """
    detail_url = _THS_DETAIL_BASE_URL.format(code=concept_code)
    headers = _make_ths_headers(v_code, referer="http://q.10jqka.com.cn/gn/")
    all_codes: list[str] = []

    # ── 第 1 页（同时获取总页数）─────────────────────────
    try:
        r = requests.get(detail_url, headers=headers, timeout=15)
        r.raise_for_status()
    except Exception as e:
        logger.warning(f"THS 概念 {concept_code} 第1页请求失败: {e}")
        return all_codes

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(r.text, features="lxml")
    page_info = soup.find("span", {"class": "page_info"})
    total_pages = int(page_info.text.split("/")[1]) if page_info else 1

    codes = _parse_stock_codes(r.text)
    all_codes.extend(codes)

    # ── 第 2 页及以后 ────────────────────────────────────
    for page in range(2, total_pages + 1):
        time.sleep(_SLEEP_BETWEEN_PAGES)
        page_url = _THS_PAGE_URL.format(code=concept_code, page=page)
        try:
            rp = requests.get(page_url, headers=headers, timeout=15)
            rp.raise_for_status()
        except Exception as e:
            logger.warning(f"THS 概念 {concept_code} 第{page}页请求失败: {e}")
            break
        page_codes = _parse_stock_codes(rp.text)
        if not page_codes:
            break
        all_codes.extend(page_codes)

    return all_codes


def _parse_stock_codes(html: str) -> list[str]:
    """从 THS 概念详情页 HTML 中解析股票代码列表。

    不同概念页面的表格结构可能略有差异，有的 tables[0] 不是成分股表，
    这里做一些兼容处理：
      1. 从所有表中优先选择包含“代码”列的表；
      2. 兼容 MultiIndex 表头（只取最后一级列名）；
      3. 首行若包含“暂无成份股数据”等字样则认为无成分股。
    """
    try:
        tables = pd.read_html(StringIO(html))
        if not tables:
            return []

        target_df = None
        for t in tables:
            df = t.copy()
            # 兼容 MultiIndex 列名
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [str(col[-1]) for col in df.columns]
            cols = [str(c) for c in df.columns]
            if any("代码" in c for c in cols):
                target_df = df
                break

        if target_df is None:
            return []

        df = target_df
        if df.empty:
            return []

        # 首行若包含“暂无成份股数据”等字样则认为无数据
        first_row_str = "".join(str(x) for x in df.iloc[0].tolist())
        if "暂无" in first_row_str or "无成份" in first_row_str:
            return []

        # 找到“代码”所在列
        code_col_idx = 1
        for i, c in enumerate(df.columns):
            if "代码" in str(c):
                code_col_idx = i
                break

        series = df.iloc[:, code_col_idx].astype(str)
        # 提取数字部分并补齐 6 位，过滤非纯数字
        codes = (
            series.str.extract(r"(\d+)")[0]
            .dropna()
            .astype(str)
            .str.zfill(6)
            .tolist()
        )
        return [c for c in codes if c.isdigit()]
    except Exception as e:
        logger.debug(f"_parse_stock_codes 解析失败: {e}")
        return []


# ─────────────────────────────────────────────────────────
# 核心：概念名称列表
# ─────────────────────────────────────────────────────────

def _get_all_concepts(force_refresh: bool = False) -> list[dict]:
    """
    获取全部概念板块名称及代码列表。
    优先读取本地缓存（concept_name_list.json），缓存不存在时从 THS 拉取并保存。

    Args:
        force_refresh: True 时忽略缓存，强制从 THS 重新拉取

    Returns:
        包含 {"name": ..., "code": ...} 的字典列表
    """
    if not force_refresh:
        cached = _load_json(_LIST_FILE)
        if cached and cached.get("source") == "ths":
            concepts = cached.get("concepts", [])
            logger.info(f"从缓存读取 THS 概念列表：{len(concepts)} 个（{cached.get('fetched_at', '')}）")
            return concepts

    logger.info("正在从 THS 获取概念板块列表...")
    concept_df = ak.stock_board_concept_name_ths()
    concepts = [
        {"name": row["name"], "code": str(row["code"])}
        for _, row in concept_df.iterrows()
    ]
    _save_json(_LIST_FILE, {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "ths",
        "concepts": concepts,
    })
    logger.info(f"THS 概念列表已缓存：{len(concepts)} 个")
    return concepts


# ─────────────────────────────────────────────────────────
# 核心：构建/更新映射表
# ─────────────────────────────────────────────────────────

def update_concept_map(
    force: bool = False,
    retry_empty_concepts_only: bool = False,
) -> dict:
    """
    全量构建（或续传）股票 ↔ 概念双向映射表，并保存到本地缓存。

    流程：
      1. 读取 THS 概念板块名称及代码列表（优先本地缓存）
      2. 根据模式选择初始数据（全量 / 续传 / 只重试缺失概念）
      3. 生成 THS 认证 v_code
      4. 逐一抓取每个概念的成分股（翻页 HTTP 请求，无需登录）；
         遇到连续失败则暂停并保存进度
      5. 全部完成后写入最终文件，删除临时进度文件

    Args:
        force:
            True  = 忽略所有缓存，强制从零重建；
            False = 若最终文件存在且是今天的则跳过，否则从上次断点继续。
        retry_empty_concepts_only:
            True  = 仅针对当前 stock_concept_map.json 中
                    「成分股列表为空」或「完全缺失」的概念进行重试抓取，
                    其余概念沿用历史结果，避免全量重拉。
            False = 使用原有逻辑（全量/续传）。

    Returns:
        包含映射数据的 dict（完成时），或已积累的部分数据（中断时）
    """
    _ensure_dir()

    # 当仅重试缺失概念时，不做“今日已完成”短路
    if not force and not retry_empty_concepts_only:
        existing = _load_json(_MAP_FILE)
        if existing:
            updated_at = existing.get("_meta", {}).get("updated_at", "")
            if updated_at.startswith(datetime.now().strftime("%Y-%m-%d")):
                logger.info(
                    f"概念映射表今日已完成（{updated_at}），跳过。如需强制重建请传 force=True"
                )
                return existing

    # Step 1：获取概念名称及代码列表（本地缓存优先）
    all_concepts = _get_all_concepts(force_refresh=force)
    total = len(all_concepts)

    # Step 2：根据模式选择初始数据及目标概念集合
    if retry_empty_concepts_only:
        existing_full = _load_json(_MAP_FILE)
        if not existing_full:
            logger.warning(
                "retry_empty_concepts_only=True 但未找到现有映射文件，将按全量模式重新构建"
            )
            stock_to_concepts: dict = {}
            concept_to_stocks: dict = {}
            done_concepts: set = set()
        else:
            existing_c2s: dict = existing_full.get("concept_to_stocks", {})
            existing_s2c: dict = existing_full.get("stock_to_concepts", {})

            all_concept_name_set = {c["name"] for c in all_concepts}
            # 1) 文件中记录了但成分股列表为空的概念
            empty_names = {name for name, codes in existing_c2s.items() if not codes}
            # 2) 在概念列表中但映射文件中完全不存在的概念
            missing_names = all_concept_name_set - set(existing_c2s.keys())

            target_concept_names = empty_names | missing_names
            if not target_concept_names:
                logger.info("未发现成分股为空或缺失的概念，不需要重试，直接返回现有映射")
                return existing_full

            logger.info(
                f"仅重试缺失概念，共 {len(target_concept_names)} 个：{sorted(target_concept_names)}"
            )

            # 以现有结果为基础增量更新：非目标概念视为已完成
            stock_to_concepts = existing_s2c
            concept_to_stocks = existing_c2s
            done_concepts = all_concept_name_set - target_concept_names
    else:
        # 原有“全量/续传”逻辑
        tmp = _load_json(_TMP_FILE)
        if tmp and not force:
            stock_to_concepts: dict = tmp.get("stock_to_concepts", {})
            concept_to_stocks: dict = tmp.get("concept_to_stocks", {})
            done_concepts: set = set(tmp.get("done_concepts", []))
            logger.info(
                f"发现中断进度：已完成 {len(done_concepts)}/{total} 个概念，从断点继续..."
            )
        else:
            stock_to_concepts = {}
            concept_to_stocks = {}
            done_concepts = set()

    remaining = total - len(done_concepts)
    logger.info(f"开始抓取成分股，剩余 {remaining} 个概念（数据源：THS）...")

    # Step 3：获取 THS 认证 v_code
    v_code = _get_ths_v_code()
    v_code_refresh_interval = 50   # 每处理 N 个概念后刷新 v_code
    _SAVE_INTERVAL = 20            # 每成功处理 N 个概念后自动保存一次进度
    fail_streak = 0                # 连续失败计数
    _MAX_FAIL_STREAK = 5           # 连续失败 N 次则终止并保存进度
    processed_count = 0            # 本次运行已处理概念数

    def _save_tmp():
        _save_json(_TMP_FILE, {
            "stock_to_concepts": stock_to_concepts,
            "concept_to_stocks": concept_to_stocks,
            "done_concepts": list(done_concepts),
        })

    # Step 4：逐概念抓成分股
    try:
        for idx, concept in enumerate(all_concepts, 1):
            concept_name = concept["name"]
            concept_code = concept["code"]

            if concept_name in done_concepts:
                continue

            # 定期刷新 v_code，避免 Cookie 过期
            if processed_count > 0 and processed_count % v_code_refresh_interval == 0:
                logger.info("刷新 THS v_code...")
                v_code = _get_ths_v_code()

            try:
                codes = _get_concept_stocks_ths(concept_code, v_code)

                concept_to_stocks[concept_name] = codes
                for code in codes:
                    stock_to_concepts.setdefault(code, [])
                    if concept_name not in stock_to_concepts[code]:
                        stock_to_concepts[code].append(concept_name)

                done_concepts.add(concept_name)
                fail_streak = 0
                processed_count += 1
                logger.info(
                    f"[{idx}/{total}] {concept_name} ({concept_code}): {len(codes)} 只"
                )

                # 周期性保存进度，防止意外中断丢失数据
                if processed_count % _SAVE_INTERVAL == 0 and not retry_empty_concepts_only:
                    _save_tmp()
                    logger.info(
                        f"进度自动保存（已完成 {len(done_concepts)}/{total}）"
                    )

            except Exception as e:
                fail_streak += 1
                logger.warning(
                    f"[{idx}/{total}] {concept_name} 抓取异常（{type(e).__name__}: {e}），"
                    f"连续失败 {fail_streak}/{_MAX_FAIL_STREAK}"
                )
                if fail_streak >= _MAX_FAIL_STREAK and not retry_empty_concepts_only:
                    logger.warning("连续失败次数达到上限，终止本次运行并保存进度")
                    _save_tmp()
                    logger.info(
                        f"进度已保存，下次运行将从 『{concept_name}』 附近继续"
                    )
                    return {
                        "_meta": {
                            "status": "incomplete",
                            "stopped_at": datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "done": len(done_concepts),
                            "total": total,
                        },
                        "stock_to_concepts": stock_to_concepts,
                        "concept_to_stocks": concept_to_stocks,
                    }

            time.sleep(_SLEEP_BETWEEN_CONCEPTS)

    except KeyboardInterrupt:
        logger.warning("用户手动中断，保存当前进度...")
        if not retry_empty_concepts_only:
            _save_tmp()
            logger.info(
                f"进度已保存（已完成 {len(done_concepts)}/{total}），下次运行将从断点继续"
            )
        return {
            "_meta": {
                "status": "interrupted",
                "stopped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "done": len(done_concepts),
                "total": total,
            },
            "stock_to_concepts": stock_to_concepts,
            "concept_to_stocks": concept_to_stocks,
        }

    # Step 5：全部完成，写入最终文件
    result = {
        "_meta": {
            "status": "complete",
            "source": "ths",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_concepts": len(concept_to_stocks),
            "total_stocks": len(stock_to_concepts),
        },
        "stock_to_concepts": stock_to_concepts,
        "concept_to_stocks": concept_to_stocks,
    }
    _save_json(_MAP_FILE, result)

    if os.path.exists(_TMP_FILE) and not retry_empty_concepts_only:
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
    """返回映射表的元信息（更新时间、数据源、统计数量等）"""
    return _get_map().get("_meta", {})


def is_map_available() -> bool:
    """判断本地缓存是否存在"""
    return os.path.exists(_MAP_FILE)


def _match_concept_names(pattern: str, all_names: list[str]) -> list[str]:
    """
    按模式匹配概念名称列表。

    支持 SQL LIKE 风格的 ``%`` 通配符：
      - ``%化工%``  → 名称中包含"化工"
      - ``化工%``   → 名称以"化工"开头
      - ``%化工``   → 名称以"化工"结尾
      - ``化工``    → 精确匹配（不含 ``%`` 时）
    """
    import fnmatch
    if "%" in pattern:
        # 将 SQL LIKE 的 % 转为 fnmatch 的 *
        return [n for n in all_names if fnmatch.fnmatch(n, pattern.replace("%", "*"))]
    # 无通配符：精确匹配
    return [pattern] if pattern in all_names else []


def get_candidate_stocks_by_concepts(
    concepts: list[str],
    output_file: str = None,
) -> list[str]:
    """
    按概念名称（支持多个，支持模糊匹配）汇总候选股代码列表。

    取所有匹配概念成分股的并集，去重并排序，可选写入文件（格式与
    ``bin/candidate_temp/candidate_stocks_ready.txt`` 保持一致，每行一个代码）。

    Args:
        concepts: 概念名称列表，每项支持：

            * 精确名称：``"光芯片"``
            * SQL LIKE 风格通配符（``%``）：

              - ``"%化工%"``  → 所有名称含"化工"的概念
              - ``"化工%"``   → 所有名称以"化工"开头的概念
              - ``"%化工"``   → 所有名称以"化工"结尾的概念

        output_file: 输出文件路径；为 None 时仅返回列表，不写文件

    Returns:
        去重排序后的股票代码列表
    """
    data = _get_map()
    concept_to_stocks = data.get("concept_to_stocks", {})
    all_concept_names = list(concept_to_stocks.keys())

    code_set: set[str] = set()
    for pattern in concepts:
        matched = _match_concept_names(pattern, all_concept_names)
        if not matched:
            logger.warning(f"模式 '{pattern}' 未匹配到任何概念")
            continue
        if "%" in pattern:
            logger.info(f"模式 '{pattern}' 匹配到 {len(matched)} 个概念: {matched}")
        for name in matched:
            code_set.update(concept_to_stocks.get(name, []))

    result = sorted(code_set)

    if output_file:
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(result) + "\n")
        logger.info(f"候选股已写入: {output_file}（共 {len(result)} 只）")

    return result
