"""Windows C 运行时的参数规则，供游戏和脚本启动共用。"""


def parse_arguments(text: str) -> list[str]:
    """解析双引号及其前面的反斜杠，保留空参数。

    :param text: 不含程序路径的 Windows 参数文本。
    :return: 可直接传给 subprocess 的参数列表。
    """
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("启动参数必须是无空字符的文本")
    arguments = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index] in " \t":
            index += 1
        if index == len(text):
            break
        value = []
        quoted = False
        while index < len(text):
            if text[index] in " \t" and not quoted:
                break
            backslashes = 0
            while index < len(text) and text[index] == "\\":
                backslashes += 1
                index += 1
            if index < len(text) and text[index] == '"':
                value.extend("\\" * (backslashes // 2))
                if backslashes % 2:
                    value.append('"')
                elif quoted and index + 1 < len(text) and text[index + 1] == '"':
                    value.append('"')
                    index += 1
                else:
                    quoted = not quoted
                index += 1
            else:
                value.extend("\\" * backslashes)
                if index < len(text) and (quoted or text[index] not in " \t"):
                    value.append(text[index])
                    index += 1
        arguments.append("".join(value))
    return arguments
