# save as check_missing.py
import subprocess
import sys
import importlib


def check_package(package_name):
    """检查包是否可以导入"""
    # 特殊包名映射
    name_mappings = {
        "scikit_learn": "sklearn",
        "Pillow": "PIL",
        "python-dateutil": "dateutil",
        # 添加更多映射关系
    }
    
    # 特殊情况处理
    if package_name == "pywin32":
        try:
            import win32api  # pywin32的一个模块
            return True
        except ImportError:
            return False
    
    import_name = name_mappings.get(package_name, package_name.lower().replace('-', '_').replace('.', '_'))
    
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
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
    if check_package(pkg):
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
