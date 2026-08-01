"""测试运行器入口 launcher：参数解析 + run_chain 主流程跑通（不启动任何外部进程）。

CI 通过该测试确保 launcher 内部逻辑可正常执行。run_chain 默认会在结尾等待 5 秒，
测试中以 mock 将其替换为即时返回，避免拖慢 CI；空脚本列表 / 禁用脚本确保不会真正
拉起任何游戏或脚本进程。
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

# 让仓库根（script_chainer 顶层包、launcher 模块所在目录）加入导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import main  # noqa: E402
from script_chainer.win_exe import script_runner  # noqa: E402
from script_chainer.win_exe.script_runner import run_chain  # noqa: E402


def _write_chain(tmp_dir: str, data: dict, name: str = "smoke") -> str:
    p = Path(tmp_dir) / f"{name}.yml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(p)


def _write_external_script(tmp_dir: Path, name: str, py_file: Path) -> str:
    """生成一个调用当前解释器执行 py_file 的外部脚本（Windows: .bat / 其他: .sh）。"""
    if sys.platform == "win32":
        p = tmp_dir / f"{name}.bat"
        p.write_text(f'@echo off\r\n"{sys.executable}" "{py_file}"\r\n', encoding="utf-8")
    else:
        p = tmp_dir / f"{name}.sh"
        p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{py_file}"\n', encoding="utf-8")
        p.chmod(0o755)
    return str(p)


class TestLauncherArgParsing(unittest.TestCase):
    """launcher.main 解析命令行参数并正确调用 run_chain。"""

    def test_main_passes_chain_path_and_debug_index(self):
        with mock.patch("launcher.run_chain") as rc, \
             mock.patch.object(sys, "exit") as exit:
            sys.argv = ["launcher", "--chain", "config/script_chain/01.yml",
                        "--debug-index", "2"]
            main()
        rc.assert_called_once()
        kwargs = rc.call_args.kwargs
        self.assertEqual(kwargs["chain_config_path"], "config/script_chain/01.yml")
        self.assertEqual(kwargs["debug_index"], 2)
        self.assertEqual(kwargs["shutdown_delay"], 0)
        exit.assert_called_once_with(0)

    def test_main_defaults(self):
        with mock.patch("launcher.run_chain") as rc, \
             mock.patch.object(sys, "exit"):
            sys.argv = ["launcher"]
            main()
        kwargs = rc.call_args.kwargs
        self.assertEqual(kwargs["chain_config_path"], "config/script_chain/88.yml")
        self.assertIsNone(kwargs["debug_index"])
        self.assertEqual(kwargs["shutdown_delay"], 0)


class TestLauncherRunsThrough(unittest.TestCase):
    """真实调用 run_chain，确保主流程（配置加载 + 编排解析）跑通且不启动进程。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_script_list_completes(self):
        cfg = _write_chain(self.tmp, {"script_list": []})
        # 跳过结尾 5 秒等待，加速 CI
        with mock.patch.object(script_runner._exit_controller, "wait", return_value=False):
            run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        # 抵达此处即说明主流程（加载、编排、打印完成）跑通，未抛异常

    def test_disabled_script_is_skipped_without_launch(self):
        cfg = _write_chain(self.tmp, {"script_list": [
            {"enabled": False, "display_name": "disabled-script"},
        ]})
        with mock.patch.object(script_runner._exit_controller, "wait", return_value=False):
            run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        # 禁用脚本在编排解析阶段被跳过，不会真正启动任何进程

    def test_non_blocking_scripts_run_and_waited(self):
        """整链模式下 block=False 的外部脚本后台启动，run_chain 末尾等待其完成。"""
        marker_block = Path(self.tmp) / "block.txt"
        marker_bg = Path(self.tmp) / "bg.txt"
        block_py = Path(self.tmp) / "block_script.py"
        block_py.write_text(
            "import time\ntime.sleep(0.2)\n"
            f"open({str(marker_block)!r}, 'w').close()\n",
            encoding="utf-8",
        )
        bg_py = Path(self.tmp) / "bg_script.py"
        bg_py.write_text(
            "import time\ntime.sleep(0.3)\n"
            f"open({str(marker_bg)!r}, 'w').close()\n",
            encoding="utf-8",
        )
        # 非阻塞仅支持外部脚本，故用平台脚本包一层调用当前解释器
        bg_external = _write_external_script(Path(self.tmp), "bg_script", bg_py)
        cfg = _write_chain(self.tmp, {"script_list": [
            {
                "display_name": "bg",
                "script_path": bg_external,
                "check_done": "script_closed",
                "block": False,
                "run_timeout_seconds": 30,
                "kill_script_after_done": False,
                "kill_game_after_done": False,
            },
            {
                "display_name": "block",
                "script_type": "python",
                "script_path": str(block_py),
                "block": True,
                "run_timeout_seconds": 30,
                "kill_script_after_done": False,
                "kill_game_after_done": False,
            },
        ]})
        with mock.patch.object(script_runner._exit_controller, "wait", return_value=False):
            run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        # 非阻塞脚本在整链末尾被等待完成，故二者标记文件均应存在
        self.assertTrue(marker_bg.exists(), "非阻塞后台脚本应已运行")
        self.assertTrue(marker_block.exists(), "阻塞脚本应已运行")


if __name__ == "__main__":
    unittest.main()
