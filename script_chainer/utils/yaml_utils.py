from typing import IO, Any

from ruamel.yaml import YAML

# 与一方模块统一：ruamel 往返实例，保留注释 / 键序，按 YAML 1.2 解析。
_yaml = YAML(typ="rt")
_yaml.preserve_quotes = True
_yaml.width = 4096


def safe_load(stream: str | bytes | IO[str] | IO[bytes]) -> Any:
    """用 ruamel.yaml 安全解析 YAML（rt 模式，默认不允许任意对象构造）。"""
    return _yaml.load(stream)
