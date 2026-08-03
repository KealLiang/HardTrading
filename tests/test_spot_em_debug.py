"""临时诊断：ak.stock_zh_a_spot_em 分页失败（Expecting value / 空响应）"""
from __future__ import annotations

import json
import os
import pickle
import tempfile
import traceback
from pathlib import Path

import requests

URLS = [
    "https://push2delay.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
    "https://82.push2.eastmoney.com/api/qt/clist/get",
]

BASE_PARAMS = {
    "pn": "1",
    "pz": "20",
    "po": "1",
    "np": "1",
    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2",
    "invt": "2",
    "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,"
    "f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
}

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Connection": "keep-alive",
    "Referer": "https://quote.eastmoney.com/center/gridlist.html",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    ),
}


def _summarize_response(r: requests.Response) -> dict:
    text = r.text or ""
    info = {
        "status": r.status_code,
        "content_type": r.headers.get("Content-Type"),
        "len": len(r.content),
        "text_preview": repr(text[:200]),
    }
    try:
        data = r.json()
        diff = (data.get("data") or {}).get("diff") if isinstance(data, dict) else None
        info["json_ok"] = True
        info["total"] = (data.get("data") or {}).get("total") if isinstance(data, dict) else None
        info["diff_len"] = len(diff) if isinstance(diff, list) else None
        info["rc"] = data.get("rc") if isinstance(data, dict) else None
    except Exception as e:
        info["json_ok"] = False
        info["json_err"] = f"{type(e).__name__}: {e}"
    return info


def probe_urls(pages=(1, 3), pz: int = 20) -> None:
    print("=" * 60)
    print(f"1) 探测各东财域名 page={pages}, pz={pz}")
    for url in URLS:
        print("-" * 60)
        print(f"URL: {url}")
        for pn in pages:
            params = dict(BASE_PARAMS)
            params["pn"] = str(pn)
            params["pz"] = str(pz)
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=15)
                info = _summarize_response(r)
                print(f"  page={pn}: {json.dumps(info, ensure_ascii=False)}")
            except Exception as e:
                print(f"  page={pn}: REQUEST_ERR {type(e).__name__}: {e}")


def inspect_cache() -> Path | None:
    print("=" * 60)
    print("2) 检查断点缓存")
    td = Path(tempfile.gettempdir())
    caches = list(td.glob("em_cache_*.pkl"))
    if not caches:
        print("  无缓存文件")
        return None
    for f in caches:
        try:
            with open(f, "rb") as fh:
                d = pickle.load(fh)
            print(
                f"  {f.name}: page={d.get('page')} total={d.get('total')} "
                f"cached_pages={len(d.get('data', []))} size={f.stat().st_size}"
            )
        except Exception as e:
            print(f"  {f.name}: load_err {e}")
    return caches[0]


def try_akshare(clear_cache: bool = False) -> None:
    print("=" * 60)
    print(f"3) 调用 ak.stock_zh_a_spot_em(clear_cache={clear_cache})")
    if clear_cache:
        td = Path(tempfile.gettempdir())
        for f in td.glob("em_cache_*.pkl"):
            f.unlink(missing_ok=True)
            print(f"  已删除缓存: {f}")

    import akshare as ak
    from akshare.utils import func as ak_func

    print(f"  akshare={getattr(ak, '__version__', '?')}")
    print(f"  fetch_paginated_data @ {ak_func.__file__}")

    try:
        df = ak.stock_zh_a_spot_em()
        print(f"  OK rows={len(df)} cols={list(df.columns)[:8]}...")
        print(df.head(2).to_string())
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        traceback.print_exc()


def stability_compare(pages: int = 8, pz: int = 100, sleep_s: float = 0.15) -> None:
    import time

    print("=" * 60)
    print(f"4) 稳定性对比 pages=1..{pages}, pz={pz}")
    for url in URLS:
        ok = fail = 0
        print("-" * 60)
        print(f"URL: {url}")
        for pn in range(1, pages + 1):
            params = dict(BASE_PARAMS)
            params["pn"] = str(pn)
            params["pz"] = str(pz)
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=15)
                good = r.status_code == 200 and (r.text or "").startswith("{")
                if good:
                    ok += 1
                    print(f"  page={pn}: OK status={r.status_code} len={len(r.content)}")
                else:
                    fail += 1
                    print(
                        f"  page={pn}: BAD status={r.status_code} "
                        f"preview={repr((r.text or '')[:100])}"
                    )
            except Exception as e:
                fail += 1
                print(f"  page={pn}: ERR {type(e).__name__}: {e}")
            time.sleep(sleep_s)
        print(f"  => ok={ok} fail={fail}")


def try_retry_fetch(max_retries: int = 5, pz: int = 100, sleep_s: float = 0.8) -> None:
    """在 push2delay 上加重试，验证能否完整拉完全市场。"""
    import math
    import time

    import pandas as pd

    print("=" * 60)
    print(f"5) push2delay + retry 完整拉取 (pz={pz}, retries={max_retries})")
    url = URLS[0]
    params = dict(BASE_PARAMS)
    params["pz"] = str(pz)

    def get_page(pn: int) -> dict:
        last_err = None
        for attempt in range(1, max_retries + 1):
            try:
                p = dict(params)
                p["pn"] = str(pn)
                r = requests.get(url, params=p, headers=HEADERS, timeout=30)
                if r.status_code != 200 or not (r.text or "").startswith("{"):
                    raise RuntimeError(
                        f"bad status={r.status_code} preview={repr((r.text or '')[:80])}"
                    )
                data = r.json()
                if not data.get("data") or data["data"].get("diff") is None:
                    raise RuntimeError(f"empty data payload: {data}")
                return data
            except Exception as e:
                last_err = e
                print(f"  page={pn} attempt={attempt} FAIL: {e}")
                time.sleep(sleep_s * attempt)
        raise RuntimeError(f"page {pn} failed after retries: {last_err}")

    first = get_page(1)
    per_page = len(first["data"]["diff"])
    total = first["data"]["total"]
    total_page = math.ceil(total / per_page)
    print(f"  total={total} per_page={per_page} pages={total_page}")
    frames = [pd.DataFrame(first["data"]["diff"])]
    for pn in range(2, total_page + 1):
        data = get_page(pn)
        frames.append(pd.DataFrame(data["data"]["diff"]))
        if pn % 10 == 0 or pn == total_page:
            print(f"  progress {pn}/{total_page}")
        time.sleep(0.05)
    df = pd.concat(frames, ignore_index=True)
    print(f"  OK rows={len(df)}")


if __name__ == "__main__":
    import sys

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("all", "probe"):
        inspect_cache()
        probe_urls(pages=(1, 3), pz=20)
        probe_urls(pages=(1,), pz=100)
    if mode in ("all", "stability"):
        stability_compare(pages=8, pz=100)
    if mode in ("all", "ak"):
        try_akshare(clear_cache=True)
    if mode in ("all", "fix", "retry"):
        try_retry_fetch()
