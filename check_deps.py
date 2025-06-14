# save as check_missing.py
import subprocess
import sys


def check_package(package_name):
    """检查包是否可以导入"""
    cmd = [sys.executable, "-c", f"import {package_name.lower().replace('-', '_').replace('.', '_')}"]
    try:
        subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


# 从requirements.txt读取依赖
with open('requirements.txt') as f:
    requirements = [line.strip().split('==')[0] for line in f if line.strip()]

# 常见的间接依赖
indirect_deps = ["et_xmlfile", "exchange_calendars", "python-dateutil", "pytz", "lxml"]

# 合并所有需要检查的包
all_packages = requirements + indirect_deps

# 检查每个包
missing = []
for pkg in all_packages:
    pkg_import_name = pkg.lower().replace('-', '_').replace('.', '_')
    if check_package(pkg_import_name):
        print(f"✓ {pkg}")
    else:
        missing.append(pkg)
        print(f"✗ {pkg} - 未安装")

# 输出安装命令
if missing:
    print("\n安装命令:")
    print(f"pip install {' '.join(missing)}")
else:
    print("\n所有依赖已安装!")
