"""无日志检测：文件活动、控制台输出及超时清理重试。"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script_chainer.config.script_config import ScriptConfig  # noqa: E402
from script_chainer.services.log_activity import LogFileActivity  # noqa: E402
from script_chainer.win_exe import script_runner as runner  # noqa: E402


class TestLogFileActivity(unittest.TestCase):
    def test_log_paths_resolve_from_script_directory(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with patch(
            "script_chainer.config.script_config.tempfile.gettempdir",
            return_value=str(root),
        ):
            for raw, expected in (
                ("", None),
                ("logs/*.log", root / "logs/*.log"),
                (str(root / "out.log"), root / "out.log"),
                ("%TEMP%/task/*.txt", root / "task/*.txt"),
            ):
                with self.subTest(path=raw):
                    config = ScriptConfig(
                        script_path=str(root / "launcher.exe"), log_path=raw
                    )
                    self.assertEqual(config.runtime_log_path, expected)

    def test_creation_updates_and_rotation_count_but_old_logs_do_not(self):
        for pattern in ("run.log", "*.log"):
            with (
                self.subTest(pattern=pattern),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory) / "logs"
                monitor = LogFileActivity(root / pattern)
                self.assertFalse(monitor.poll())
                root.mkdir()
                path = root / "run.log"
                path.write_bytes(b"started")
                self.assertTrue(monitor.poll(), "启动后创建日志")
                monitor = LogFileActivity(root / pattern)
                self.assertFalse(monitor.poll(), "已有日志不刷新新一轮计时")
                for content in (b"started\nrunning", b""):
                    path.write_bytes(content)
                    self.assertTrue(monitor.poll())
                    self.assertFalse(monitor.poll())
                path.rename(root / "run.old")
                self.assertFalse(monitor.poll(), "删除旧文件不算活动")
                path.write_bytes(b"rotated")
                self.assertTrue(monitor.poll())


class TestNoLogRun(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = root / "runtime.log"
        self.path.write_bytes(b"old log")
        self.config = ScriptConfig(
            script_path=sys.executable,
            check_done="script_closed",
            kill_game_after_done=False,
            kill_script_after_done=False,
            log_path=str(self.path),
            no_log_timeout_seconds=30,
            no_log_max_retries=1,
        )
        self.now = 100.0
        self.enterContext(
            patch.object(runner.time, "monotonic", side_effect=lambda: self.now)
        )
        self.enterContext(patch.object(runner, "print_message"))
        self.enterContext(
            patch.object(runner, "is_process_existed", return_value=False)
        )
        self.enterContext(
            patch.object(runner, "_launch_game_if_needed", return_value=True)
        )
        self.pm = Mock()
        self.pm.process.poll.return_value = 0  # 启动器已退出，受管目标仍在运行。
        self.pm.is_running.return_value = True
        self.launch = self.enterContext(
            patch.object(runner, "_launch_script", return_value=self.pm)
        )
        runner._exit_controller.reset()
        self.addCleanup(runner._exit_controller.reset)

    def prepare_run(self):
        state = runner._RunMonitorState(
            script_ever_existed=True, last_log_time=self.now
        )
        run = runner._ScriptRun(self.config, state=state)
        self.assertTrue(run._prepare())
        return run, state

    def test_launcher_exit_with_file_updates_then_silence(self):
        self.config.launcher_mode = True
        self.config.script_process_name = ["worker.exe"]
        self.enterContext(
            patch.object(runner, "_get_target_process_infos", return_value=[Mock()])
        )
        run, _ = self.prepare_run()
        for tick in (131.0, 162.0):
            self.now = tick
            with self.path.open("ab") as stream:
                stream.write(b"worker running\n")
            self.assertFalse(run._is_done())
        self.now = 193.0
        with self.assertRaises(runner._NoLogTimeoutError):
            run._is_done()

    def test_stdout_keeps_unchanged_or_unconfigured_file_alive(self):
        for path in (str(self.path), ""):
            with self.subTest(path=path):
                self.config.log_path = path
                run, state = self.prepare_run()
                self.now += 31
                with patch("builtins.print"):
                    runner._make_stdout_callback("test", state=state)("stdout")
                self.assertFalse(run._is_done())
                self.now += 31
                with self.assertRaises(runner._NoLogTimeoutError):
                    run._is_done()

    def test_file_baseline_precedes_launch_and_is_reset_for_retry(self):
        def launch(*args):
            self.path.write_bytes(b"new startup log")
            return self.pm

        self.launch.side_effect = launch
        run, _ = self.prepare_run()
        self.now += 31
        self.assertFalse(run._is_done())
        self.launch.side_effect = None
        retry, _ = self.prepare_run()
        self.now += 31
        with self.assertRaises(runner._NoLogTimeoutError):
            retry._is_done()

    def test_disabled_and_nonblocking_do_not_scan_files(self):
        with patch.object(runner, "LogFileActivity") as monitor:
            self.config.no_log_timeout_seconds = 0
            run, _ = self.prepare_run()
            self.now += 300
            self.assertFalse(run._is_done())
            self.config.no_log_timeout_seconds = 30
            self.config.block = False
            run = runner._NonBlockScriptRun(self.config)
            self.assertTrue(run._prepare())
            self.assertFalse(run._is_done())
            monitor.assert_not_called()

    def test_silence_force_kills_and_respects_retry_count(self):
        def wait(seconds):
            self.now += 31
            return False

        for retries in (0, 1):
            with (
                self.subTest(retries=retries),
                patch.object(runner, "_wait_for_subprocess_ready", return_value=True),
                patch.object(runner._exit_controller, "wait", side_effect=wait),
            ):
                self.config.no_log_max_retries = retries
                self.launch.reset_mock()
                self.pm.kill.reset_mock()
                runner._run_external_script_with_retries(self.config)
                self.assertEqual(self.launch.call_count, retries + 1)
                self.assertEqual(self.pm.kill.call_count, retries + 1)


if __name__ == "__main__":
    unittest.main()
