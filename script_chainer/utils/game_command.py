"""游戏启动命令解析与旧配置转换。"""

import re


def parse_game_command(command: str) -> tuple[str, str]:
    """拆出可执行文件与原始参数；含空格的路径须用双引号。"""
    if not isinstance(command, str) or "\0" in command:
        raise ValueError("游戏启动命令无效")
    if not command.strip():
        return "", ""
    match = re.fullmatch(r'\s*(?:"([^"\r\n]+)"|([^\s"]+))(?:\s+(.*))?\s*', command)
    if match is None:
        raise ValueError("游戏启动命令格式无效，含空格的路径须用双引号")
    return match[1] or match[2], (match[3] or "").strip()
