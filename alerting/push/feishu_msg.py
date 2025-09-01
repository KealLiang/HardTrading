import json

import requests

webhoook_url = ''


def send_alert(message):
    # 如果 webhook URL 为空，跳过推送
    if not webhoook_url or webhoook_url.strip() == '':
        print(f"[飞书推送跳过] webhook URL 未配置: {message}")
        return

    headers = {
        'Content-Type': 'application/json'
    }
    payload = {
        'msg_type': 'text',
        'content': {
            'text': message
        }
    }
    try:
        response = requests.post(webhoook_url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            print(f"[飞书推送失败] {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[飞书推送异常] {e}")
