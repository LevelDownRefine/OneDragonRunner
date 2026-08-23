"""脚本链运行器的横切装饰器。"""

from __future__ import annotations

import functools
import sys

from script_chainer.utils.cmd_utils import shutdown_sys


def set_system_mute(mute_status: bool) -> bool:
    """设置系统扬声器静音状态（Windows 专属，按需 import pycaw）。

    Args:
        mute_status: True 静音，False 取消静音。

    Returns:
        成功执行返回 True；非 Windows 平台或 pycaw 不可用时返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        from ctypes import POINTER, cast

        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError:
        return False
    devices = AudioUtilities.GetSpeakers()
    interface = cast(
        devices.Activate(IAudioEndpointVolume._iid_, 0, None),
        POINTER(IAudioEndpointVolume),
    )
    interface.SetMute(bool(mute_status), None)
    return True


def with_system_mute(flag: bool):
    """参数化装饰器：被装饰函数执行前静音，结束后（含异常）恢复。

    Args:
        flag: True 启用环绕静音；False 返回原函数。

    Returns:
        装饰器；flag 为假时即原函数本身。
    """

    def decorator(func):
        if not flag:
            return func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            set_system_mute(True)
            try:
                return func(*args, **kwargs)
            finally:
                set_system_mute(False)

        return wrapper

    return decorator


def with_auto_shutdown(delay: int):
    """参数化装饰器：被装饰函数正常返回后，按 delay 秒触发关机确认。

    Args:
        delay: 倒计时秒数，<=0 时返回原函数。

    Returns:
        装饰器；delay 非正时即原函数本身。

    说明：链执行抛异常时不触发关机。
    """

    def decorator(func):
        if delay <= 0:
            return func

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            shutdown_sys(delay)
            return result

        return wrapper

    return decorator
