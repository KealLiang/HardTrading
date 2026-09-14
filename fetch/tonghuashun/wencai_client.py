import logging

import pywencai
import pywencai.convert as pywencai_convert
import pywencai.headers as pywencai_headers
import pywencai.wencai as pywencai_wencai
import requests as rq

from config.holder import config

logger = logging.getLogger(__name__)

_patched = False
_orig_wencai_headers = pywencai_headers.headers

# 2026-09 起，问财下线了老的问句解析接口：
#   http://www.iwencai.com/customized/chart/get-robot-data   -> 404 Not Found
# 新入口（移动端/统一接口）：
#   https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data
# 差异：新入口必须用 form-urlencoded 提交（json= 会被判缺参数 -302），
# 返回体包了一层 status_code/status_msg，但 data.answer[0].txt[0].content.components
# 结构与老接口完全一致，因此 pywencai 的 convert() 可原样复用。
NEW_ROBOT_URL = 'https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data'
OLD_ROBOT_URL = 'http://www.iwencai.com/customized/chart/get-robot-data'


def _wencai_headers(cookie=None, user_agent=None):
    """补充问财 WAF 所需的浏览器请求头，避免 403 Access Denied。"""
    h = _orig_wencai_headers(cookie, user_agent)
    h.update({
        'Referer': 'https://www.iwencai.com/unifiedwap/result',
        'Origin': 'https://www.iwencai.com',
        'Accept': 'application/json, text/plain, */*',
    })
    return h


def _while_do(do, retry=10, sleep=0, tag=''):
    """带日志的重试，避免 pywencai 裸 except 把真实原因吞掉。"""
    import time

    last_error = None
    for i in range(retry):
        if sleep:
            time.sleep(sleep)
        try:
            return do()
        except Exception as e:  # noqa: BLE001
            last_error = e
            logger.warning(f'{tag} 第{i + 1}/{retry}次尝试失败: {type(e).__name__}: {e}')
    if last_error is not None:
        logger.error(f'{tag} 连续 {retry} 次失败，最后错误: {last_error}')
    return None


def _build_robot_payload(**kwargs):
    """构造问句解析请求体（新老接口参数一致）。"""
    data = {
        'add_info': "{\"urp\":{\"scene\":1,\"company\":1,\"business\":1},\"contentType\":\"json\",\"searchInfo\":true}",
        'perpage': '10',
        'page': 1,
        'source': 'Ths_iwencai_Xuangu',
        'log_info': "{\"input_type\":\"click\"}",
        'version': '2.0',
        'secondary_intent': kwargs.get('query_type', 'stock'),
        'question': kwargs.get('query'),
    }
    if kwargs.get('pro', False):
        data['iwcpro'] = 1
    return data


def _new_get_robot_data(**kwargs):
    """替换 pywencai.wencai.get_robot_data：优先新接口，失败回退老接口。"""
    retry = kwargs.get('retry', 10)
    sleep = kwargs.get('sleep', 0)
    cookie = kwargs.get('cookie', None)
    user_agent = kwargs.get('user_agent', None)
    request_params = kwargs.get('request_params', {})
    data = _build_robot_payload(**kwargs)

    def do_new():
        res = rq.request(
            method='POST',
            url=NEW_ROBOT_URL,
            data=data,  # 必须是 form 编码，json= 会返回 -302 缺少必要参数
            headers=_wencai_headers(cookie, user_agent),
            **request_params
        )
        body = res.json()
        if body.get('status_code') != 0:
            raise RuntimeError(
                f"问财接口异常 status_code={body.get('status_code')} "
                f"status_msg={body.get('status_msg')}"
            )
        return pywencai_convert.convert(res)

    def do_old():
        res = rq.request(
            method='POST',
            url=OLD_ROBOT_URL,
            json=data,
            headers=_wencai_headers(cookie, user_agent),
            **request_params
        )
        return pywencai_convert.convert(res)

    result = _while_do(do_new, retry, sleep, tag='[问财新接口]')
    if result is None:
        logger.warning('新接口不可用，回退老接口 %s', OLD_ROBOT_URL)
        result = _while_do(do_old, 2, sleep, tag='[问财老接口]')
    return result


def apply_pywencai_headers_patch():
    global _patched
    if _patched:
        return
    pywencai_headers.headers = _wencai_headers
    pywencai.wencai.headers = _wencai_headers
    pywencai_wencai.get_robot_data = _new_get_robot_data
    _patched = True


def query_wencai(param, *, sort_key='股票代码', sort_order='desc', loop=True):
    apply_pywencai_headers_patch()
    try:
        df = pywencai.get(
            question=param,
            sort_key=sort_key,
            sort_order=sort_order,
            loop=loop,
            cookie=config.ths_cookie,
        )
    except Exception as e:  # noqa: BLE001
        # 兜底：pywencai 内部 while_do 用裸 except，解析失败时会抛 AttributeError
        logger.error(f'问财查询异常: {param} -> {type(e).__name__}: {e}')
        df = None
    if df is None:
        print(f'问财查询失败，请检查 Cookie 或网络: {param}')
    return df


apply_pywencai_headers_patch()
