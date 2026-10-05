"""无日志检测：文件活动、启动器退出、静默清理与重试。"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from conftest import dump_yaml  # noqa: E402

from script_chainer.config.script_config import (  # noqa: E402
    ScriptChainConfig,
    ScriptConfig,
)
from script_chainer.services.log_activity import LogFileActivity  # noqa: E402
from script_chainer.win_exe import script_runner as runner  # noqa: E402


class TestLogPathConfig(unittest.TestCase):
    def test_chain_round_trip_keeps_log_path_relative_to_script(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        script = root / "scripts" / "launcher.exe"
        script.parent.mkdir()
        script.touch()
        chain = root / "chain.yml"
        chain.write_text(
            dump_yaml(
                {
                    "script_list": [
                        {
                            "script_path": "scripts/launcher.exe",
                            "log_path": "data/logs/*.log",
                            "log_analysis_path": "%TEMP%/report.txt",
                            "no_log_timeout_seconds": 300,
                            "no_log_max_retries": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        for _ in range(2):
            config = ScriptChainConfig(file_path=str(chain))
            item = config.script_list[0]
            self.assertEqual(item.log_path, "data/logs/*.log")
            self.assertEqual(item.runtime_log_path, script.parent / "data/logs/*.log")
            self.assertEqual(item.no_log_timeout_seconds, 300)
            self.assertEqual(item.no_log_max_retries, 1)
            self.assertEqual(item.copy().log_path, item.log_path)
            config.save()

    def test_log_path_forms(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        cases = (
            ("empty", "", None),
            ("whitespace", "  ", None),
            ("relative", "logs/main.log", root / "logs/main.log"),
            ("backslash", r"logs\main.log", root / "logs/main.log"),
            ("absolute", str(root / "other/out.log"), root / "other/out.log"),
            ("windows", r"D:\scripts\out.log", Path("D:/scripts/out.log")),
            ("temp", "%TEMP%/task/*.txt", root / "task/*.txt"),
        )
        with patch(
            "script_chainer.config.script_config.tempfile.gettempdir",
            return_value=str(root),
        ):
            for name, raw, expected in cases:
                with self.subTest(name=name):
                    config = ScriptConfig(
                        script_path=str(root / "launcher.exe"), log_path=raw
                    )
                    self.assertEqual(config.runtime_log_path, expected)

    def test_invalid_path_is_reported_before_launch(self):
        for raw in (None, 123, "logs/*/out.log", "logs?/out.log", "logs/**.log"):
            with self.subTest(raw=raw):
                config = ScriptConfig(
                    script_path=sys.executable,
                    check_done="script_closed",
                    kill_game_after_done=False,
                    log_path=raw,
                    no_log_timeout_seconds=30,
                )
                self.assertIn("log_path", config.invalid_message)


class TestLogFileActivity(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_existing_file_append_overwrite_truncate_and_replace(self):
        path = self.root / "main.log"
        path.write_bytes(b"old")
        monitor = LogFileActivity(path)
        self.assertFalse(monitor.poll(), "旧日志不应延长本次运行的期限")
        path.write_bytes(b"old plus new")
        self.assertTrue(monitor.poll())
        self.assertFalse(monitor.poll())
        before = path.stat()
        path.write_bytes(b"NEW plus new")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        self.assertTrue(monitor.poll(), "等长改写仍是活动")
        path.write_bytes(b"")
        self.assertTrue(monitor.poll(), "截断仍是活动")
        before = path.stat()
        replacement = self.root / "replacement"
        replacement.write_bytes(b"")
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(path)
        self.assertTrue(monitor.poll(), "同大小同时间的文件替换仍是活动")
        path.unlink()
        self.assertFalse(monitor.poll(), "只删除文件不算活动")
        path.write_bytes(b"recreated")
        self.assertTrue(monitor.poll())

    def test_missing_directory_and_file_created_after_start(self):
        for pattern in ("new/run.log", "glob/*.log"):
            with self.subTest(pattern=pattern):
                monitor = LogFileActivity(self.root / pattern)
                self.assertFalse(monitor.poll())
                path = self.root / Path(pattern).parent / "run.log"
                path.parent.mkdir()
                path.write_bytes(b"hello")
                self.assertTrue(monitor.poll())
                self.assertFalse(monitor.poll())

    def test_filename_glob_rotation_ignores_other_files_and_subdirectories(self):
        directory = self.root / "[game] 中文"
        directory.mkdir()
        old = directory / "day1.log"
        old.write_bytes(b"old")
        monitor = LogFileActivity(directory / "day?.log")
        (directory / "unrelated.txt").touch()
        nested = directory / "day9.log"
        nested.mkdir()
        (nested / "day3.log").write_bytes(b"nested")
        self.assertFalse(monitor.poll())
        old.rename(directory / "day0.log")
        (directory / "day2.log").write_bytes(b"new day")
        self.assertTrue(monitor.poll())
        self.assertFalse(monitor.poll())
        (directory / "day0.log").unlink()
        self.assertFalse(monitor.poll())

    def test_access_error_warns_once_and_preserves_baseline(self):
        path = self.root / "main.log"
        path.write_bytes(b"old")
        monitor = LogFileActivity(path)
        with (
            patch.object(Path, "stat", side_effect=PermissionError("locked")),
            self.assertLogs(
                "script_chainer.services.log_activity", level="WARNING"
            ) as logs,
        ):
            self.assertFalse(monitor.poll())
            self.assertFalse(monitor.poll())
        self.assertEqual(len(logs.output), 1)
        self.assertIn("PermissionError", logs.output[0])
        self.assertFalse(monitor.poll(), "恢复访问不能把旧日志当作新活动")
        path.write_bytes(b"new content")
        self.assertTrue(monitor.poll())

    def test_initial_access_error_does_not_make_old_files_new(self):
        path = self.root / "old.log"
        path.write_bytes(b"old")
        with (
            patch(
                "script_chainer.services.log_activity.os.scandir",
                side_effect=PermissionError("locked"),
            ),
            self.assertLogs("script_chainer.services.log_activity", level="WARNING"),
        ):
            monitor = LogFileActivity(self.root / "*.log")
        self.assertFalse(monitor.poll())
        path.write_bytes(b"new content")
        self.assertTrue(monitor.poll())


class TestNoLogRun(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.root / "runtime.log"
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

    def test_launcher_exit_with_file_updates_does_not_timeout_then_silence_does(self):
        self.config.launcher_mode = True
        self.config.script_process_name = ["worker.exe"]
        self.enterContext(
            patch.object(runner, "_get_target_process_infos", return_value=[Mock()])
        )
        run, state = self.prepare_run()
        for tick in (131.0, 162.0):
            self.now = tick
            with self.path.open("ab") as stream:
                stream.write(b"worker running\n")
            self.assertFalse(run._is_done())
            self.assertEqual(state.last_log_time, tick)
        self.now = 193.0
        with self.assertRaises(runner._NoLogTimeoutError):
            run._is_done()

    def test_stdout_alone_keeps_unchanged_or_unconfigured_file_alive(self):
        for path in (str(self.path), ""):
            with self.subTest(path=path):
                self.config.log_path = path
                run, state = self.prepare_run()
                self.now += 31
                callback = runner._make_stdout_callback("test", state=state)
                with patch("builtins.print"):
                    callback("stdout or stderr")
                self.assertFalse(run._is_done())
                self.assertEqual(state.last_log_time, self.now)
                self.now += 31
                with self.assertRaises(runner._NoLogTimeoutError):
                    run._is_done()

    def test_old_or_missing_log_does_not_extend_deadline(self):
        for raw in (str(self.path), str(self.root / "missing.log")):
            with self.subTest(path=raw):
                self.config.log_path = raw
                run, _ = self.prepare_run()
                self.now += 31
                with self.assertRaises(runner._NoLogTimeoutError):
                    run._is_done()

    def test_file_baseline_precedes_launch_and_is_reset_for_retry(self):
        def launch(*args):
            self.path.write_bytes(b"new startup log")
            return self.pm

        self.launch.side_effect = launch
        run, state = self.prepare_run()
        self.now += 31
        self.assertFalse(run._is_done())
        self.assertEqual(state.last_log_time, self.now)
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

    def test_normal_completion_takes_priority_over_silence(self):
        run, _ = self.prepare_run()
        self.now += 31
        self.pm.is_running.return_value = False
        self.assertTrue(run._is_done())

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
                self.assertIsNone(runner._active_pm)


if __name__ == "__main__":
    unittest.main()
