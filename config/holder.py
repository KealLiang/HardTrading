import configparser
import os
from pathlib import Path
from typing import Any


class Config:
    def __init__(self):
        self.config = configparser.ConfigParser()
        # 禁用插值，这样特殊字符 % 就不会导致解析错误
        self.config = configparser.ConfigParser(interpolation=None)
        self.env = os.getenv('ENV', 'development')
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration based on current environment."""
        # 定义配置文件的基础路径
        base_path = Path(__file__).parent.parent

        # 加载默认配置
        default_config = base_path / 'config' / 'local.ini'
        if default_config.exists():
            self.config.read(default_config)

    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """安全地获取配置值"""
        try:
            return self.config[section][key]
        except (KeyError, configparser.Error) as e:
            if fallback is not None:
                return fallback
            raise ValueError(f"Configuration {section}.{key} not found") from e

    @property
    def ths_cookie(self) -> str:
        """获取 THS cookie 配置"""
        return self.get('THS', 'cookie')


# 创建全局配置实例
config = Config()
