import json

import requests

webhoook_url = ''


def send_alert(message):
    headers = {
        'Content-Type': 'application/json'
    }
    payload = {
        'msg_type': 'text',
        'content': {
            'text': message
        }
    }
    response = requests.post(webhoook_url, headers=headers, data=json.dumps(payload))
    if response.status_code != 200:
        raise Exception(f"Failed to send message: {response.text}")
