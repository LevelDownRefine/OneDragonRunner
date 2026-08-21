import os
import subprocess
import sys
import threading
from typing import Callable, List, Optional

from script_chainer.utils import os_utils
from script_chainer.utils.log_utils import log


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

        # 为子进程指定不创建新窗口的标志
        creationflags = subprocess.CREATE_NO_WINDOW

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


def shutdown_sys(seconds: int):
    """
    关机：先弹倒计时确认窗，确认才关机；关窗/取消/超时则不关。
    :param seconds: 倒计时秒数
    :return: 无返回值，确认则关机，否则仅记录日志
    """
    if sys.platform != "win32":
        log.warning("非 Windows 平台不支持关机确认窗，跳过关机")
        return
    if _run_shutdown_confirm(seconds):
        log.info("准备关机")
        os.system("shutdown /s /f /t 0")
    else:
        log.info("已取消关机")


def _run_shutdown_confirm(countdown: int) -> bool:
    """
    拉起独立确认窗子进程，确认返回 True、取消/超时返回 False。
    :param countdown: 倒计时秒数
    :return: 确认返回 True，取消/超时返回 False
    """
    confirm_script = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "win_exe", "shutdown_confirm.py"
    )
    if not os.path.isfile(confirm_script):
        log.error("关机确认窗脚本缺失 %s，降级直接关机", confirm_script)
        return True
    try:
        proc = subprocess.run(
            [sys.executable, confirm_script, str(countdown)],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=countdown + 30,
        )
        out = (proc.stdout or "").strip()
        if out:
            for line in out.splitlines():
                log.info("[关机确认窗] %s", line)
        log.info("关机确认窗退出码=%d", proc.returncode)
        return proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        proc = getattr(e, "subprocess", None)
        if proc is not None:
            proc.kill()
        log.error("关机确认窗超时未响应，视为取消")
        return False
    except OSError as e:
        log.error("启动关机确认窗失败 %s，降级直接关机", e)
        return True


def cancel_shutdown_sys():
    """
    取消计划的自动关机
    使用 shutdown /a 命令
    :return:
    """
    os.system("shutdown /a")


if __name__ == "__main__":
    run_command(["taskkill", "/F", "/IM", "git.exe"])
