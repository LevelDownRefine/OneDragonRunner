import subprocess
import threading
from typing import Callable, List, Optional

from script_chainer.utils import os_utils
from script_chainer.utils.log_utils import log

# CREATE_NO_WINDOW 仅在 Windows 平台存在；非 Windows 用 0 表示无特殊创建标志，
# 保证同一份代码在 Linux/macOS CI 上也能正常执行（不创建隐藏窗口）。
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_command(
    commands: List[str],
    cwd: Optional[str] = None,
    message_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    执行命令行
    :param commands: 需要执行的命令
    :param cwd: 命令的执行目录
    :param message_callback: 命令行日志的回调
    :return 执行结果的 stdout
    """
    command_str = " ".join(commands)
    log.info(command_str)
    if message_callback is not None:
        message_callback(command_str)
    if cwd is None:  # 这个不写在入参默认值中 防止后续函数返回值会变
        cwd = os_utils.get_work_dir()

    try:
        # 在Windows上
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # 为子进程指定不创建新窗口的标志（非 Windows 上为 0）
        creationflags = _CREATE_NO_WINDOW

        process = subprocess.Popen(
            commands,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
            text=True,
            encoding="utf-8",  # 指定编码为 GBK
            errors="ignore",  # 忽略解码错误
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        result_str: str = ""

        def read_pipe(pipe, log_func):
            nonlocal result_str
            for line in iter(pipe.readline, ""):
                line_strip = line.strip().strip('"')
                if len(line_strip) == 0:
                    continue
                log_func(line_strip)
                if message_callback is not None:
                    message_callback(line_strip)
                result_str = result_str + "\n" + line_strip

        # 创建两个线程分别处理 stdout 和 stderr
        stdout_thread = threading.Thread(
            target=read_pipe, args=(process.stdout, log.info)
        )
        stderr_thread = threading.Thread(
            target=read_pipe, args=(process.stderr, log.error)
        )

        # 启动线程
        stdout_thread.start()
        stderr_thread.start()

        # 等待线程结束
        stdout_thread.join()
        stderr_thread.join()

        # 等待子进程完成
        process.wait()

        if process.returncode == 0:
            return result_str.strip()
        else:
            return None
    except Exception:
        log.error("执行命令失败", exc_info=True)
        return None


if __name__ == "__main__":
    run_command(["taskkill", "/F", "/IM", "git.exe"])
