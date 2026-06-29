"""配置管理模块 — 读取和管理 Super Tutor 的全局配置。

【功能说明】
从 ~/.super-tutor/settings.json 文件中加载配置，并允许通过环境变量覆盖。
配置优先级：环境变量 > settings.json > 默认值。

【耦合关系】
- 被 app.py 的 _init_services() 调用，用于初始化数据库和 LLM 客户端
- 被 LLMClient 间接依赖（通过环境变量传递配置）
- 不依赖项目内其他模块
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TutorConfig:
    """Super Tutor 全局配置数据类。

    包含 API 密钥、API 地址、数据库路径和模型名称。
    通过 TutorConfig.load() 工厂方法创建实例。

    Attributes:
        api_key: DeepSeek API 密钥。可通过 TUTOR_API_KEY 环境变量覆盖。
        api_base_url: API 基础 URL，默认 https://api.deepseek.com。
        db_path: SQLite 数据库文件路径，默认 ~/.super-tutor/super_tutor.db。
        model: 默认模型名称，默认 deepseek-chat。
    """

    api_key: str = ""
    api_base_url: str = "https://api.deepseek.com"
    db_path: str = "~/.super-tutor/super_tutor.db"
    model: str = "deepseek-chat"

    # ------------------------------------------------------------------
    # 工厂方法：从文件 + 环境变量加载配置
    # ------------------------------------------------------------------

    @classmethod
    def load(cls) -> TutorConfig:
        """从 settings.json 和环境变量加载配置。

        优先级：环境变量 > settings.json > 默认值。

        Returns:
            TutorConfig: 填充了所有字段的配置实例。
        """
        config = cls()
        config._load_from_file()     # 步骤1: 从 JSON 文件加载
        config._apply_env_overrides() # 步骤2: 用环境变量覆盖
        return config

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    def _settings_path(self) -> Path:
        """返回 settings.json 的完整路径：~/.super-tutor/settings.json"""
        return Path.home() / ".super-tutor" / "settings.json"

    def _load_from_file(self) -> None:
        """从 settings.json 文件加载配置到当前实例。

        文件不存在或格式错误时静默跳过（使用默认值）。
        支持两种 JSON key 命名风格：
        - deepseek_api_key / deepseek_base_url（旧风格）
        - api_key / api_base_url（新风格）
        """
        path = self._settings_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return

        # JSON key → dataclass 字段名映射表
        _FILE_KEY_MAP = {
            "deepseek_api_key": "api_key",
            "deepseek_base_url": "api_base_url",
            "api_key": "api_key",
            "api_base_url": "api_base_url",
            "db_path": "db_path",
            "model": "model",
        }
        for file_key, attr in _FILE_KEY_MAP.items():
            if file_key in data:
                setattr(self, attr, data[file_key])

    def _apply_env_overrides(self) -> None:
        """用环境变量覆盖当前配置值。

        支持的环境变量：
        - TUTOR_API_KEY → api_key
        - TUTOR_API_BASE_URL → api_base_url
        - TUTOR_DB_PATH → db_path
        - TUTOR_MODEL → model
        """
        _ENV_MAP = {
            "TUTOR_API_KEY": ("api_key", str),
            "TUTOR_API_BASE_URL": ("api_base_url", str),
            "TUTOR_DB_PATH": ("db_path", str),
            "TUTOR_MODEL": ("model", str),
        }
        for env_var, (attr, cast) in _ENV_MAP.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    setattr(self, attr, cast(value))
                except (ValueError, TypeError):
                    pass  # 环境变量值非法时静默跳过
