"""测试脚本链全阻塞模式下的容错行为。

验证：当链中任一脚本失败（抛异常 / sys.exit(非0) / 外部进程启动失败 /
外部进程崩溃 / 运行超时），后续阻塞脚本应继续执行，整条链不应中断。

注意：run_timeout_seconds 超时仅对外部脚本（子进程）生效，
Python 脚本（进程内 exec）不受超时保护。

外部脚本（script_type=external）的构造有两种方案：
1. 统一方案 _make_external_python：script_path 直接用当前解释器
   (sys.executable)，脚本文件经 script_arguments 传入。Windows/Linux
   行为完全一致，不依赖 .bat/.sh 语法，退出码直接反映脚本退出码。
2. 真实包装方案 _write_external_script：Windows 生成 .bat、其他平台生成
   .sh，模拟真实外部程序（保留跨平台分支验证真实场景）。
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import yaml

# 让仓库根（script_chainer 顶层包）加入导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script_chainer.win_exe import script_runner  # noqa: E402
from script_chainer.win_exe.script_runner import run_chain  # noqa: E402

# ─── 辅助函数：构造临时脚本与链配置 ──────────────────────────────


def _write_marker_script(tmp_dir: Path, marker: Path) -> str:
    """写一个创建 marker 空文件的简单 .py 脚本，返回脚本路径。"""
    p = tmp_dir / "marker.py"
    # 每次调用需要不同文件名，用 marker 名称作区分
    p = tmp_dir / f"marker_{marker.stem}.py"
    p.write_text(
        f"open({str(marker)!r}, 'w').close()\n",
        encoding="utf-8",
    )
    return str(p)


def _write_raise_script(tmp_dir: Path, label: str = "boom") -> str:
    """写一个抛 RuntimeError 的 .py 脚本，返回脚本路径。"""
    p = tmp_dir / f"raise_{label}.py"
    p.write_text(f"raise RuntimeError('{label}')\n", encoding="utf-8")
    return str(p)


def _write_exit_script(tmp_dir: Path, exit_code: int, label: str = "") -> str:
    """写一个 sys.exit(code) 的 .py 脚本，返回脚本路径。"""
    suffix = f"_{label}" if label else ""
    p = tmp_dir / f"exit{exit_code}{suffix}.py"
    p.write_text(
        f"import sys\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return str(p)


def _write_syntax_error_script(tmp_dir: Path) -> str:
    """写一个包含语法错误的 .py 脚本，返回脚本路径。"""
    p = tmp_dir / "syntax_error.py"
    p.write_text("this is not valid python @@@\n", encoding="utf-8")
    return str(p)


def _write_sleep_script(
    tmp_dir: Path, seconds: int, pid_file: Path | None = None
) -> str:
    """写一个睡眠 seconds 秒的 .py 脚本，可选记录自身 PID 到 pid_file。"""
    p = tmp_dir / f"sleep_{seconds}s.py"
    lines = ["import os", "import time"]
    if pid_file is not None:
        lines.append(f"open({str(pid_file)!r}, 'w').write(str(os.getpid()))")
    lines.append(f"time.sleep({seconds})")
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


def _write_external_script(tmp_dir: Path, name: str, py_file: Path) -> str:
    """生成一个调用当前解释器执行 py_file 的外部脚本（Windows: .bat / 其他: .sh）。

    这是"真实外部程序"方案：被测对象是脚本链对 .bat/.sh 的启动、退出码传播处理。
    跨平台需要写两份语法（bat vs sh），且退出码经 cmd/sh 中转。
    """
    if sys.platform == "win32":
        p = tmp_dir / f"{name}.bat"
        p.write_text(
            f'@echo off\r\n"{sys.executable}" "{py_file}"\r\n',
            encoding="utf-8",
        )
    else:
        p = tmp_dir / f"{name}.sh"
        p.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{py_file}"\n',
            encoding="utf-8",
        )
        p.chmod(0o755)
    return str(p)


def _write_chain_config(tmp_dir: str, scripts: list[dict]) -> str:
    """写脚本链 YAML 配置文件，返回路径。"""
    p = Path(tmp_dir) / "chain.yml"
    data = {"script_list": scripts}
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(p)


def _make_blocking_python(path: str, **overrides) -> dict:
    """创建阻塞 Python 脚本配置，覆盖默认值以适配纯逻辑测试。"""
    return {
        "display_name": os.path.basename(path),
        "script_type": "python",
        "script_path": path,
        "block": True,
        "run_timeout_seconds": 10,
        "kill_script_after_done": False,
        "kill_game_after_done": False,
        **overrides,
    }


def _make_external_python(script_path: str, **overrides) -> dict:
    """创建外部脚本配置 —— 统一方案。

    ``script_path`` 直接用当前解释器（``sys.executable``），脚本文件经
    ``script_arguments`` 传入。这样 Windows / Linux 行为完全一致：
    不依赖 .bat/.sh 语法、退出码直接反映脚本退出码，无需平台分支。
    注：``script_arguments`` 经 ``shlex.split(posix=False)`` 拆分，
    故脚本路径不应包含空格。
    """
    return {
        "display_name": os.path.basename(script_path),
        "script_type": "external",
        "script_path": sys.executable,
        "script_arguments": str(script_path),
        "block": True,
        "check_done": "script_closed",
        "run_timeout_seconds": 10,
        "kill_script_after_done": False,
        "kill_game_after_done": False,
        **overrides,
    }


def _make_blocking_external(path: str, **overrides) -> dict:
    """创建阻塞外部脚本配置。"""
    return {
        "display_name": os.path.basename(path),
        "script_type": "external",
        "script_path": path,
        "block": True,
        "check_done": "script_closed",
        "run_timeout_seconds": 10,
        "kill_script_after_done": False,
        "kill_game_after_done": False,
        **overrides,
    }


def _is_process_alive(pid: int) -> bool:
    """检查 PID 对应的进程是否存活（跨平台）。

    os.kill(pid, 0) 仅探测进程存在性，不发送信号。
    """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _make_mock_subprocess_ready():
    """构造 _wait_for_subprocess_ready 的 mock，设置 state.script_ever_existed 并返回 True。

    用于绕过外部脚本崩溃时 _wait_for_subprocess_ready 的 20 秒硬编码超时
    （进程退出码非 0 会导致其轮询死循环直到超时）。
    """

    def _mock(pm, script_path, state, **kwargs):
        state.script_ever_existed = True
        return True

    return _mock


# ─── 测试类 ────────────────────────────────────────────────────


class TestBlockingChainResilience(unittest.TestCase):
    """全阻塞模式下脚本链的容错测试。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        # 统一 mock 掉所有 _exit_controller.wait，跳过组间 10 秒间隔和结尾 5 秒等待
        self._wait_patcher = mock.patch.object(
            script_runner._exit_controller, "wait", return_value=False
        )
        self._wait_patcher.start()

    def tearDown(self):
        self._wait_patcher.stop()

    def _run_and_check(self, scripts: list[dict], expected_markers: list[Path]) -> None:
        """运行链配置并断言所有 marker 均存在。"""
        cfg = _write_chain_config(self.tmp, scripts)
        run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        for m in expected_markers:
            self.assertTrue(
                m.exists(),
                f"预期 marker '{m.name}' 应存在（说明该脚本被执行），但未找到",
            )

    # ─── Python 脚本容错 ───────────────────────────────────────

    def test_exception_does_not_stop_chain(self):
        """链: [raise RuntimeError, marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_raise_script(self.tmp_path)),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )

    def test_system_exit_nonzero_does_not_stop_chain(self):
        """链: [sys.exit(1), marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_exit_script(self.tmp_path, 1)),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )

    def test_system_exit_zero_chain_continues(self):
        """链: [sys.exit(0), marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_exit_script(self.tmp_path, 0)),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )

    def test_syntax_error_does_not_stop_chain(self):
        """链: [语法错误脚本, marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_syntax_error_script(self.tmp_path)),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )

    def test_multiple_failures_chain_completes(self):
        """链: [raise, marker1, sys.exit(3), marker2] → 两个 marker 应均存在。"""
        m1 = self.tmp_path / "m1.txt"
        m2 = self.tmp_path / "m2.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_raise_script(self.tmp_path, "first")),
                _make_blocking_python(_write_marker_script(self.tmp_path, m1)),
                _make_blocking_python(_write_exit_script(self.tmp_path, 3, "second")),
                _make_blocking_python(_write_marker_script(self.tmp_path, m2)),
            ],
            [m1, m2],
        )

    def test_all_scripts_fail_chain_completes(self):
        """链中全部脚本失败时 run_chain 不应抛异常。"""
        fails = [
            _write_raise_script(self.tmp_path, "a"),
            _write_exit_script(self.tmp_path, 1, "b"),
            _write_syntax_error_script(self.tmp_path),
        ]
        cfg = _write_chain_config(
            self.tmp,
            [_make_blocking_python(p) for p in fails],
        )
        run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        # 抵达此处即说明未抛异常

    def test_first_and_last_fail_middle_ok(self):
        """链: [raise, marker1, marker2, sys.exit(2)] → 两个 marker 应均存在。"""
        m1 = self.tmp_path / "m1.txt"
        m2 = self.tmp_path / "m2.txt"
        self._run_and_check(
            [
                _make_blocking_python(_write_raise_script(self.tmp_path, "first")),
                _make_blocking_python(_write_marker_script(self.tmp_path, m1)),
                _make_blocking_python(_write_marker_script(self.tmp_path, m2)),
                _make_blocking_python(_write_exit_script(self.tmp_path, 2, "last")),
            ],
            [m1, m2],
        )

    # ─── 外部脚本容错 ─────────────────────────────────────────

    def test_external_invalid_path_does_not_stop_chain(self):
        """链: [不存在的 .exe, marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        self._run_and_check(
            [
                _make_blocking_external(
                    "C:/nonexistent/fake_game.exe",
                    display_name="bad-external",
                ),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )

    def test_external_crash_does_not_stop_chain(self):
        """链: [外部脚本崩溃(sys.exit(1)), marker] → marker 应存在。

        统一方案：script_path=当前解释器，脚本经 script_arguments 传入。
        需要 mock _wait_for_subprocess_ready 以绕过其 20 秒硬编码超时
        （进程退出码非 0 时会进入死循环轮询直到超时）。
        """
        marker = self.tmp_path / "ok.txt"
        crash_py = _write_exit_script(self.tmp_path, 1, "crash")
        with mock.patch(
            "script_chainer.win_exe.script_runner._wait_for_subprocess_ready",
            side_effect=_make_mock_subprocess_ready(),
        ):
            self._run_and_check(
                [
                    _make_external_python(crash_py),
                    _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
                ],
                [marker],
            )

    def test_external_success_does_not_stop_chain(self):
        """链: [外部成功(marker1), 外部成功(marker2)] → 两个 marker 均应存在。

        统一方案下外部脚本 rc=0，_wait_for_subprocess_ready 会立即放行，
        无需任何 mock。
        """
        m1 = self.tmp_path / "m1.txt"
        m2 = self.tmp_path / "m2.txt"
        ext1 = _write_marker_script(self.tmp_path, m1)
        ext2 = _write_marker_script(self.tmp_path, m2)
        self._run_and_check(
            [_make_external_python(ext1), _make_external_python(ext2)],
            [m1, m2],
        )

    def test_external_fail_then_external_ok(self):
        """链: [外部exit(1), 外部marker] → 两个外部脚本，后者仍应执行。"""
        m1 = self.tmp_path / "m1.txt"
        crash_py = _write_exit_script(self.tmp_path, 1, "crash")
        ok_py = _write_marker_script(self.tmp_path, m1)
        with mock.patch(
            "script_chainer.win_exe.script_runner._wait_for_subprocess_ready",
            side_effect=_make_mock_subprocess_ready(),
        ):
            self._run_and_check(
                [_make_external_python(crash_py), _make_external_python(ok_py)],
                [m1],
            )

    def test_external_wrapper_bat_sh_success(self):
        """链: [外部包装脚本成功(.bat/.sh→python→marker), marker2] → 均执行。

        真实外部程序方案：被测对象是 .bat/.sh 的启动与退出码传播
        （保留跨平台分支，验证真实场景而非仅依赖统一方案）。
        """
        marker_ext = self.tmp_path / "ext_wrapper_ok.txt"
        marker_py = self.tmp_path / "py_ok.txt"
        wrapper_py = _write_marker_script(self.tmp_path, marker_ext)
        wrapper = _write_external_script(
            self.tmp_path, "wrapper_marker", Path(wrapper_py)
        )
        self._run_and_check(
            [
                _make_blocking_external(wrapper),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker_py)),
            ],
            [marker_ext, marker_py],
        )

    # ─── 超时容错 ─────────────────────────────────────────────

    def test_external_timeout_does_not_stop_chain(self):
        """链: [外部脚本 sleep(30) 且 run_timeout=2, Python marker] → marker 应存在。

        超时后 runner 打印"脚本运行超时"并继续下一个脚本；整链应快速结束
        （远小于 sleep 时长），不会卡死。
        """
        marker = self.tmp_path / "ok.txt"
        sleepy = _write_sleep_script(self.tmp_path, 30)
        cfg = _write_chain_config(
            self.tmp,
            [
                _make_external_python(
                    sleepy,
                    run_timeout_seconds=2,
                    kill_script_after_done=True,
                ),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
        )
        start = time.time()
        run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        elapsed = time.time() - start

        self.assertTrue(marker.exists(), "超时脚本后的 marker 应已执行")
        self.assertLess(elapsed, 15, f"整链应因超时而快速结束，实际耗时 {elapsed:.1f}s")

    def test_external_timeout_then_external_ok(self):
        """链: [外部 sleep(30) 且 run_timeout=2, 外部 marker] → marker 应存在。"""
        marker = self.tmp_path / "ok.txt"
        sleepy = _write_sleep_script(self.tmp_path, 30)
        ok_py = _write_marker_script(self.tmp_path, marker)
        cfg = _write_chain_config(
            self.tmp,
            [
                _make_external_python(
                    sleepy,
                    run_timeout_seconds=2,
                    kill_script_after_done=True,
                ),
                _make_external_python(ok_py),
            ],
        )
        start = time.time()
        run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)
        elapsed = time.time() - start

        self.assertTrue(marker.exists(), "超时脚本后的外部 marker 应已执行")
        self.assertLess(elapsed, 15, f"整链应因超时而快速结束，实际耗时 {elapsed:.1f}s")

    def test_external_timeout_process_is_killed(self):
        """超时脚本在 kill_script_after_done=True 时应被清理，不留孤儿进程。

        sleep 脚本把自身 PID 写入文件；超时返回后该 PID 不应再存活。
        """
        pid_file = self.tmp_path / "sleepy.pid"
        sleepy = _write_sleep_script(self.tmp_path, 60, pid_file=pid_file)
        marker = self.tmp_path / "ok.txt"
        cfg = _write_chain_config(
            self.tmp,
            [
                _make_external_python(
                    sleepy,
                    run_timeout_seconds=2,
                    kill_script_after_done=True,
                ),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
        )
        run_chain(chain_config_path=cfg, shutdown_delay=0, debug_index=None)

        self.assertTrue(marker.exists(), "超时脚本后的 marker 应已执行")
        self.assertTrue(pid_file.exists(), "sleep 脚本应已记录自身 PID")
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        self.assertFalse(
            _is_process_alive(pid),
            f"进程 {pid} 应已被清理（kill_script_after_done=True），但仍存活",
        )

    # ─── 混合脚本容错 ─────────────────────────────────────────

    def test_mixed_python_fail_then_external_ok(self):
        """链: [Python raise, 外部 marker(统一方案)] → marker 应存在。"""
        py_raise = _write_raise_script(self.tmp_path, "mixed")
        marker = self.tmp_path / "mixed_ok.txt"
        marker_py = _write_marker_script(self.tmp_path, marker)
        self._run_and_check(
            [
                _make_blocking_python(py_raise),
                _make_external_python(marker_py),
            ],
            [marker],
        )

    def test_mixed_external_fail_then_python_ok(self):
        """链: [不存在 .exe, Python marker] → marker 应存在。"""
        marker = self.tmp_path / "mixed2_ok.txt"
        self._run_and_check(
            [
                _make_blocking_external(
                    "C:/nonexistent/another_fake.exe",
                    display_name="bad-ext",
                ),
                _make_blocking_python(_write_marker_script(self.tmp_path, marker)),
            ],
            [marker],
        )


if __name__ == "__main__":
    unittest.main()
