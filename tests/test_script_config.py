"""测试脚本链配置中 script_path 的相对路径解析。

原则（与 review 结论一致）：
- 绝对路径原样使用，不被修改。
- 相对路径优先按脚本链目录解析（用户脚本约定，落点在 <链目录>/scripts/）；
  若该位置不存在，再回退按项目根解析（内置脚本 scripts/... 约定，
  与 GUI 侧 subscript.resolve_script_path / get_script_path 一致）。

回归：相对 script_path 绝不能一律按项目根解析（那样会破坏用户脚本约定），
也不能一律按脚本链目录解析（那样内置脚本 scripts/shutdown.bat 会被错误拼成
config/script_chain/scripts/shutdown.bat 而找不到，表现为运行时
「脚本配置不合法 跳过运行 脚本路径不存在」）。
"""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

# 让 script_chainer 顶层包（src/runner）加入导入路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from script_chainer.config.script_config import ScriptChainConfig  # noqa: E402


def _write_chain(root: Path, script_path: str, name: str = "88") -> str:
    """在 <root>/config/script_chain/<name>.yml 写一个含单条 external 脚本的链配置。"""
    chain_dir = root / "config" / "script_chain"
    chain_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "script_list": [
            {
                "display_name": "自动关机",
                "script_type": "external",
                "script_path": script_path,
                "check_done": "script_closed",
                "run_timeout_seconds": 60,
                "kill_game_after_done": False,
                "enabled": True,
            }
        ]
    }
    p = chain_dir / f"{name}.yml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(p)


class TestScriptPathResolution(unittest.TestCase):
    def test_user_script_relative_resolves_against_chain_dir(self):
        """用户脚本（落点 config/script_chain/scripts/）按链目录解析（优先）。"""
        root = Path(tempfile.mkdtemp())
        # 用户脚本实际放在 <链目录>/scripts/ 下。
        user_dir = root / "config" / "script_chain" / "scripts"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "foo.bat").write_text("@echo off\n", encoding="utf-8")

        chain_path = _write_chain(root, "scripts/foo.bat")
        cfg = ScriptChainConfig(file_path=chain_path)

        expected = str((user_dir / "foo.bat").resolve())
        self.assertEqual(cfg.script_list[0].script_path, expected)
        self.assertIsNone(cfg.script_list[0].invalid_message)

    def test_builtin_script_relative_falls_back_to_project_root(self):
        """内置脚本 scripts/shutdown.bat 不在链目录下时，回退到项目根解析。"""
        root = Path(tempfile.mkdtemp())
        # 内置脚本按部署结构放在 <root>/scripts/ 下，链目录下没有同名文件。
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "shutdown.bat").write_text("@echo off\n", encoding="utf-8")

        chain_path = _write_chain(root, "scripts/shutdown.bat")
        cfg = ScriptChainConfig(file_path=chain_path)

        expected = str((root / "scripts" / "shutdown.bat").resolve())
        self.assertEqual(cfg.script_list[0].script_path, expected)
        self.assertIsNone(cfg.script_list[0].invalid_message)

    def test_relative_path_never_resolves_under_script_chain_scripts_for_builtin(self):
        """回归：内置脚本不能被拼成 config/script_chain/scripts/shutdown.bat。"""
        root = Path(tempfile.mkdtemp())
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "shutdown.bat").write_text("@echo off\n", encoding="utf-8")

        chain_path = _write_chain(root, "scripts/shutdown.bat")
        cfg = ScriptChainConfig(file_path=chain_path)

        wrong = str(
            (root / "config" / "script_chain" / "scripts" / "shutdown.bat").resolve()
        )
        self.assertNotEqual(cfg.script_list[0].script_path, wrong)

    def test_absolute_script_path_is_kept_as_is(self):
        root = Path(tempfile.mkdtemp())
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        abs_path = str((root / "scripts" / "shutdown.bat").resolve())
        (root / "scripts" / "shutdown.bat").write_text("@echo off\n", encoding="utf-8")

        chain_path = _write_chain(root, abs_path)
        cfg = ScriptChainConfig(file_path=chain_path)
        self.assertEqual(cfg.script_list[0].script_path, abs_path)


if __name__ == "__main__":
    unittest.main()
