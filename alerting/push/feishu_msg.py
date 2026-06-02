import json
import logging
import time

import requests

from config.holder import config

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_CONNECT_TIMEOUT = 3
_READ_TIMEOUT = 10
_RETRY_BACKOFF_SEC = (0.6, 1.5)


def _message_preview(message: str, max_len: int = 80) -> str:
    text = message.replace('\n', ' ')
    return text if len(text) <= max_len else text[:max_len] + '...'


def _build_payload(message: str) -> dict:
    return {
        'msg_type': 'text',
        'content': {
            'text': f'<at user_id="all">所有人</at> {message}',
        },
    }


def _parse_body(response: requests.Response):
    try:
        return response.json()
    except ValueError:
        return None


def _is_success(body) -> bool:
    return isinstance(body, dict) and body.get('code') == 0


def _is_retryable_http(status_code: int) -> bool:
    return status_code in (429, 500, 502, 503, 504)


def _is_retryable_api(body) -> bool:
    if not isinstance(body, dict) or body.get('code') == 0:
        return False
    msg = str(body.get('msg', '')).lower()
    hints = ('frequency', 'freq', 'limit', 'too many', 'rate', 'throttl', '限流', '频繁')
    return any(h in msg for h in hints)


def send_alert(message: str) -> None:
    """推送飞书文本告警。成功时静默返回；仅失败写入 logging.error。"""
    webhook_url = config.feishu_webhook_url
    if not webhook_url or not webhook_url.strip():
        logger.warning('[飞书推送跳过] webhook URL 未配置')
        return

    payload = _build_payload(message)
    preview = _message_preview(message)
    last_error = '未知错误'

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                webhook_url,
                headers={'Content-Type': 'application/json'},
                data=json.dumps(payload, ensure_ascii=False),
                timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
            )
        except requests.RequestException as exc:
            last_error = f'网络异常: {exc}'
            if attempt < _MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_SEC[attempt - 1])
                continue
            logger.error(
                '[飞书推送失败] %s | 已重试%d次 | 摘要: %s',
                last_error, _MAX_ATTEMPTS, preview,
            )
            return

        body = _parse_body(response)

        if response.status_code == 200 and _is_success(body):
            return

        if _is_retryable_http(response.status_code):
            last_error = f'HTTP {response.status_code}: {(response.text or "")[:200]}'
            should_retry = attempt < _MAX_ATTEMPTS
        elif response.status_code == 200 and _is_retryable_api(body):
            last_error = f"code={body.get('code')} msg={body.get('msg')}"
            should_retry = attempt < _MAX_ATTEMPTS
        else:
            detail = (response.text or '')[:300] if response.text else str(body)
            logger.error(
                '[飞书推送失败] HTTP %s body=%s | 摘要: %s',
                response.status_code, detail, preview,
            )
            return

        if should_retry:
            time.sleep(_RETRY_BACKOFF_SEC[attempt - 1])
            continue

        logger.error(
            '[飞书推送失败] %s | 已重试%d次 | 摘要: %s',
            last_error, attempt, preview,
        )
        return


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    send_alert('测试消息')
