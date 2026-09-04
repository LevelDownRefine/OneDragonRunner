"""测试「运行脚本前启动游戏」（ScriptConfig.game_path）。

覆盖范围：
- 配置校验：``ScriptConfig.invalid_message`` 对 game_path 的判定（等待时长为
  模块常量 ``_GAME_LAUNCH_WAIT_SECONDS``，不参与配置）。
- 启动逻辑：``_launch_game_if_needed`` 的分支（未配置 / 已在运行 / 拉起并等待 /
  启动失败 / 等待被中断）。

原则：不真起游戏进程，``ProcessManager.open_process`` 与 ``is_process_existed``
均打桩；等待走 ``_exit_controller.wait`` 的打桩，不真实耗时。
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

# 让 script_chainer 顶层包（src/runner）加入导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script_chainer.config.script_config import ScriptConfig  # noqa: E402
from script_chainer.win_exe import script_runner  # noqa: E402

# 仓库内真实存在的文件，充当「存在」的脚本/游戏路径占位
_EXISTING_FILE = str(REPO_ROOT / "launcher.py")


def _config(**kwargs) -> ScriptConfig:
    """构造一条合法的 external 脚本配置，再叠加本用例关心的字段。"""
    base = {
        "display_name": "终末地",
        "script_type": "external",
        "script_path": _EXISTING_FILE,
        "check_done": "script_closed",
        "kill_game_after_done": False,
    }
    base.update(kwargs)
    return ScriptConfig(**base)


class TestGamePathValidation(unittest.TestCase):
    """game_path 相关字段的合法性校验。"""

    def test_no_game_path_is_valid(self):
        """未配置 game_path：不校验游戏字段（现有脚本全部走这条）。"""
        self.assertIsNone(_config().invalid_message)

    def test_missing_game_path_is_invalid(self):
        """配了 game_path 但文件不存在 → 不合法。"""
        cfg = _config(game_path="D:/not/exist/Endfield.exe")
        self.assertEqual(
            cfg.invalid_message, "游戏路径不存在 D:/not/exist/Endfield.exe"
        )

    def test_existing_game_path_is_valid(self):
        """配了 game_path 且文件存在 → 合法。"""
        self.assertIsNone(_config(game_path=_EXISTING_FILE).invalid_message)


class TestLaunchGameIfNeeded(unittest.TestCase):
    """_launch_game_if_needed 的分支。

    ``print_message`` 一并打桩：它内部会调 ``_exit_controller.wait(0.1)``
    （见 script_runner.print_message），不打桩会把日志输出的等待混进 wait 断言。
    """

    def test_no_game_path_skips(self):
        """未配置 game_path：不启动、不等待，直接放行。"""
        with (
            mock.patch.object(script_runner, "print_message"),
            mock.patch.object(script_runner, "ProcessManager") as pm,
            mock.patch.object(script_runner, "is_process_existed") as existed,
        ):
            self.assertTrue(script_runner._launch_game_if_needed(_config()))
        pm.assert_not_called()
        existed.assert_not_called()

    def test_running_game_skips_launch(self):
        """游戏已在运行：跳过启动，也不等待。"""
        cfg = _config(game_path="D:/Endfield.exe", game_process_name="Endfield.exe")
        with (
            mock.patch.object(script_runner, "print_message"),
            mock.patch.object(script_runner, "ProcessManager") as pm,
            mock.patch.object(script_runner, "is_process_existed", return_value=True),
            mock.patch.object(script_runner._exit_controller, "wait") as wait,
        ):
            self.assertTrue(script_runner._launch_game_if_needed(cfg))
        pm.assert_not_called()
        wait.assert_not_called()

    def test_launches_and_waits(self):
        """未运行：拉起游戏并按 _GAME_LAUNCH_WAIT_SECONDS 等待就绪。"""
        cfg = _config(game_path="D:/Endfield.exe", game_process_name="Endfield.exe")
        with (
            mock.patch.object(script_runner, "print_message"),
            mock.patch.object(script_runner, "ProcessManager") as pm,
            mock.patch.object(script_runner, "is_process_existed", return_value=False),
            mock.patch.object(
                script_runner._exit_controller, "wait", return_value=False
            ) as wait,
        ):
            self.assertTrue(script_runner._launch_game_if_needed(cfg))
        pm.return_value.open_process.assert_called_once_with("D:/Endfield.exe")
        wait.assert_called_once_with(script_runner._GAME_LAUNCH_WAIT_SECONDS)

    def test_launch_failure_blocks_script(self):
        """启动抛异常：不再运行本脚本。"""
        cfg = _config(game_path="D:/Endfield.exe")
        with (
            mock.patch.object(script_runner, "print_message"),
            mock.patch.object(script_runner, "ProcessManager") as pm,
            mock.patch.object(script_runner, "is_process_existed", return_value=False),
        ):
            pm.return_value.open_process.side_effect = OSError("boom")
            self.assertFalse(script_runner._launch_game_if_needed(cfg))

    def test_interrupted_wait_blocks_script(self):
        """等待被退出信号打断：跳过本脚本。"""
        cfg = _config(game_path="D:/Endfield.exe")
        with (
            mock.patch.object(script_runner, "print_message"),
            mock.patch.object(script_runner, "ProcessManager"),
            mock.patch.object(script_runner, "is_process_existed", return_value=False),
            mock.patch.object(
                script_runner._exit_controller, "wait", return_value=True
            ),
        ):
            self.assertFalse(script_runner._launch_game_if_needed(cfg))
