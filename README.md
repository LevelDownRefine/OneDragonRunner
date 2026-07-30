# OneDragonRunner

脚本链运行器，从 [OneDragon-ScriptChainer](https://github.com/OneDragon-Anything/OneDragon-ScriptChainer) 移植而来，作为独立仓库维护（仅保留不含 `opencv`/`pynput` 的纯编排部分）。

## 运行

由 OneDragon-Helper 的 GUI 通过子进程调用：

```bash
python -m src.runner.launcher --chain <config_path> --debug-index <i>
```

- `--chain <config_path>`：脚本链配置文件路径（`.yml`，相对路径以项目根为基准，例如 `config/script_chain/88.yml`）。
- `--debug-index <i>`：仅运行第 `i` 条脚本（及其挂靠组）。

依赖 `pyyaml` / `colorama` / `psutil`。
