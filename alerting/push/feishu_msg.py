import json

import requests

from config.holder import config


def send_alert(message):
    webhook_url = config.feishu_webhook_url
    # 如果 webhook URL 为空，跳过推送
    if not webhook_url or webhook_url.strip() == '':
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
        response = requests.post(webhook_url, headers=headers, data=json.dumps(payload))
        if response.status_code != 200:
            print(f"[飞书推送失败] {response.status_code}: {response.text}")
    except Exception as e:
        print(f"[飞书推送异常] {e}")


if __name__ == '__main__':
    send_alert('测试消息')
