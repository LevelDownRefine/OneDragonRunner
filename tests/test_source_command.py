"""独立解释器启动参数与工作目录。"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import psutil

from script_chainer.config.script_config import ScriptConfig
from script_chainer.win_exe.script_runner import _launch_script


class SourceCommandTests(unittest.TestCase):
    def test_stop_reaps_interpreter_and_child(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "main.py"
            script.write_text(
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "Path('child.pid').write_text(str(child.pid))\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            config = ScriptConfig(
                script_path=str(script),
                execution_program=getattr(sys, "_base_executable", sys.executable),
                execution_args=[str(script)],
                execution_cwd=directory,
            )
            manager = _launch_script(config)
            self.addCleanup(manager.kill)
            marker = Path(directory) / "child.pid"
            deadline = time.monotonic() + 15
            while not marker.is_file() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(marker.is_file())
            child_pid = int(marker.read_text())
            parent = manager.process
            self.assertIsNotNone(parent)
            manager.kill()
            self.assertIsNotNone(parent.poll())
            self.assertFalse(psutil.pid_exists(child_pid))

    def test_real_process_receives_arguments_and_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "main.py"
            script.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path('result.json').write_text(json.dumps([os.getcwd(), sys.argv[1:]]))\n",
                encoding="utf-8",
            )
            config = ScriptConfig(
                script_path=str(script),
                execution_program=getattr(sys, "_base_executable", sys.executable),
                execution_args=[str(script), "hello world"],
                execution_cwd=directory,
            )
            manager = _launch_script(config)
            self.assertIsNotNone(manager.process)
            self.assertEqual(manager.process.wait(timeout=15), 0)
            result = json.loads((Path(directory) / "result.json").read_text())
            self.assertEqual(Path(result[0]).resolve(), Path(directory).resolve())
            self.assertEqual(result[1], ["hello world"])

    def test_launch_passes_structured_command(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "main.py"
            script.touch()
            config = ScriptConfig(
                script_path=str(script),
                execution_program=sys.executable,
                execution_args=[str(script), "hello world"],
                execution_cwd=directory,
            )
            with patch(
                "script_chainer.win_exe.script_runner.ProcessManager"
            ) as manager:
                _launch_script(config)
            values = manager.return_value.open_process.call_args.kwargs
            self.assertEqual(values["program"], sys.executable)
            self.assertEqual(values["args"], [str(script), "hello world"])
            self.assertEqual(values["cwd"], directory)

    def test_missing_execution_directory_is_invalid(self):
        config = ScriptConfig(execution_program=sys.executable)
        self.assertIn("工作目录不存在", config.invalid_message)

    def test_partial_command_and_python_type_are_rejected(self):
        config = ScriptConfig(execution_args=["main.py"])
        self.assertEqual(config.invalid_message, "执行程序为空")
        config = ScriptConfig(
            script_type="python",
            execution_program=sys.executable,
            execution_cwd=str(Path.cwd()),
        )
        self.assertEqual(config.invalid_message, "独立解释器须使用外部脚本类型")
