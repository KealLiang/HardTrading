# -*- coding: utf-8 -*-
"""东财 WAF 按请求头拦截 → 给 requests 全局注入浏览器头；并禁用系统代理。"""
import os
for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']:
    os.environ[k] = ''
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import requests

_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://quote.eastmoney.com/',
    'Connection': 'keep-alive',
}

_orig_request = requests.Session.request

def _patched_request(self, method, url, **kw):
    hdrs = dict(_BROWSER_HEADERS)
    hdrs.update(kw.pop('headers', None) or {})
    kw['headers'] = hdrs
    kw.setdefault('timeout', 20)
    return _orig_request(self, method, url, **kw)

requests.Session.request = _patched_request
