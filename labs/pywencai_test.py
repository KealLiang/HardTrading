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
res = pywencai.get(query='20250409低开，实体涨幅大于12%，非涉嫌信息披露违规且非立案调查且非ST，非主板',
                   sort_key='股票代码', sort_order='desc', loop=True, cookie=config.ths_cookie)
print(res)
