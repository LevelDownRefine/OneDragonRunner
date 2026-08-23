"""测试公共 fixtures / helpers。

pytest 与 unittest（python -m unittest discover）均会自动加载本目录的
``conftest.py``，故放于此处的共享 helper 可被同目录所有测试模块直接导入，
无需各自重复定义。
"""

from io import StringIO

from ruamel.yaml import YAML

_yaml = YAML()


def dump_yaml(data: dict) -> str:
    """将 dict 序列化为 YAML 字符串（取代 yaml.safe_dump，统一用 ruamel）。"""
    buf = StringIO()
    _yaml.dump(data, buf)
    return buf.getvalue()
