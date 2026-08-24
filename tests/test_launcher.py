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

# 让仓库根（script_chainer 顶层包、launcher 模块所在目录）加入导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from conftest import dump_yaml as _dump_yaml  # noqa: E402

from launcher import main  # noqa: E402
from script_chainer.config.script_config import ScriptChainConfig  # noqa: E402
from script_chainer.utils.runtime_group_utils import (  # noqa: E402
    build_runtime_selection,
    resolve_runtime_groups,
)
from script_chainer.win_exe import script_runner  # noqa: E402
from script_chainer.win_exe.script_runner import run_chain  # noqa: E402


def _write_chain(tmp_dir: str, data: dict, name: str = "smoke") -> str:
    p = Path(tmp_dir) / f"{name}.yml"
    p.write_text(_dump_yaml(data), encoding="utf-8")
    return str(p)


def _write_external_script(tmp_dir: Path, name: str, py_file: Path) -> str:
    """生成一个调用当前解释器执行 py_file 的外部脚本（Windows: .bat / 其他: .sh）。"""
    if sys.platform == "win32":
        p = tmp_dir / f"{name}.bat"
        p.write_text(
            f'@echo off\r\n"{sys.executable}" "{py_file}"\r\n', encoding="utf-8"
        )
    else:
        p = tmp_dir / f"{name}.sh"
        p.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{py_file}"\n', encoding="utf-8"
        )
        p.chmod(0o755)
    return str(p)


# 细粒度单测：脚本链解析（dry-run 等价物，纯函数、不启动进程）。
# 复刻 run_chain 执行前的解析步骤，供 agent 在不拉起游戏（避开 1600s 超时）的
# 前提下验证「--debug-index N 究竟会跑哪些脚本」。
_BASE_SCRIPT = {
    "script_type": "external",
    "script_path": "C:/fake/game.exe",
    "game_process_name": "YuanShen.exe",
    "check_done": "game_or_script_closed",
    "run_timeout_seconds": 100,
    "block": True,
    "attach_direction": "",
    "enabled": True,
}


def _write_chain_scripts(scripts: list[dict]) -> str:
    """写临时脚本链 yml（缺省字段用 _BASE_SCRIPT 填充），返回路径。"""
    normalized = []
    for i, s in enumerate(scripts):
        item = dict(_BASE_SCRIPT)
        item.update(s)
        if "script_path" not in s:
            item["script_path"] = f"C:/fake/script_{i}.exe"
        normalized.append(item)
    path = Path(tempfile.mkdtemp()) / "chain.yml"
    path.write_text(
        _dump_yaml({"script_list": normalized}),
        encoding="utf-8",
    )
    return str(path)


def _resolve(chain_path: str, debug_index):
    """复刻 run_chain 执行前的解析步骤，返回 (groups, skipped, cfg)。"""
    cfg = ScriptChainConfig(file_path=chain_path)
    targets = cfg.compute_attach_targets()
    sel = build_runtime_selection(cfg.script_list, targets, debug_index=debug_index)
    groups, skipped = resolve_runtime_groups(sel)
    return groups, skipped, cfg


class TestAttachTargets(unittest.TestCase):
    """compute_attach_targets 对 attach_direction 的解析。"""

    def test_pre_attaches_to_next_non_pre(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {
                    "display_name": "stubB",
                    "script_type": "python",
                    "attach_direction": "pre",
                },
                {"display_name": "gameC"},
            ]
        )
        cfg = ScriptChainConfig(file_path=path)
        targets = cfg.compute_attach_targets()
        names = [t.display_name if t else None for t in targets]
        self.assertEqual(names, [None, "gameC", None])

    def test_post_attaches_to_prev_non_post(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {
                    "display_name": "stubB",
                    "script_type": "python",
                    "attach_direction": "post",
                },
                {"display_name": "gameC"},
            ]
        )
        cfg = ScriptChainConfig(file_path=path)
        targets = cfg.compute_attach_targets()
        names = [t.display_name if t else None for t in targets]
        self.assertEqual(names, [None, "gameA", None])

    def test_no_attach_are_none(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {"display_name": "gameB"},
            ]
        )
        cfg = ScriptChainConfig(file_path=path)
        self.assertEqual(cfg.compute_attach_targets(), [None, None])


class TestRuntimeSelection(unittest.TestCase):
    """build_runtime_selection 按 debug_index 裁剪参与脚本。"""

    def test_no_debug_index_selects_all(self):
        path = _write_chain_scripts([{"display_name": "a"}, {"display_name": "b"}])
        cfg = ScriptChainConfig(file_path=path)
        sel = build_runtime_selection(cfg.script_list, cfg.compute_attach_targets())
        self.assertEqual([s.display_name for s in sel.script_list], ["a", "b"])
        self.assertIsNone(sel.debug_target)

    def test_debug_index_keeps_target_only(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {
                    "display_name": "stubB",
                    "script_type": "python",
                    "attach_direction": "pre",
                },
                {"display_name": "gameC"},
            ]
        )
        cfg = ScriptChainConfig(file_path=path)
        targets = cfg.compute_attach_targets()
        sel = build_runtime_selection(cfg.script_list, targets, debug_index=0)
        self.assertEqual([s.display_name for s in sel.script_list], ["gameA"])
        self.assertEqual(sel.debug_target.display_name, "gameA")

    def test_debug_index_out_of_range_raises(self):
        path = _write_chain_scripts([{"display_name": "gameA"}])
        cfg = ScriptChainConfig(file_path=path)
        with self.assertRaises(ValueError):
            build_runtime_selection(
                cfg.script_list, cfg.compute_attach_targets(), debug_index=5
            )


class TestResolveRuntimeGroups(unittest.TestCase):
    """resolve_runtime_groups 的 enabled 过滤 / 挂靠跳过 / 分组合并。"""

    def test_disabled_script_skipped(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {"display_name": "gameB", "enabled": False},
            ]
        )
        groups, skipped, _ = _resolve(path, None)
        self.assertEqual([g.host.display_name for g in groups], ["gameA"])
        self.assertIn("脚本已禁用 跳过 gameB", skipped)

    def test_attached_to_disabled_skipped(self):
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {
                    "display_name": "stubB",
                    "script_type": "python",
                    "attach_direction": "pre",
                },
                {"display_name": "gameC", "enabled": False},
            ]
        )
        groups, skipped, _ = _resolve(path, None)
        self.assertEqual([g.host.display_name for g in groups], ["gameA"])
        self.assertIn("被挂靠脚本已禁用 跳过 stubB", skipped)

    def test_consecutive_same_host_merged(self):
        # stubB 用 post 挂靠到前方的 gameA，二者应并入同一运行组。
        path = _write_chain_scripts(
            [
                {"display_name": "gameA"},
                {
                    "display_name": "stubB",
                    "script_type": "python",
                    "attach_direction": "post",
                },
                {"display_name": "gameC"},
            ]
        )
        cfg = ScriptChainConfig(file_path=path)
        targets = cfg.compute_attach_targets()
        sel = build_runtime_selection(cfg.script_list, targets, debug_index=0)
        groups, _ = resolve_runtime_groups(sel)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            [s.display_name for s in groups[0].scripts], ["gameA", "stubB"]
        )


class TestLauncherArgParsing(unittest.TestCase):
    """launcher.main 解析命令行参数并正确调用 run_chain。"""

    def test_main_passes_chain_path_and_debug_index(self):
        with (
            mock.patch("launcher.run_chain") as rc,
            mock.patch.object(sys, "exit") as exit,
        ):
            sys.argv = [
                "launcher",
                "--chain",
                "config/script_chain/01.yml",
                "--debug-index",
                "2",
            ]
            main()
        rc.assert_called_once()
        kwargs = rc.call_args.kwargs
        self.assertEqual(kwargs["chain_config_path"], "config/script_chain/01.yml")
        self.assertEqual(kwargs["debug_index"], 2)
        exit.assert_called_once_with(0)

    def test_main_defaults(self):
        with mock.patch("launcher.run_chain") as rc, mock.patch.object(sys, "exit"):
            sys.argv = ["launcher"]
            main()
        kwargs = rc.call_args.kwargs
        self.assertEqual(kwargs["chain_config_path"], "config/script_chain/88.yml")
        self.assertIsNone(kwargs["debug_index"])

    def test_script_branch_runs_single_file(self):
        # --script 单文件模式：直接 exec .py，不经过脚本链编排，不调 run_chain。
        # 注意：不能 mock sys.exit，否则 sys.exit(0) 变空操作、执行会穿透到末尾的
        # run_chain(...)；这里让 sys.exit(0) 真正抛 SystemExit 以终止分支。
        with (
            mock.patch("launcher.run_chain") as rc,
            mock.patch("launcher._exec_python_file") as ef,
        ):
            sys.argv = ["launcher", "--script", "C:/fake/stub.py"]
            with self.assertRaises(SystemExit):
                main()
        ef.assert_called_once_with("C:/fake/stub.py")
        rc.assert_not_called()


class TestLauncherRunsThrough(unittest.TestCase):
    """真实调用 run_chain，确保主流程（配置加载 + 编排解析）跑通且不启动进程。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_empty_script_list_completes(self):
        cfg = _write_chain(self.tmp, {"script_list": []})
        # 跳过结尾 5 秒等待，加速 CI
        with mock.patch.object(
            script_runner._exit_controller, "wait", return_value=False
        ):
            run_chain(chain_config_path=cfg, debug_index=None)
        # 抵达此处即说明主流程（加载、编排、打印完成）跑通，未抛异常

    def test_disabled_script_is_skipped_without_launch(self):
        cfg = _write_chain(
            self.tmp,
            {
                "script_list": [
                    {"enabled": False, "display_name": "disabled-script"},
                ]
            },
        )
        with mock.patch.object(
            script_runner._exit_controller, "wait", return_value=False
        ):
            run_chain(chain_config_path=cfg, debug_index=None)
        # 禁用脚本在编排解析阶段被跳过，不会真正启动任何进程

    def test_non_blocking_scripts_run_and_waited(self):
        """整链模式下 block=False 的外部脚本后台启动，run_chain 末尾等待其完成。"""
        marker_block = Path(self.tmp) / "block.txt"
        marker_bg = Path(self.tmp) / "bg.txt"
        block_py = Path(self.tmp) / "block_script.py"
        block_py.write_text(
            f"import time\ntime.sleep(0.2)\nopen({str(marker_block)!r}, 'w').close()\n",
            encoding="utf-8",
        )
        bg_py = Path(self.tmp) / "bg_script.py"
        bg_py.write_text(
            f"import time\ntime.sleep(0.3)\nopen({str(marker_bg)!r}, 'w').close()\n",
            encoding="utf-8",
        )
        # 非阻塞仅支持外部脚本，故用平台脚本包一层调用当前解释器
        bg_external = _write_external_script(Path(self.tmp), "bg_script", bg_py)
        cfg = _write_chain(
            self.tmp,
            {
                "script_list": [
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
                ]
            },
        )
        with mock.patch.object(
            script_runner._exit_controller, "wait", return_value=False
        ):
            run_chain(chain_config_path=cfg, debug_index=None)
        # 非阻塞脚本在整链末尾被等待完成，故二者标记文件均应存在
        self.assertTrue(marker_bg.exists(), "非阻塞后台脚本应已运行")
        self.assertTrue(marker_block.exists(), "阻塞脚本应已运行")


if __name__ == "__main__":
    unittest.main()
