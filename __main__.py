"""脚本链运行器入口（替代原 OneDragon-ScriptChainer 的 win_exe.launcher）。

用法::

    python -m src.runner --chain 88 --debug-index 0

参数与原 ``script_chainer.win_exe.launcher`` 的 onedragon 模式对齐，
但省去了 GUI 编辑器与 ``ExeLauncher`` 依赖，直接调用
``script_chainer.win_exe.script_runner.run_chain``。
"""
from __future__ import annotations

import argparse
import sys

from script_chainer.win_exe.script_runner import run_chain


def main() -> None:
    parser = argparse.ArgumentParser(description="OneDragon-Helper 脚本链运行器")
    parser.add_argument(
        "--chain",
        type=str,
        default="88",
        help="脚本链名称（对应 config/script_chain/<name>.yml）",
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
    args = parser.parse_args()
    run_chain(
        chain_name=args.chain,
        shutdown_delay=args.shutdown or 0,
        debug_index=args.debug_index,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
