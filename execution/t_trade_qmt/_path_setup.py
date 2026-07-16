"""保证项目根在 sys.path 最前，避免 PyCharm 直接跑脚本时目录遮蔽。"""
from __future__ import annotations

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
_ROOT = _PKG_DIR.parents[1]


def ensure_project_root() -> Path:
    root = str(_ROOT)
    pkg = str(_PKG_DIR)
    # 去掉脚本目录，防止本目录下模块名（如旧的 config.py）遮蔽根包
    sys.path[:] = [p for p in sys.path if Path(p).resolve() != _PKG_DIR]
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    return _ROOT
