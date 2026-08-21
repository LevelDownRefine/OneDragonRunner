"""测试 cmd_utils.shutdown_sys / _run_shutdown_confirm 的确认窗逻辑。"""

import subprocess
import sys
import unittest
from unittest import mock

from script_chainer.utils import cmd_utils


class TestRunShutdownConfirm(unittest.TestCase):
    """确认窗子进程：退出码决定关机与否。"""

    def _patch_win(self):
        return mock.patch.object(sys, "platform", "win32")

    def test_confirm_zero_returncode_shuts_down(self):
        with (
            self._patch_win(),
            mock.patch.object(cmd_utils.os.path, "isfile", return_value=True),
            mock.patch.object(subprocess, "run") as run,
        ):
            run.return_value = subprocess.CompletedProcess(
                args=["x"], returncode=0, stdout="Tk 创建成功\n"
            )
            self.assertTrue(cmd_utils._run_shutdown_confirm(45))
        run.assert_called_once()

    def test_cancel_nonzero_returncode_no_shutdown(self):
        with (
            self._patch_win(),
            mock.patch.object(cmd_utils.os.path, "isfile", return_value=True),
            mock.patch.object(subprocess, "run") as run,
        ):
            run.return_value = subprocess.CompletedProcess(
                args=["x"], returncode=1, stdout=""
            )
            self.assertFalse(cmd_utils._run_shutdown_confirm(45))

    def test_timeout_treated_as_cancel(self):
        with (
            self._patch_win(),
            mock.patch.object(cmd_utils.os.path, "isfile", return_value=True),
            mock.patch.object(
                subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 45)
            ),
        ):
            self.assertFalse(cmd_utils._run_shutdown_confirm(45))

    def test_oserror_falls_back_to_shutdown(self):
        with (
            self._patch_win(),
            mock.patch.object(cmd_utils.os.path, "isfile", return_value=True),
            mock.patch.object(subprocess, "run", side_effect=OSError("boom")),
        ):
            self.assertTrue(cmd_utils._run_shutdown_confirm(45))

    def test_missing_script_falls_back_to_shutdown(self):
        with (
            self._patch_win(),
            mock.patch.object(cmd_utils.os.path, "isfile", return_value=False),
        ):
            self.assertTrue(cmd_utils._run_shutdown_confirm(45))


class TestShutdownSys(unittest.TestCase):
    """shutdown_sys：win32 下确认才执行实际关机。"""

    def test_win32_confirm_then_force_shutdown(self):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(cmd_utils, "_run_shutdown_confirm", return_value=True),
            mock.patch.object(cmd_utils.os, "system") as system,
        ):
            cmd_utils.shutdown_sys(45)
        system.assert_called_once_with("shutdown /s /f /t 0")

    def test_win32_cancel_no_shutdown(self):
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(cmd_utils, "_run_shutdown_confirm", return_value=False),
            mock.patch.object(cmd_utils.os, "system") as system,
        ):
            cmd_utils.shutdown_sys(45)
        system.assert_not_called()

    def test_non_windows_no_shutdown(self):
        with (
            mock.patch.object(sys, "platform", "linux"),
            mock.patch.object(cmd_utils.os, "system") as system,
        ):
            cmd_utils.shutdown_sys(45)
        system.assert_not_called()


if __name__ == "__main__":
    unittest.main()
