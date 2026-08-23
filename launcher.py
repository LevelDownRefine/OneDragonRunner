"""脚本链运行器入口（替代原 OneDragon-ScriptChainer 的 win_exe.launcher）。

用法::

    python -m src.runner.launcher --chain config/script_chain/88.yml --debug-index 0

参数与原 ``script_chainer.win_exe.launcher`` 的 onedragon 模式对齐，
但省去了 GUI 编辑器与 ``ExeLauncher`` 依赖，直接调用
``script_chainer.win_exe.script_runner.run_chain``。
"""

from __future__ import annotations

import argparse
import atexit
import sys

from colorama import init

from script_chainer.server.chain_decorators import (
    with_auto_shutdown,
    with_system_mute,
)
from script_chainer.win_exe.runner_logging import configure_runner_runtime_logging
from script_chainer.win_exe.script_runner import (
    _cleanup_active_pm,
    _exec_python_file,
    _exit_controller,
    run_chain,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="OneDragon-Helper 脚本链运行器")
    parser.add_argument(
        "--chain",
        type=str,
        default="config/script_chain/88.yml",
        help="脚本链配置文件路径（.yml），相对路径以项目根为基准",
    )
    parser.add_argument(
        "-s",
        "--shutdown",
        type=int,
        nargs="?",
        const=60,
        default=0,
        help="运行后关机延迟秒数，默认 0 表示不关机",
    )
    parser.add_argument(
        "--debug-index",
        type=int,
        default=None,
        help="仅调试指定下标脚本，并按挂靠关系一并纳入关联脚本",
    )
    parser.add_argument(
        "--script",
        type=str,
        default=None,
        help="直接执行单个 Python 脚本文件（.py），供 GUI「启动脚本」在冻结模式下调用",
    )
    parser.add_argument(
        "--mute",
        action="store_true",
        default=False,
        help="运行中系统静音，链结束后自动恢复",
    )
    args = parser.parse_args()

    if args.script:
        # 单文件模式：直接 exec 一个 .py，不经过脚本链编排。
        # 用于 GUI「启动脚本」在冻结（PyInstaller）模式下替代 `python xxx.py`，
        # 因为此时 sys.executable 指向 GUI 自身的 exe 而非 python 解释器。
        init(autoreset=True)
        configure_runner_runtime_logging()
        _exit_controller.install_handlers(_cleanup_active_pm)
        atexit.register(_cleanup_active_pm)
        _exec_python_file(args.script)
        sys.exit(0)

    # 静音包在最外层，关机确认在内层（链正常跑完才触发）。
    decorated_chain = with_system_mute(args.mute)(
        with_auto_shutdown(args.shutdown or 0)(run_chain)
    )
    decorated_chain(
        chain_config_path=args.chain,
        debug_index=args.debug_index,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
