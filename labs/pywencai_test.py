import pywencai
import logging
import os
from config.holder import config

# 禁用Node.js的弃用警告
os.environ["NODE_OPTIONS"] = "--no-deprecation"

# 配置logging，启用详细日志
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('pywencai')
logger.setLevel(logging.DEBUG)

# 使用debug=True参数来启用日志
res = pywencai.get(query='今日涨停', sort_order='asc', loop=True, debug=True, cookie=config.ths_cookie)
print(res)
