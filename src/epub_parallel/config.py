"""配置加载：代码默认 < 配置文件 < 环境变量 < CLI 覆盖。"""

import json
import os
import types
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Union, get_args, get_origin

DEFAULT_CONFIG_PATH = "~/.config/epub-parallel/config.json"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    temperature: float = 0.2
    batch_size: int = 10
    timeout: float = 60.0
    max_retries: int = 3
    max_cost: float | None = None  # 单次运行预算上限（美元）
    input_price: float = 0.14  # 每百万输入 token 美元价
    output_price: float = 0.28  # 每百万输出 token 美元价
    disable_thinking: bool = True  # 关闭推理模式（省输出 token）
    skip_types: tuple = ("index", "copyright-page", "titlepage", "dedication", "colophon", "cover")

    @classmethod
    def from_env(cls, config_path=None, **overrides):
        """按优先级合并配置。config_path=None 用默认路径；overrides 为 CLI flag。"""
        path = DEFAULT_CONFIG_PATH if config_path is None else config_path
        cfg = cls()
        for k, v in load_config_file(path).items():
            setattr(cfg, k, v)
        env_key = os.environ.get("DEEPSEEK_API_KEY")
        if env_key:
            cfg.api_key = env_key
        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg


# 配置文件允许的字段（排除 api_key，key 只走环境变量）
_CONFIG_FIELDS = {f.name: f for f in fields(Config) if f.name != "api_key"}


def _coerce(name, value):
    field = _CONFIG_FIELDS[name]
    if value is None:
        return None
    typ = field.type
    if get_origin(typ) in (Union, types.UnionType):
        non_none = [a for a in get_args(typ) if a is not type(None)]
        if non_none:
            typ = non_none[0]
    if typ is bool:
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "no", "0", "off", "")
        return bool(value)
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    if typ is str:
        return str(value)
    if typ in (tuple, list):
        if isinstance(value, str):
            return tuple(v.strip() for v in value.split(",") if v.strip())
        return tuple(value)
    return value


def load_config_file(path):
    """读取配置文件，返回已校验的字段 dict；不存在返回 {}；损坏抛 ConfigError。"""
    p = Path(path).expanduser()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise ConfigError(f"配置文件损坏: {p} ({e})") from e
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件必须是 JSON 对象: {p}")
    result = {}
    for k, v in data.items():
        if k in _CONFIG_FIELDS:
            try:
                result[k] = _coerce(k, v)
            except (ValueError, TypeError) as e:
                raise ConfigError(f"配置字段 '{k}' 值无效: {p} ({e})") from e
    return result
