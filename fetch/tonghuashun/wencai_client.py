import pywencai
import pywencai.headers as pywencai_headers

from config.holder import config

_patched = False
_orig_wencai_headers = pywencai_headers.headers


def _wencai_headers(cookie=None, user_agent=None):
    """补充问财 WAF 所需的浏览器请求头，避免 403 Access Denied。"""
    h = _orig_wencai_headers(cookie, user_agent)
    h.update({
        'Referer': 'https://www.iwencai.com/unifiedwap/result',
        'Origin': 'https://www.iwencai.com',
        'Accept': 'application/json, text/plain, */*',
    })
    return h


def apply_pywencai_headers_patch():
    global _patched
    if _patched:
        return
    pywencai_headers.headers = _wencai_headers
    pywencai.wencai.headers = _wencai_headers
    _patched = True


def query_wencai(param, *, sort_key='股票代码', sort_order='desc', loop=True):
    apply_pywencai_headers_patch()
    df = pywencai.get(
        question=param,
        sort_key=sort_key,
        sort_order=sort_order,
        loop=loop,
        cookie=config.ths_cookie,
    )
    if df is None:
        print(f'问财查询失败，请检查 Cookie 或网络: {param}')
    return df


apply_pywencai_headers_patch()
