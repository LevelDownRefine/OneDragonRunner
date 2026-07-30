# OneDragonRunner

从 [OneDragon-Helper](https://github.com/LevelDownRefine/OneDragon-Helper) 抽出的**脚本链运行器**，作为独立仓库维护。

## 来源

vendored（fork）自上游 `OneDragon-ScriptChainer` 的运行逻辑，仅保留其不含 `opencv`/`pynput` 的纯编排部分：

- `script_chainer/` — 脚本链启动、进程管理、完成判定、重试、日志等编排逻辑（去掉了 gui / 配置编辑器 / 通知推送 / 上下文等可选模块）。
- `script_chainer/utils/` 内含原 `one_dragon` 基础层（`config_item` / `yaml_config` / `os_utils` / `log_utils` / `cmd_utils` 等），不含 controller / matcher 等游戏操控层；原 `one_dragon` 的配置框架（`config_item` / `yaml_config` / `yaml_operator`）现位于 `script_chainer/config/`。

> 注意：脚本链结束 / 重试的通知推送在抽出时**有意丢弃**（`ScriptChainerContext` / `LogNotifier` 未移植）。核心运行逻辑不受影响。

## 运行

由 OneDragon-Helper 的 GUI 通过子进程调用（进程隔离）：

```bash
python -m src.runner --chain <config_path> --debug-index <i>
```

`<config_path>` 为脚本链配置文件的路径（`.yml`），相对路径以项目根为基准（例如 `config/script_chain/88.yml`）。

独立使用时，将 `src/runner` 加入 `PYTHONPATH` 后同样以 `python -m src.runner` 启动；依赖 `pyyaml` / `colorama` / `psutil`（与主项目共用同一个 venv）。

## 配置

脚本链配置由调用方（OneDragon-Helper）生成在 `<项目根>/config/script_chain/<name>.yml`，运行器通过重写的 `get_work_dir()` 定位项目根后读取。
